"""Media Toolbox: a sidebar app with one page per tool."""
import queue
import threading
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox
from tkinter import font as tkfont

import customtkinter as ctk

import folder_tools
import icons
import settings
import silent_videos
import theme
import webp_convert
from gif_tab import GifTab
from theme import button, card, muted
from themes import (CORNER_STYLES, DEFAULT_THEME, ELEMENT_SIZES, FONT_CHOICES, PALETTES, TEXT_SIZES)
from widgets import Page, tree_in_card


def fmt_size(n):
    if n < 1024:
        return f"{n} B"
    if n < 1024 ** 2:
        return f"{n / 1024:.0f} KB"
    return f"{n / 1024 ** 2:.1f} MB"


def _nearest(mapping, value):
    """The label in mapping whose number is closest to value."""
    return min(mapping, key=lambda k: abs(mapping[k] - value))


class SilentPage(Page):
    title = "Silent videos"
    subtitle = "Find videos with no audio, select the ones you want, then move them to another folder."

    def build(self):
        self.folder = tk.StringVar()
        self.recursive = tk.IntVar(value=1)
        self.loud = tk.IntVar(value=0)
        self.threshold = tk.StringVar(value="-60")
        self.body.grid_rowconfigure(2, weight=1)

        setup = card(self.body)
        setup.grid(row=0, column=0, sticky="ew")
        setup.grid_columnconfigure(1, weight=1)
        self.folder_row(setup, 0, "Video folder", self.folder, "Choose the video folder")
        opts = ctk.CTkFrame(setup, fg_color="transparent")
        opts.grid(row=1, column=0, columnspan=3, sticky="w", padx=18, pady=(0, 16))
        theme.switch(opts, "Include subfolders", self.recursive).pack(side="left", padx=(0, 26))
        theme.switch(opts, "Also check audio level (slower)", self.loud).pack(side="left", padx=(0, 26))
        muted(opts, "Threshold (dB)").pack(side="left", padx=(0, 8))
        theme.entry(opts, self.threshold, width=90).pack(side="left")

        actions = ctk.CTkFrame(self.body, fg_color="transparent")
        actions.grid(row=1, column=0, sticky="ew", pady=12)
        button(actions, "Scan", self.scan, "primary", icon=icons.icon("search", "#ffffff", 18)).pack(side="left")
        button(actions, "Select all", self.select_all).pack(side="left", padx=8)
        button(actions, "Move selected", self.move_selected, "primary",
               icon=icons.icon("move", "#ffffff", 18)).pack(side="left")
        self.summary = muted(actions, "", size=14)
        self.summary.pack(side="left", padx=16)

        list_card = card(self.body)
        list_card.grid(row=2, column=0, sticky="nsew", pady=(0, 8))
        self.tree = tree_in_card(list_card, ("path", "reason"), ("File", "Reason"), (640, 300))

    def scan(self):
        folder = self.folder.get().strip()
        if not Path(folder).is_dir():
            messagebox.showerror("Folder not found", "Choose a valid video folder.")
            return
        try:
            threshold = float(self.threshold.get())
        except ValueError:
            messagebox.showerror("Invalid threshold", "Enter a number such as -60.")
            return
        self.app.run_background(self._scan_worker, folder, bool(self.recursive.get()),
                                bool(self.loud.get()), threshold)

    def _scan_worker(self, folder, recursive, loud, threshold, log, progress):
        silent = silent_videos.scan_folder(folder, recursive, loud, threshold, log=log, progress=progress)
        self.app.on_main(lambda: self._show_results(silent))

    def _show_results(self, silent):
        self.tree.delete(*self.tree.get_children())
        for path, reason in silent:
            self.tree.insert("", "end", iid=str(path), values=(str(path), reason))
        self.summary.configure(text=f"{len(silent)} silent video(s). Select the ones to move.")

    def select_all(self):
        self.tree.selection_set(self.tree.get_children())

    def move_selected(self):
        iids = self.tree.selection()
        if not iids:
            messagebox.showinfo("Nothing selected", "Select one or more videos in the list first (or click Select all).")
            return
        dest = filedialog.askdirectory(title="Move selected videos to...")
        if not dest:
            return
        self.app.run_background(self._move_worker, [Path(i) for i in iids], dest)

    def _move_worker(self, paths, dest, log, progress):
        moved = silent_videos.move_files(paths, dest, log=log, progress=progress)
        moved_ids = [str(p) for p in moved]
        self.app.on_main(lambda: self._remove_rows(moved_ids))

    def _remove_rows(self, iids):
        for iid in iids:
            if self.tree.exists(iid):
                self.tree.delete(iid)
        self.summary.configure(text=f"{len(self.tree.get_children())} silent video(s) remaining")


