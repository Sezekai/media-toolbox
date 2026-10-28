"""GIF maker tab: pick videos, optionally set a timeframe for each one, then convert them."""
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from PIL import ImageTk

import gif_maker
from media_utils import find_videos, probe_duration

MIN_CLIP = 0.1  # shortest allowed timeframe, in seconds
PREVIEW_SIZE = (320, 180)


def fmt_time(seconds):
    minutes = int(seconds // 60)
    return f"{minutes}:{seconds - minutes * 60:04.1f}"


def parse_time(text):
    """Accepts seconds ("83.5") or m:ss.s ("1:23.5")."""
    text = text.strip()
    if ":" in text:
        minutes, seconds = text.split(":", 1)
        return float(minutes) * 60 + float(seconds)
    return float(text)


class Timeline(tk.Canvas):
    """A bar showing the whole video, with the GIF's start and end handles on it."""
    PAD = 14

    def __init__(self, master, on_drag, on_release):
        super().__init__(master, height=60, background="#1e1e1e", highlightthickness=0)
        self.on_drag = on_drag
        self.on_release = on_release
        self.duration = 0.0
        self.start = 0.0
        self.end = 0.0
        self._drag = None
        self.bind("<Configure>", lambda _e: self.redraw())
        self.bind("<ButtonPress-1>", self._press)
        self.bind("<B1-Motion>", self._motion)
        self.bind("<ButtonRelease-1>", self._release)

    def set_range(self, duration, start, end):
        self.duration, self.start, self.end = duration, start, end
        self.redraw()

    def _x(self, t):
        span = self.winfo_width() - 2 * self.PAD
        return self.PAD + (t / self.duration) * span if self.duration else self.PAD

    def _t(self, x):
        span = max(1, self.winfo_width() - 2 * self.PAD)
        return min(max((x - self.PAD) / span * self.duration, 0.0), self.duration)

    def redraw(self):
        self.delete("all")
        if not self.duration:
            return
        w, h = self.winfo_width(), self.winfo_height()
        top, bottom = 14, h - 14
        self.create_rectangle(self.PAD, top, w - self.PAD, bottom, fill="#3a3a3a", outline="")
        xs, xe = self._x(self.start), self._x(self.end)
        self.create_rectangle(xs, top, xe, bottom, fill="#3d7ac7", outline="")
        for x in (xs, xe):
            self.create_line(x, top - 6, x, bottom + 6, fill="white", width=3)
        self.create_text(self.PAD, h - 2, text="0:00.0", anchor="sw", fill="#aaaaaa", font=("Segoe UI", 8))
        self.create_text(w - self.PAD, h - 2, text=fmt_time(self.duration), anchor="se",
                         fill="#aaaaaa", font=("Segoe UI", 8))

    def _press(self, event):
        if not self.duration:
            return
        xs, xe = self._x(self.start), self._x(self.end)
        self._drag = "start" if abs(event.x - xs) <= abs(event.x - xe) else "end"
        self._motion(event)

    def _motion(self, event):
        if not self._drag:
            return
        t = self._t(event.x)
        if self._drag == "start":
            self.start = max(0.0, min(t, self.end - MIN_CLIP))
        else:
            self.end = min(self.duration, max(t, self.start + MIN_CLIP))
        self.redraw()
        self.on_drag(self.start, self.end)

    def _release(self, _event):
        if self._drag:
            self._drag = None
            self.on_release(self.start, self.end)


class GifTab(ttk.Frame):
    def __init__(self, master, app):
        super().__init__(master, padding=10)
        self.app = app
        self.folder = tk.StringVar()
        self.recursive = tk.BooleanVar(value=True)
        self.fps = tk.StringVar(value="12")
        self.width = tk.StringVar(value="480")
        self.out_dir = tk.StringVar()
        self.start_text = tk.StringVar()
        self.end_text = tk.StringVar()
        self.length_text = tk.StringVar()
        self.durations = {}  # video path (str) -> seconds
        self.ranges = {}     # video path (str) -> (start, end), only once a timeframe is set
        self.current = None  # path shown in the timeframe editor
        self._preview_after = None
        self._preview_id = 0
        self._photos = []    # keep references so Tk doesn't drop the images
        self.columnconfigure(1, weight=1)
        self.rowconfigure(3, weight=1)
        self._build()

    # ---------- layout ----------
    def _build(self):
        ttk.Label(self, text="Video folder:").grid(row=0, column=0, sticky="w", padx=6, pady=4)
        ttk.Entry(self, textvariable=self.folder).grid(row=0, column=1, sticky="ew", padx=6, pady=4)
        ttk.Button(self, text="Browse...", command=self._browse_folder).grid(row=0, column=2, padx=6, pady=4)

        top = ttk.Frame(self)
        top.grid(row=1, column=0, columnspan=3, sticky="w", padx=6, pady=2)
        ttk.Checkbutton(top, text="Include subfolders", variable=self.recursive).pack(side="left", padx=(0, 12))
        ttk.Button(top, text="Load videos", command=self.load_videos).pack(side="left")

        settings = ttk.Frame(self)
        settings.grid(row=2, column=0, columnspan=3, sticky="w", padx=6, pady=4)
        ttk.Label(settings, text="FPS").pack(side="left")
        ttk.Entry(settings, textvariable=self.fps, width=5).pack(side="left", padx=(4, 14))
        ttk.Label(settings, text="Width (px)").pack(side="left")
        ttk.Entry(settings, textvariable=self.width, width=6).pack(side="left", padx=(4, 14))
        ttk.Label(settings, text="Save to").pack(side="left")
        ttk.Entry(settings, textvariable=self.out_dir, width=36).pack(side="left", padx=4)
        ttk.Button(settings, text="Browse...", command=self._browse_out).pack(side="left")
        ttk.Label(settings, text="(blank = beside each video)").pack(side="left", padx=6)

        list_frame = ttk.Frame(self)
        list_frame.grid(row=3, column=0, columnspan=3, sticky="nsew", padx=6, pady=4)
        self.tree = ttk.Treeview(list_frame, columns=("file", "length", "range"),
                                 show="headings", selectmode="extended", height=8)
        for col, text, width in (("file", "File", 420), ("length", "Length", 80), ("range", "Timeframe", 200)):
            self.tree.heading(col, text=text)
            self.tree.column(col, width=width, stretch=(col == "file"))
        scroll = ttk.Scrollbar(list_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        self.tree.bind("<<TreeviewSelect>>", self._on_select)

        buttons = ttk.Frame(self)
        buttons.grid(row=4, column=0, columnspan=3, sticky="w", padx=6, pady=6)
        ttk.Button(buttons, text="Select all", command=self.select_all).pack(side="left")
        ttk.Button(buttons, text="Clear timeframes (selected)",
                   command=self.clear_selected_ranges).pack(side="left", padx=6)
        ttk.Button(buttons, text="Convert selected",
                   command=lambda: self.convert(selected_only=True)).pack(side="left", padx=6)
        ttk.Button(buttons, text="Convert all",
                   command=lambda: self.convert(selected_only=False)).pack(side="left")

        editor = ttk.LabelFrame(self, text="Timeframe (click a video in the list to set its clip)")
        editor.grid(row=5, column=0, columnspan=3, sticky="ew", padx=6, pady=(4, 0))
        self.timeline = Timeline(editor, on_drag=self._on_drag, on_release=self._on_release)
        self.timeline.pack(fill="x", padx=8, pady=(8, 4))

        controls = ttk.Frame(editor)
        controls.pack(fill="x", padx=8)
        ttk.Label(controls, text="Start").pack(side="left")
        start_entry = ttk.Entry(controls, textvariable=self.start_text, width=9)
        start_entry.pack(side="left", padx=(4, 12))
        start_entry.bind("<Return>", lambda _e: self._apply_entries())
        ttk.Label(controls, text="End").pack(side="left")
        end_entry = ttk.Entry(controls, textvariable=self.end_text, width=9)
        end_entry.pack(side="left", padx=(4, 12))
        end_entry.bind("<Return>", lambda _e: self._apply_entries())
        ttk.Button(controls, text="Apply", command=self._apply_entries).pack(side="left")
        ttk.Button(controls, text="Whole video", command=self._reset_range).pack(side="left", padx=8)
        ttk.Label(controls, textvariable=self.length_text).pack(side="left", padx=8)

        previews = ttk.Frame(editor)
        previews.pack(pady=8)
        self.start_preview = self._preview_box(previews, "Clip starts at")
        self.end_preview = self._preview_box(previews, "Clip ends at")

    def _preview_box(self, parent, caption):
        box = ttk.Frame(parent)
        box.pack(side="left", padx=12)
        ttk.Label(box, text=caption).pack()
        label = ttk.Label(box, text="(no video selected)", width=40, anchor="center")
        label.pack()
        return label

    # ---------- folders and loading ----------
    def _browse_folder(self):
        chosen = filedialog.askdirectory()
        if chosen:
            self.folder.set(chosen)

    def _browse_out(self):
        chosen = filedialog.askdirectory(title="Save GIFs to...")
        if chosen:
            self.out_dir.set(chosen)

    def load_videos(self):
        folder = self.folder.get().strip()
        if not Path(folder).is_dir():
            messagebox.showerror("Folder not found", "Choose a valid video folder.")
            return
        videos = find_videos(folder, self.recursive.get())
        self.tree.delete(*self.tree.get_children())
        self.durations.clear()
        self.ranges.clear()
        self.current = None
        for path in videos:
            self.tree.insert("", "end", iid=str(path),
                             values=(str(path.relative_to(folder)), "", "whole video"))
        self.app.log(f"Loaded {len(videos)} video(s).")
        self._clear_editor()

    def select_all(self):
        self.tree.selection_set(self.tree.get_children())

    # ---------- selecting a video and editing its timeframe ----------
    def _on_select(self, _event):
        iid = self.tree.focus()
        if not iid or iid == self.current:
            return
        self.current = iid
        self._ensure_duration(iid, lambda: self._show_editor(iid))

    def _ensure_duration(self, iid, then):
        if iid in self.durations:
            then()
            return

        def worker():
            seconds = probe_duration(iid)

            def done():
                if seconds is None:
                    self.app.log(f"Could not read the length of {Path(iid).name}")
                    return
                self.durations[iid] = seconds
                self.tree.set(iid, "length", fmt_time(seconds))
                then()
            self.app.on_main(done)

        threading.Thread(target=worker, daemon=True).start()

    def _show_editor(self, iid):
        if self.current != iid:  # the user has moved on to another video
            return
        duration = self.durations[iid]
        start, end = self.ranges.get(iid, (0.0, duration))
        self.timeline.set_range(duration, start, end)
        self._update_labels(start, end)
        self._request_previews()

    def _clear_editor(self):
        self.current = None
        self.timeline.set_range(0.0, 0.0, 0.0)
        self.start_text.set("")
        self.end_text.set("")
        self.length_text.set("")
        self.start_preview.configure(image="", text="(no video selected)")
        self.end_preview.configure(image="", text="(no video selected)")

    def _update_labels(self, start, end):
        self.start_text.set(fmt_time(start))
        self.end_text.set(fmt_time(end))
        self.length_text.set(f"Length: {end - start:.1f}s")

    def _store(self, start, end):
        """Remember the timeframe for the current video (or clear it if it covers the whole video)."""
        iid = self.current
        duration = self.durations[iid]
        if start <= 0.05 and end >= duration - 0.05:
            self.ranges.pop(iid, None)
            self.tree.set(iid, "range", "whole video")
        else:
            self.ranges[iid] = (start, end)
            self.tree.set(iid, "range", f"{fmt_time(start)} to {fmt_time(end)}")

    def _on_drag(self, start, end):
        self._update_labels(start, end)
        self._store(start, end)
        self._schedule_previews()

    def _on_release(self, start, end):
        self._store(start, end)
        self._request_previews()

    def _apply_entries(self):
        iid = self.current
        if not iid:
            return
        duration = self.durations[iid]
        try:
            start = parse_time(self.start_text.get())
            end = parse_time(self.end_text.get())
        except ValueError:
            messagebox.showerror("Invalid time", "Enter times like 12.5 or 1:23.5.")
            return
        start = max(0.0, min(start, duration))
        end = max(0.0, min(end, duration))
        if end - start < MIN_CLIP:
            messagebox.showerror("Invalid timeframe", f"The end must be at least {MIN_CLIP} s after the start.")
            return
        self.timeline.set_range(duration, start, end)
        self._update_labels(start, end)
        self._store(start, end)
        self._request_previews()

    def _reset_range(self):
        iid = self.current
        if not iid:
            return
        self.ranges.pop(iid, None)
        self.tree.set(iid, "range", "whole video")
        self._show_editor(iid)

    def clear_selected_ranges(self):
        for iid in self.tree.selection():
            self.ranges.pop(iid, None)
            self.tree.set(iid, "range", "whole video")
        if self.current in self.tree.selection():
            self._show_editor(self.current)

    # ---------- start and end frame previews ----------
    def _schedule_previews(self):
        if self._preview_after:
            self.after_cancel(self._preview_after)
        self._preview_after = self.after(250, self._request_previews)

    def _request_previews(self):
        self._preview_after = None
        iid = self.current
        if not iid:
            return
        start, end = self.timeline.start, self.timeline.end
        self._preview_id += 1
        token = self._preview_id

        def worker():
            first = gif_maker.extract_frame(iid, start)
            last = gif_maker.extract_frame(iid, max(end - 0.05, start))
            self.app.on_main(lambda: self._show_previews(token, first, last))

        threading.Thread(target=worker, daemon=True).start()

    def _show_previews(self, token, first, last):
        if token != self._preview_id:  # a newer preview has been requested since
            return
        for label, img in ((self.start_preview, first), (self.end_preview, last)):
            if img is None:
                label.configure(image="", text="(no frame)")
                continue
            img = img.copy()
            img.thumbnail(PREVIEW_SIZE)
            photo = ImageTk.PhotoImage(img)
            self._photos.append(photo)
            self._photos = self._photos[-4:]
            label.configure(image=photo, text="")

    # ---------- converting ----------
    def convert(self, selected_only):
        iids = self.tree.selection() if selected_only else self.tree.get_children()
        if not iids:
            messagebox.showinfo("Nothing selected", "Select one or more videos first, or use Convert all.")
            return
        try:
            fps = int(self.fps.get())
            width = int(self.width.get())
        except ValueError:
            messagebox.showerror("Invalid settings", "FPS and width must be whole numbers.")
            return
        if not (1 <= fps <= 60) or not (64 <= width <= 1920):
            messagebox.showerror("Invalid settings", "FPS must be 1 to 60, and width 64 to 1920 pixels.")
            return
        out_dir = self.out_dir.get().strip() or None
        jobs = []
        for iid in iids:
            if iid in self.ranges:
                start, end = self.ranges[iid]
                jobs.append((Path(iid), start, end))
            else:
                jobs.append((Path(iid), 0.0, None))
        self.app.run_background(gif_maker.convert_batch, jobs, fps, width, out_dir, log=self.app.log)
