"""GIF maker page: pick videos, optionally set a timeframe for each one, then convert them."""
import threading
import tkinter as tk
from pathlib import Path
from tkinter import messagebox

import customtkinter as ctk
from PIL import Image

import gif_maker
import icons
import theme
from media_utils import find_videos, probe_duration
from theme import button, card, entry, label, muted
from widgets import Page, tree_in_card

MIN_CLIP = 0.1  # shortest allowed timeframe, in seconds


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
    """A bar showing the whole video, with the GIF's start and end handles on it. Stretches to the window width."""
    PAD = 16

    def __init__(self, master, on_drag, on_release):
        super().__init__(master, height=72, background=theme.FIELD, highlightthickness=0)
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
        top, bottom = 16, h - 18
        self.create_rectangle(self.PAD, top, w - self.PAD, bottom, fill=theme.TRACK, outline="")
        xs, xe = self._x(self.start), self._x(self.end)
        self.create_rectangle(xs, top, xe, bottom, fill=theme.GREEN, outline="")
        for x in (xs, xe):
            self.create_line(x, top - 6, x, bottom + 6, fill="#ffffff", width=3)
        self.create_text(self.PAD, h - 2, text="0:00.0", anchor="sw", fill=theme.MUTED, font=(theme.FAMILY, 10))
        self.create_text(w - self.PAD, h - 2, text=fmt_time(self.duration), anchor="se",
                         fill=theme.MUTED, font=(theme.FAMILY, 10))

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