class ZipPage(Page):
    title = "Zip subfolders"
    subtitle = "Each subfolder becomes its own zip file, named after the folder."

    def build(self):
        self.source = tk.StringVar()
        self.dest = tk.StringVar()
        setup = card(self.body)
        setup.grid(row=0, column=0, sticky="ew")
        setup.grid_columnconfigure(1, weight=1)
        self.folder_row(setup, 0, "Parent folder", self.source, "Choose the parent folder")
        self.folder_row(setup, 1, "Save zips to", self.dest, "Choose where to save the zips")
        muted(setup, "Leave the destination empty to save the zips beside the folders.").grid(
            row=2, column=1, sticky="w", padx=6, pady=(0, 16))

        actions = ctk.CTkFrame(self.body, fg_color="transparent")
        actions.grid(row=1, column=0, sticky="w", pady=12)
        button(actions, "Zip subfolders", self.run, "primary", icon=icons.icon("zip", "#ffffff", 18)).pack(side="left")

    def run(self):
        src = self.source.get().strip()
        dst = self.dest.get().strip() or None
        if not Path(src).is_dir():
            messagebox.showerror("Folder not found", "Choose a valid parent folder.")
            return
        self.app.run_background(folder_tools.zip_subfolders, src, dst)


class WebpPage(Page):
    title = "WebP to JPG"
    subtitle = "Pick a folder to see its WebP images before converting. Each JPG is saved beside its original."
    QUALITY_STEPS = [100, 95, 90, 85, 80, 75, 70, 60, 50]
    QUALITY_INFO = {
        100: "Maximum. No visible change from the original, but the largest files. Only worth it for archiving or heavy editing.",
        95: "Near-perfect, and very hard to tell from the original. This was the app's setting until now.",
        90: "Excellent. Looks the same to almost everyone, with noticeably smaller files. A good everyday choice.",
        85: "Very good. A slight loss in fine detail and smooth gradients. Fine for photos and art shared online.",
        80: "Good. Files are much smaller, and fine textures can soften when zoomed in.",
        75: "Fair. Good where file size matters. Faint blocky edges can show around sharp lines.",
        70: "Visible artefacts around text and sharp edges. Use when size matters most.",
        60: "Low. Blocky patterns in flat colours and gradients are common.",
        50: "Lowest. Clearly degraded. Only suitable for thumbnails or previews.",
    }

    def build(self):
        self.folder = tk.StringVar()
        self.recursive = tk.IntVar(value=0)
        self.delete_originals = tk.IntVar(value=0)
        self.quality = tk.StringVar(value="95%")
        self.rows = []  # (Path, folder shown in the list, size in bytes)
        self.body.grid_rowconfigure(2, weight=1)

        setup = card(self.body)
        setup.grid(row=0, column=0, sticky="ew")
        setup.grid_columnconfigure(1, weight=1)
        self.folder_row(setup, 0, "Folder", self.folder, "Choose the folder", on_change=self.scan)
        opts = ctk.CTkFrame(setup, fg_color="transparent")
        opts.grid(row=1, column=0, columnspan=3, sticky="w", padx=18, pady=(0, 16))
        theme.switch(opts, "Include subfolders", self.recursive, command=self.scan).pack(side="left", padx=(0, 26))
        theme.switch(opts, "Send originals to the Recycle Bin after converting",
                     self.delete_originals).pack(side="left")

        quality_card = card(self.body)
        quality_card.grid(row=1, column=0, sticky="ew", pady=(12, 0))
        top = ctk.CTkFrame(quality_card, fg_color="transparent")
        top.pack(fill="x", padx=18, pady=(14, 4))
        theme.label(top, "JPG quality", size=16, weight="bold").pack(side="left")
        values = [f"{q}%" for q in self.QUALITY_STEPS]
        theme.combo(top, values, self.quality, width=130, command=self._quality_changed).pack(side="left", padx=14)
        muted(top, "Higher = bigger file, better detail").pack(side="left")
        self.quality_info = muted(quality_card, self.QUALITY_INFO[95], size=14, wraplength=theme.px(820),
                                  justify="left")
        self.quality_info.pack(anchor="w", padx=18, pady=(0, 6))
        muted(quality_card, "JPG can't store transparency, so transparent areas become white. "
                            "Animated WebP files convert only their first frame. Metadata is not kept.",
              size=12, wraplength=theme.px(820), justify="left").pack(anchor="w", padx=18, pady=(0, 14))

        list_card = card(self.body)
        list_card.grid(row=2, column=0, sticky="nsew", pady=(12, 8))
        self.tree = tree_in_card(list_card, ("file", "folder", "size"),
                                 ("File", "Folder", "Size"), (300, 440, 110))

        actions = ctk.CTkFrame(self.body, fg_color="transparent")
        actions.grid(row=3, column=0, sticky="ew", pady=(4, 8))
        button(actions, "Scan folder", self.scan).pack(side="left")
        button(actions, "Convert all listed", lambda: self.convert(selected_only=False), "primary",
               icon=icons.icon("image", "#ffffff", 18)).pack(side="left", padx=8)
        button(actions, "Convert selected", lambda: self.convert(selected_only=True), "primary").pack(side="left")
        self.summary = muted(actions, "Choose a folder to see its WebP files.", size=14)
        self.summary.pack(side="left", padx=16)

    def _quality_changed(self, choice):
        self.quality_info.configure(text=self.QUALITY_INFO[int(choice.rstrip("%"))])

    def scan(self):
        folder = self.folder.get().strip()
        if not Path(folder).is_dir():
            self._show([])
            self.summary.configure(text="Choose a folder to see its WebP files.")
            return
        recursive = bool(self.recursive.get())
        self.summary.configure(text="Scanning...")
        root = Path(folder)

        def worker():
            rows = []
            for p in webp_convert.find_webp(root, recursive):
                try:
                    size = p.stat().st_size
                except OSError:
                    size = 0
                rel = p.parent.relative_to(root)
                where = "(top folder)" if str(rel) == "." else str(rel)
                rows.append((p, where, size))
            self.app.on_main(lambda: self._show(rows))
            self.app.log(f"Scan finished: {len(rows)} WebP file(s) in {folder}")

        threading.Thread(target=worker, daemon=True).start()

    def _show(self, rows):
        self.rows = rows
        self.tree.delete(*self.tree.get_children())
        for p, where, size in rows:
            self.tree.insert("", "end", iid=str(p), values=(p.name, where, fmt_size(size)))
        if not rows:
            self.summary.configure(text="No WebP files found in this folder.")
            return
        total = sum(size for _, _, size in rows)
        folders = len({where for _, where, _ in rows})
        self.summary.configure(text=f"{len(rows)} WebP file(s) in {folders} folder(s), {fmt_size(total)} in total")

    def convert(self, selected_only):
        if not self.rows:
            messagebox.showinfo("No files", "Choose a folder with WebP files first.")
            return
        if selected_only:
            iids = self.tree.selection()
            if not iids:
                messagebox.showinfo("Nothing selected", "Select one or more files in the list first.")
                return
            paths = [Path(i) for i in iids]
        else:
            paths = [p for p, _, _ in self.rows]
        quality = int(self.quality.get().rstrip("%"))
        delete = bool(self.delete_originals.get())
        if delete and not messagebox.askyesno(
                "Confirm", f"The original .webp files of the {len(paths)} selected file(s) will be sent to the "
                           "Recycle Bin after converting. Continue?"):
            return
        self.app.run_background(webp_convert.convert_files, paths, quality, delete)


