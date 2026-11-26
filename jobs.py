"""Background jobs and the queue (STANDARDS.md: "The window never freezes", "Progress you can trust",
"A queue, not busy", "Pause and resume long jobs").

A job is a function f(..., log, progress) run on a worker thread. It reports progress with
progress(done, total, text, overall=None, eta=True, size=False): done/total are items (or bytes when
size=True), overall is the share of the whole job when it differs, eta is True (estimate it), False (none
yet) or seconds. Stop is cooperative: the next progress() call raises JobStopped, and any external process
the job registered (FFmpeg, the duplicate engine) is ended at once. A job returns a summary string, or
{"summary": ..., "next": (label, function)}, which the status bar keeps showing when it finishes."""
import subprocess
import sys
import threading
import time
from collections import deque

from PySide6.QtCore import QObject, Signal

import fileops
import logs

_local = threading.local()


class JobStopped(Exception):
    """Raised inside a job when Stop was pressed."""


def current():
    """The job running on this thread, or None."""
    return getattr(_local, "job", None)


def register_process(proc):
    """Tell the running job about an external process, so Stop can end it."""
    job = current()
    if job is not None:
        job.processes.append(proc)
        if job.stop_requested:
            job._kill(proc)


def check_stop():
    job = current()
    if job is not None and job.stop_requested:
        raise JobStopped()


class Job:
    def __init__(self, title, fn, *args, done=None, failed=None, short=None, own_log=False, gpu=None, page=None,
                 **kwargs):
        self.title = title              # "Converting GIFs": the status bar's job name
        self.short = short or title     # the title-bar pill's label
        self.fn, self.args, self.kwargs = fn, args, kwargs
        self.on_done, self.on_failed = done, failed
        self.own_log = own_log          # long jobs get their own log file
        self.gpu = gpu                  # None: no chip; "gpu" or "cpu": show which is in use
        self.page = page                # the tool that started it (for the rail and messages)
        self.lock = threading.Lock()
        self.stop_requested = False
        self.processes = []
        self.pause_target = None        # an object with pause() and resume(), when the job can pause
        self.stop_hook = None
        self.what = "Starting…"
        self.done_count, self.total, self.share, self.eta, self.size = 0, 0, None, True, False
        self.started = None
        self.last_change = None
        self.paused_at = None
        self.paused_total = 0.0
        self.finished = None             # "done", "stopped" or "failed"
        self.summary = ""
        self.next_step = None
        self.result = None
        self.error = None
        self.ended = None
        self.job_log = None
        self._bytes = deque(maxlen=40)

    # ----- called from the worker -----
    def progress(self, done, total, text="", overall=None, eta=True, size=False, *_ignored):
        if self.stop_requested:
            raise JobStopped()
        now = time.monotonic()
        with self.lock:
            key = (done, total, text, overall)
            if key != (self.done_count, self.total, self.what, self.share):
                self.last_change = now
            self.done_count, self.total = done, total
            if text:
                self.what = text
            self.share = overall
            self.eta = eta
            self.size = size
            if size:
                self._bytes.append((now, done))

    # ----- read by the status bar -----
    def elapsed(self):
        if self.started is None:
            return 0.0
        end = self.ended or self.paused_at or time.monotonic()
        return end - self.started - self.paused_total

    def fraction(self):
        """The share done, 0 to 1, or None when the size isn't known yet."""
        with self.lock:
            if self.share is not None:
                return max(0.0, min(1.0, self.share))
            if self.total:
                return max(0.0, min(1.0, self.done_count / self.total))
            return None

    def speed(self):
        """Bytes per second over the last few seconds, for downloads and copies."""
        with self.lock:
            points = list(self._bytes)
        recent = [p for p in points if p[0] >= points[-1][0] - 5] if points else []
        if len(recent) < 2 or recent[-1][0] == recent[0][0]:
            return None
        return (recent[-1][1] - recent[0][1]) / (recent[-1][0] - recent[0][0])

    def time_left(self):
        """Seconds left, or None while it's being worked out."""
        with self.lock:
            eta = self.eta
        if eta is False:
            return None
        if eta is not True and eta is not None:
            return max(0.0, float(eta))
        share = self.fraction()
        elapsed = self.elapsed()
        if share is None or share < 0.01 or elapsed < 3:
            return None
        return elapsed * (1 - share) / share

    def stalled_for(self):
        if self.last_change is None or self.paused_at is not None:
            return 0.0
        return time.monotonic() - self.last_change

    # ----- control, from the UI thread -----
    def stop(self):
        self.stop_requested = True
        if self.paused_at is not None:
            self.resume()
        for proc in list(self.processes):
            self._kill(proc)
        if self.stop_hook:
            try:
                self.stop_hook()
            except Exception:
                pass

    @staticmethod
    def _kill(proc):
        try:
            if proc.poll() is None:
                if sys.platform == "win32":
                    subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True,
                                   creationflags=subprocess.CREATE_NO_WINDOW)
                else:
                    proc.kill()
        except Exception:
            pass

    def pause(self):
        if self.pause_target and self.paused_at is None:
            self.pause_target.pause()
            self.paused_at = time.monotonic()

    def resume(self):
        if self.pause_target and self.paused_at is not None:
            self.pause_target.resume()
            self.paused_total += time.monotonic() - self.paused_at
            self.paused_at = None
            self.last_change = time.monotonic()

    @property
    def paused(self):
        return self.paused_at is not None