class GifTab(Page):
    title = "GIF maker"
    subtitle = "Turn videos into GIFs. Pick a timeframe for any video, or leave it to convert the whole thing."

    def build(self):
        self.folder = tk.StringVar()
        self.recursive = tk.IntVar(value=1)
        self.fps = tk.StringVar(value="12")
        self.width = tk.StringVar(value="480")
        self.quality = tk.StringVar(value="Standard")
        self.out_dir = tk.StringVar()
        self.start_text = tk.StringVar()
        self.end_text = tk.StringVar()
        self.durations = {}  # video path (str) -> seconds
        self.ranges = {}     # video path (str) -> (start, end), only once a timeframe is set
        self.current = None  # path shown in the timeframe editor
        self._preview_after = None
        self._preview_id = 0
        self._refit_after = None
        self._frames = {"start": None, "end": None}  # full-size preview frames (PIL)
        self._images = []    # keep references so the preview images aren't dropped
        self._blank = ctk.CTkImage(light_image=Image.new("RGBA", (1, 1), (0, 0, 0, 0)),
                                   dark_image=Image.new("RGBA", (1, 1), (0, 0, 0, 0)), size=(1, 1))
        self.body.grid_rowconfigure(2, weight=1)
        self.scroll.add_resize_callback(self._refit_previews)

        # Source and output settings
        setup = card(self.body)
        setup.grid(row=0, column=0, sticky="ew")
        setup.grid_columnconfigure(1, weight=1)
        self.folder_row(setup, 0, "Video folder", self.folder, "Choose the video folder")

        load = ctk.CTkFrame(setup, fg_color="transparent")
        load.grid(row=1, column=0, columnspan=3, sticky="w", padx=18, pady=(0, 8))
        theme.switch(load, "Include subfolders", self.recursive).pack(side="left", padx=(0, 26))
        button(load, "Load videos", self.load_videos, "primary", icon=icons.icon("gif", "#ffffff", 18)).pack(side="left")

        settings = ctk.CTkFrame(setup, fg_color="transparent")
        settings.grid(row=2, column=0, columnspan=3, sticky="w", padx=18, pady=(4, 8))
        muted(settings, "FPS").pack(side="left")
        entry(settings, self.fps, width=72).pack(side="left", padx=(8, 20))
        muted(settings, "Width (px)").pack(side="left")
        entry(settings, self.width, width=84).pack(side="left", padx=(8, 20))
        muted(settings, "Quality").pack(side="left")
        ctk.CTkComboBox(settings, values=list(gif_maker.QUALITY_PRESETS), variable=self.quality,
                        state="readonly", width=160, height=40, corner_radius=8, font=theme.font(14),
                        fg_color=theme.FIELD, border_color=theme.CARD_BORDER, text_color=theme.TEXT,
                        button_color=theme.SECONDARY, button_hover_color=theme.SECONDARY_HOVER,
                        dropdown_fg_color=theme.CARD, dropdown_hover_color=theme.SECONDARY,
                        dropdown_text_color=theme.TEXT, dropdown_font=theme.font(14)).pack(side="left", padx=(8, 16))
        muted(settings, "Higher quality = better colours, bigger file, slower").pack(side="left")

        self.folder_row(setup, 3, "Save GIFs to", self.out_dir, "Save GIFs to...")
        muted(setup, "Leave the output folder empty to save each GIF beside its video.").grid(
            row=4, column=1, sticky="w", padx=6, pady=(0, 14))

        # Actions
        actions = ctk.CTkFrame(self.body, fg_color="transparent")
        actions.grid(row=1, column=0, sticky="ew", pady=12)
        button(actions, "Select all", self.select_all).pack(side="left")
        button(actions, "Clear timeframes", self.clear_selected_ranges).pack(side="left", padx=8)
        button(actions, "Convert selected", lambda: self.convert(selected_only=True), "primary",
               icon=icons.icon("gif", "#ffffff", 18)).pack(side="left")
        button(actions, "Convert all", lambda: self.convert(selected_only=False), "primary").pack(side="left", padx=8)

        # Video list (grows with the window)
        list_card = card(self.body)
        list_card.grid(row=2, column=0, sticky="nsew", pady=(0, 12))
        self.tree = tree_in_card(list_card, ("file", "length", "range"),
                                 ("File", "Length", "Timeframe"), (560, 110, 220))
        self.tree.bind("<<TreeviewSelect>>", self._on_select)

        # Timeframe editor
        editor = card(self.body)
        editor.grid(row=3, column=0, sticky="ew", pady=(0, 8))
        head = ctk.CTkFrame(editor, fg_color="transparent")
        head.pack(fill="x", padx=18, pady=(14, 8))
        label(head, "Timeframe", size=16, weight="bold").pack(side="left")
        muted(head, "   Click a video in the list to set its clip (drag the handles or type times)").pack(side="left")

        self.timeline = Timeline(editor, on_drag=self._on_drag, on_release=self._on_release)
        self.timeline.pack(fill="x", padx=18, pady=(0, 12))

        controls = ctk.CTkFrame(editor, fg_color="transparent")
        controls.pack(fill="x", padx=18)
        muted(controls, "Start").pack(side="left")
        start_entry = entry(controls, self.start_text, width=110)
        start_entry.pack(side="left", padx=(8, 16))
        start_entry.bind("<Return>", lambda _e: self._apply_entries())
        muted(controls, "End").pack(side="left")
        end_entry = entry(controls, self.end_text, width=110)
        end_entry.pack(side="left", padx=(8, 16))
        end_entry.bind("<Return>", lambda _e: self._apply_entries())
        button(controls, "Apply", self._apply_entries).pack(side="left")
        button(controls, "Whole video", self._reset_range).pack(side="left", padx=8)
        self.length_label = label(controls, "", weight="bold")
        self.length_label.pack(side="left", padx=12)

        previews = ctk.CTkFrame(editor, fg_color="transparent")
        previews.pack(fill="x", padx=18, pady=(14, 18))
        previews.grid_columnconfigure((0, 1), weight=1, uniform="preview")
        self.start_preview = self._preview_box(previews, 0, "Clip starts at")
        self.end_preview = self._preview_box(previews, 1, "Clip ends at")

    def _preview_box(self, parent, col, caption):
        box = ctk.CTkFrame(parent, fg_color=theme.FIELD, corner_radius=12)
        box.grid(row=0, column=col, sticky="nsew", padx=(0, 8) if col == 0 else (8, 0))
        muted(box, caption).pack(anchor="w", padx=14, pady=(10, 6))
        view = ctk.CTkLabel(box, text="No video selected", height=190, font=theme.font(14),
                            text_color=theme.MUTED)
        view.pack(fill="both", expand=True, padx=14, pady=(0, 14))
        return view

    # ---------- loading ----------
    def load_videos(self):
        folder = self.folder.get().strip()
        if not Path(folder).is_dir():
            messagebox.showerror("Folder not found", "Choose a valid video folder.")
            return
        videos = find_videos(folder, bool(self.recursive.get()))
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
        self.length_label.configure(text="")
        self._frames = {"start": None, "end": None}
        self._reset_preview(self.start_preview)
        self._reset_preview(self.end_preview)

    def _reset_preview(self, view):
        view.configure(image=self._blank, text="No video selected")

    def _update_labels(self, start, end):
        self.start_text.set(fmt_time(start))
        self.end_text.set(fmt_time(end))
        self.length_label.configure(text=f"Length: {end - start:.1f}s")

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
        self._frames = {"start": first, "end": last}
        for view, img in ((self.start_preview, first), (self.end_preview, last)):
            if img is None:
                view.configure(image=self._blank, text="Could not read this frame")
        self._render_previews()

    def _refit_previews(self):
        """Called when the window is resized, so the preview images fill their boxes again."""
        if self._refit_after:
            self.after_cancel(self._refit_after)
        self._refit_after = self.after(120, self._render_previews)

    def _render_previews(self):
        self._refit_after = None
        for view, key in ((self.start_preview, "start"), (self.end_preview, "end")):
            img = self._frames.get(key)
            if img is None:
                continue
            box_w = max(60, view.winfo_width() - 16)
            box_h = max(60, view.winfo_height() - 16)
            scale = min(box_w / img.width, box_h / img.height)
            size = (max(1, int(img.width * scale)), max(1, int(img.height * scale)))
            resized = img.resize(size, Image.LANCZOS)
            photo = ctk.CTkImage(light_image=resized, dark_image=resized, size=size)
            self._images.append(photo)
            self._images = self._images[-6:]
            view.configure(image=photo, text="")

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
        self.app.run_background(gif_maker.convert_batch, jobs, fps, width, self.quality.get(), out_dir)