class CopyPage(Page):
    title = "Copy folder structure"
    subtitle = "Recreate a folder's sub-folders in another location, without copying any files."

    def build(self):
        self.source = tk.StringVar()
        self.dest = tk.StringVar()
        setup = card(self.body)
        setup.grid(row=0, column=0, sticky="ew")
        setup.grid_columnconfigure(1, weight=1)
        self.folder_row(setup, 0, "Folder to copy", self.source, "Choose the folder to copy")
        self.folder_row(setup, 1, "Copy into", self.dest, "Choose the destination")
        muted(setup, "Creates a copy of the folder tree (no files) inside the destination.").grid(
            row=2, column=1, sticky="w", padx=6, pady=(0, 16))

        actions = ctk.CTkFrame(self.body, fg_color="transparent")
        actions.grid(row=1, column=0, sticky="w", pady=12)
        button(actions, "Copy folder structure", self.run, "primary",
               icon=icons.icon("copy_folder", "#ffffff", 18)).pack(side="left")

    def run(self):
        src = self.source.get().strip()
        dst = self.dest.get().strip()
        if not Path(src).is_dir() or not dst:
            messagebox.showerror("Missing input", "Choose a source folder and a destination.")
            return
        self.app.run_background(folder_tools.copy_folder_structure, src, dst)