class JobQueue(QObject):
    """One job runs at a time; the rest wait in order. Stop ends the current job and empties the queue."""
    changed = Signal()

    def __init__(self, log, on_main):
        super().__init__()
        self.log = log
        self.on_main = on_main
        self.current = None
        self.waiting = []
        self.last = None

    def busy(self):
        return self.current is not None

    def add(self, job):
        if self.current is None:
            self._start(job)
        else:
            self.waiting.append(job)
            self.log(f"Added to the queue: {job.title} ({len(self.waiting)} waiting).")
        self.changed.emit()
        return job

    def stop(self):
        dropped = len(self.waiting)
        self.waiting.clear()
        if dropped:
            self.log(f"Removed {dropped} job(s) from the queue.")
        if self.current is not None:
            self.log(f"Stopping {self.current.title}…")
            self.current.stop()
        self.changed.emit()

    def _start(self, job):
        try:  # players and previews let go of their files, so moves and recycles aren't refused as "in use"
            import preview
            preview.release_all()
        except Exception:
            pass
        self.current = job
        job.started = time.monotonic()
        job.last_change = job.started
        if job.own_log:
            job.job_log = logs.JobLog(job.title)
            self.log(f"{job.title}: this job's full log is {job.job_log.path}")
        threading.Thread(target=self._run, args=(job,), daemon=True).start()

    def _run(self, job):
        _local.job = job

        def log(line):
            self.log(line)
            if job.job_log:
                job.job_log.write(line)

        log(f"Started: {job.title}")
        try:
            result = job.fn(*job.args, log=log, progress=job.progress, **job.kwargs)
            job.result = result
            if isinstance(result, dict):
                job.summary = result.get("summary", "")
                job.next_step = result.get("next")
            elif isinstance(result, str):
                job.summary = result
            job.finished = "stopped" if job.stop_requested else "done"
        except JobStopped:
            job.finished = "stopped"
        except Exception as exc:  # report errors in the log instead of crashing
            job.finished = "failed"
            job.error = exc
            if job.stop_requested:
                job.finished = "stopped"
            else:
                log(f"ERROR: {job.title} failed: {exc}")
                if job.job_log:
                    import traceback
                    job.job_log.write(traceback.format_exc())
        finally:
            job.ended = time.monotonic()
            _local.job = None
            took = fileops.clock(job.elapsed())
            if job.finished == "done":
                log(f"Finished: {job.title}{' · ' + job.summary if job.summary else ''} · took {took}")
            elif job.finished == "stopped":
                log(f"Stopped: {job.title} after {took}. Work finished before stopping is kept.")
            self.on_main(lambda: self._finished(job))

    def _finished(self, job):
        self.last = job
        self.current = None
        callback = job.on_done if job.finished in ("done", "stopped") else job.on_failed
        if callback:
            try:
                callback(job)
            except Exception as exc:
                self.log(f"ERROR: after {job.title}: {exc}")
        if self.waiting:
            self._start(self.waiting.pop(0))
        self.changed.emit()