class AppearancePage(Page):
    title = "Appearance"
    subtitle = "Choose a theme, font, text size, element size and corner style. Changes apply straight away and are remembered."

    def build(self):
        self.body.grid_columnconfigure(0, weight=1)

        # Themes
        themes_card = card(self.body)
        themes_card.grid(row=0, column=0, sticky="ew")
        theme.label(themes_card, "Theme", size=17, weight="bold").pack(anchor="w", padx=20, pady=(16, 2))
        muted(themes_card, "Based on the designs you shared. Click a theme to use it.").pack(anchor="w", padx=20)
        grid = ctk.CTkFrame(themes_card, fg_color="transparent")
        grid.pack(fill="x", padx=12, pady=12)
        for c in range(4):
            grid.grid_columnconfigure(c, weight=1, uniform="theme")
        for i, name in enumerate(PALETTES):
            self._theme_tile(grid, name, i // 4, i % 4)

        # Font
        font_card = card(self.body)
        font_card.grid(row=1, column=0, sticky="ew", pady=(12, 0))
        row = ctk.CTkFrame(font_card, fg_color="transparent")
        row.pack(fill="x", padx=20, pady=(16, 4))
        theme.label(row, "Font", size=17, weight="bold").pack(side="left")
        installed = theme.installed_families(self)
        choices = [f for f in FONT_CHOICES if f in installed] or [theme.FAMILY]
        self.font_var = tk.StringVar(value=theme.FAMILY if theme.FAMILY in choices else choices[0])
        theme.combo(row, choices, self.font_var, width=240, command=lambda c: self.app.change_appearance(font=c)).pack(
            side="left", padx=16)
        muted(row, "Only fonts installed on this PC are listed.").pack(side="left")
        self.sample = ctk.CTkLabel(font_card, text="The quick brown fox jumps over the lazy dog. 0123456789",
                                   font=ctk.CTkFont(family=theme.FAMILY, size=theme._text_px(20)),
                                   text_color=theme.TEXT)
        self.sample.pack(anchor="w", padx=20, pady=(6, 18))

        # Sizes and shape
        size_card = card(self.body)
        size_card.grid(row=2, column=0, sticky="ew", pady=(12, 12))
        size_card.grid_columnconfigure(1, weight=1)
        self._option_row(size_card, 0, "Text size", TEXT_SIZES, theme.TEXT_SCALE, "text_scale",
                         "Changes the size of the words only.")
        self._option_row(size_card, 1, "Element size", ELEMENT_SIZES, theme.UI_SCALE, "ui_scale",
                         "Changes the size of buttons, boxes, switches and tables.")
        self._option_row(size_card, 2, "Corner style", CORNER_STYLES, theme.RADIUS_SCALE, "radius_scale",
                         "How rounded the cards, buttons and boxes are.")

        button(self.body, "Reset to default", self._reset, "secondary", width=190).grid(
            row=3, column=0, sticky="w", pady=(0, 8))

    def _option_row(self, parent, row, title, mapping, current, key, hint):
        theme.label(parent, title, size=16, weight="bold").grid(row=row, column=0, sticky="w", padx=(20, 14), pady=12)
        var = tk.StringVar(value=_nearest(mapping, current))
        theme.combo(parent, list(mapping), var, width=200,
                    command=lambda choice, k=key, m=mapping: self.app.change_appearance(**{k: m[choice]})
                    ).grid(row=row, column=1, sticky="w", padx=6, pady=12)
        muted(parent, hint).grid(row=row, column=2, sticky="w", padx=(14, 20), pady=12)

    def _theme_tile(self, parent, name, row, col):
        p = PALETTES[name]
        selected = name == theme.CURRENT_THEME
        tile = ctk.CTkFrame(parent, fg_color=p["APP_BG"], corner_radius=theme.radius(14),
                            border_width=3 if selected else 1,
                            border_color=p["GREEN"] if selected else theme.CARD_BORDER)
        tile.grid(row=row, column=col, sticky="nsew", padx=8, pady=8)

        preview = ctk.CTkFrame(tile, fg_color=p["SIDEBAR"], corner_radius=theme.radius(10))
        preview.pack(fill="x", padx=12, pady=(12, 6))
        strip = ctk.CTkFrame(preview, fg_color="transparent")
        strip.pack(fill="x", padx=10, pady=10)
        ctk.CTkFrame(strip, width=theme.px(60), height=theme.px(44), corner_radius=theme.radius(8),
                     fg_color=p["CARD"]).pack(side="left")
        ctk.CTkFrame(strip, width=theme.px(60), height=theme.px(44), corner_radius=theme.radius(8),
                     fg_color=p["TRACK"]).pack(side="left", padx=8)
        ctk.CTkFrame(strip, width=theme.px(60), height=theme.px(44), corner_radius=theme.radius(8),
                     fg_color=p["GREEN"]).pack(side="left")
        name_label = ctk.CTkLabel(tile, text=("✓ " if selected else "") + name, font=theme.font(15, "bold"),
                                  text_color=p["TEXT"])
        name_label.pack(anchor="w", padx=14, pady=(4, 12))

        def choose(_event=None, n=name):
            self.app.change_appearance(theme=n)

        def bind_all_children(widget):
            widget.bind("<Button-1>", choose)
            for child in widget.winfo_children():
                bind_all_children(child)

        bind_all_children(tile)

    def _reset(self):
        self.app.change_appearance(theme=DEFAULT_THEME, font="Inter", text_scale=1.0, ui_scale=1.0, radius_scale=1.0)


# Sidebar entries: key, label, icon name
NAV = [
    ("silent", "Silent videos", "silent"),
    ("gif", "GIF maker", "gif"),
    ("zip", "Zip subfolders", "zip"),
    ("webp", "WebP to JPG", "image"),
    ("copy", "Copy folder structure", "copy_folder"),
    ("appearance", "Appearance", "brush"),
]
PAGES = {
    "silent": SilentPage,
    "gif": GifTab,
    "zip": ZipPage,
    "webp": WebpPage,
    "copy": CopyPage,
    "appearance": AppearancePage,
}


class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        theme.setup(self)
        self.title("Media Toolbox")
        self.geometry("1280x880")
        self.minsize(1000, 680)
        self.ui_queue = queue.Queue()
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)
        self.nav = {}
        self.pages = {}
        self.current_key = "silent"

        self._build_sidebar()
        self._build_main()
        self.show("silent")
        self.after(80, self._drain)

    # ---------- layout ----------
    def _build_sidebar(self):
        side = ctk.CTkFrame(self, width=theme.px(260), corner_radius=0, fg_color=theme.SIDEBAR)
        side.grid(row=0, column=0, sticky="nsew")

        brand = ctk.CTkFrame(side, fg_color="transparent")
        brand.pack(fill="x", padx=20, pady=(24, 22))
        ctk.CTkLabel(brand, text="", image=icons.icon("logo", theme.GREEN, 34)).pack(side="left")
        names = ctk.CTkFrame(brand, fg_color="transparent")
        names.pack(side="left", padx=12)
        theme.label(names, "Media Toolbox", size=17, weight="bold").pack(anchor="w")
        muted(names, "Everyday file tools", size=12).pack(anchor="w")

        theme.label(side, "TOOLS", size=12, weight="bold", color=theme.MUTED).pack(anchor="w", padx=26, pady=(4, 8))
        for key, text, icon_name in NAV:
            btn = ctk.CTkButton(side, text=f"  {text}", anchor="w", height=theme.px(48),
                                corner_radius=theme.radius(10), fg_color="transparent",
                                hover_color=theme.NAV_HOVER, text_color=theme.MUTED,
                                font=theme.font(15, "bold"),
                                image=icons.icon(icon_name, theme.MUTED, 22), compound="left",
                                command=lambda k=key: self.show(k))
            btn.pack(fill="x", padx=14, pady=3)
            self.nav[key] = (btn, icon_name)

    def _build_main(self):
        main = ctk.CTkFrame(self, fg_color=theme.APP_BG, corner_radius=0)
        main.grid(row=0, column=1, sticky="nsew")
        main.grid_columnconfigure(0, weight=1)
        main.grid_rowconfigure(0, weight=3)   # the pages get most of the height
        main.grid_rowconfigure(1, weight=1)   # the activity panel grows too

        host = ctk.CTkFrame(main, fg_color="transparent")
        host.grid(row=0, column=0, sticky="nsew", padx=24, pady=(20, 10))
        host.grid_columnconfigure(0, weight=1)
        host.grid_rowconfigure(0, weight=1)
        for key, cls in PAGES.items():
            page = cls(host, self)
            page.grid(row=0, column=0, sticky="nsew")
            self.pages[key] = page

        self._build_activity(main)

    def _build_activity(self, main):
        panel = card(main)
        panel.grid(row=1, column=0, sticky="nsew", padx=24, pady=(0, 20))

        top = ctk.CTkFrame(panel, fg_color="transparent")
        top.pack(fill="x", padx=18, pady=(14, 8))
        self.status = theme.label(top, "Ready", size=14, weight="bold", width=theme.px(320), anchor="w")
        self.status.pack(side="left")
        button(top, "Clear log", self._clear_log, width=120).pack(side="right")
        self.bar = ctk.CTkProgressBar(top, height=theme.px(14), corner_radius=7, progress_color=theme.GREEN,
                                      fg_color=theme.TRACK)
        self.bar.set(0)
        self.bar.pack(side="left", fill="x", expand=True, padx=16)

        self.log_box = ctk.CTkTextbox(panel, height=theme.px(110), corner_radius=theme.radius(10),
                                      fg_color=theme.FIELD, text_color=theme.TEXT,
                                      font=(theme.MONO, theme._text_px(13)), wrap="word")
        self.log_box.pack(fill="both", expand=True, padx=18, pady=(0, 16))
        self.log_box.configure(state="disabled")

    def show(self, key):
        self.current_key = key
        self.pages[key].tkraise()
        for k, (btn, icon_name) in self.nav.items():
            active = k == key
            btn.configure(fg_color=theme.NAV_ACTIVE if active else "transparent",
                          text_color=theme.TEXT if active else theme.MUTED,
                          image=icons.icon(icon_name, theme.TEXT if active else theme.MUTED, 22))

    # ---------- appearance ----------
    def change_appearance(self, **changes):
        """Save a new appearance choice and rebuild the screen with it. Rebuilding is deferred, so it
        never happens inside the widget's own click handler."""
        current = {
            "theme": theme.CURRENT_THEME,
            "font": theme.WANTED_FAMILY,
            "text_scale": theme.TEXT_SCALE,
            "ui_scale": theme.UI_SCALE,
            "radius_scale": theme.RADIUS_SCALE,
        }
        current.update(changes)
        settings.save(current)
        apply_settings(current)
        self.after(30, self.rebuild)

    def rebuild(self):
        """Rebuild all the widgets so they pick up the new theme and sizes. The log and the current page are kept."""
        key = self.current_key
        log_text = self.log_box.get("1.0", "end-1c")
        status = self.status.cget("text")
        for child in self.winfo_children():
            child.destroy()
        self.nav = {}
        self.pages = {}
        theme.setup(self)
        self.configure(fg_color=theme.APP_BG)
        self._build_sidebar()
        self._build_main()
        self.log_box.configure(state="normal")
        self.log_box.insert("1.0", log_text)
        self.log_box.see("end")
        self.log_box.configure(state="disabled")
        self.status.configure(text=status)
        self.show(key)

    # ---------- thread-safe updates ----------
    # Background threads never touch the UI directly; they queue callables for the UI thread.
    def log(self, msg):
        stamp = datetime.now().strftime("%H:%M:%S")
        self.ui_queue.put(lambda: self._append_log(f"{stamp}  {msg}"))

    def on_main(self, fn):
        self.ui_queue.put(fn)

    def progress(self, done, total, text=""):
        """Show progress for the running job, e.g. progress(3, 10, "Converting")."""
        self.ui_queue.put(lambda: self._set_progress(done, total, text))

    def _set_progress(self, done, total, text):
        if total:
            pct = done * 100 / total
            self.bar.set(done / total)
            self.status.configure(text=f"{text}: {done} of {total}  ({pct:.0f}%)")
        else:
            self.bar.set(0)
            self.status.configure(text=text)

    def _append_log(self, line):
        self.log_box.configure(state="normal")
        self.log_box.insert("end", line + "\n")
        self.log_box.see("end")
        self.log_box.configure(state="disabled")

    def _clear_log(self):
        self.log_box.configure(state="normal")
        self.log_box.delete("1.0", "end")
        self.log_box.configure(state="disabled")

    def _drain(self):
        try:
            while True:
                fn = self.ui_queue.get_nowait()
                try:
                    fn()
                except Exception as exc:  # e.g. a page was rebuilt while a job was running
                    self._append_log(f"UI update skipped: {exc}")
        except queue.Empty:
            pass
        self.after(80, self._drain)

    def run_background(self, fn, *args, **kwargs):
        """Run fn in a thread. fn receives log= and progress= callbacks automatically."""
        def worker():
            self.progress(0, 0, "Starting...")
            self.log("Started.")
            try:
                fn(*args, log=self.log, progress=self.progress, **kwargs)
                self.progress(1, 1, "Finished")
                self.log("Finished.")
            except Exception as exc:  # report errors in the log instead of crashing
                self.progress(0, 0, "Failed, see log")
                self.log(f"ERROR: {exc}")
        threading.Thread(target=worker, daemon=True).start()


def apply_settings(saved):
    """Apply saved appearance choices to the theme module."""
    theme.use_theme(saved.get("theme", DEFAULT_THEME))
    theme.set_family(saved.get("font", theme.BUNDLED_FAMILY))
    theme.set_sizes(saved.get("text_scale", 1.0), saved.get("ui_scale", 1.0), saved.get("radius_scale", 1.0))


if __name__ == "__main__":
    theme.load_fonts()
    apply_settings(settings.load())
    App().mainloop()
