"""Media Toolbox: a sidebar app with one page per tool."""
import queue
import threading
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import messagebox

import customtkinter as ctk

import folder_tools
import icons
import silent_videos
import theme
import webp_convert
from gif_tab import GifTab
from theme import button, card, muted
from widgets import Page, tree_in_card


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
        theme.entry(opts, self.threshold, width=84).pack(side="left")

        actions = ctk.CTkFrame(self.body, fg_color="transparent")
        actions.grid(row=1, column=0, sticky="ew", pady=12)
        button(actions, "Scan", self.scan, "primary", icon=icons.icon("search", "#ffffff", 18)).pack(side="left")
        button(actions, "Select all", self.select_all).pack(side="left", padx=8)
        button(actions, "Move selected", self.move_selected, "primary",
               icon=icons.icon("move", "#ffffff", 18)).pack(side="left")
        self.summary = muted(actions, "", size=13)
        self.summary.pack(side="left", padx=16)

        list_card = card(self.body)
        list_card.grid(row=2, column=0, sticky="nsew")
        self.tree = tree_in_card(list_card, ("path", "reason"), ("File", "Reason"), (560, 260))

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
        dest = _ask_dir("Move selected videos to...")
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
    subtitle = "Convert .webp images to .jpg. Each JPG is saved in the same folder as its original."

    def build(self):
        self.folder = tk.StringVar()
        self.recursive = tk.IntVar(value=0)
        self.delete_originals = tk.IntVar(value=0)
        setup = card(self.body)
        setup.grid(row=0, column=0, sticky="ew")
        setup.grid_columnconfigure(1, weight=1)
        self.folder_row(setup, 0, "Folder", self.folder, "Choose the folder")
        opts = ctk.CTkFrame(setup, fg_color="transparent")
        opts.grid(row=1, column=0, columnspan=3, sticky="w", padx=18, pady=(0, 16))
        theme.switch(opts, "Include subfolders", self.recursive).pack(side="left", padx=(0, 26))
        theme.switch(opts, "Send original .webp files to the Recycle Bin after converting",
                     self.delete_originals).pack(side="left")

        actions = ctk.CTkFrame(self.body, fg_color="transparent")
        actions.grid(row=1, column=0, sticky="w", pady=12)
        button(actions, "Convert to JPG", self.run, "primary", icon=icons.icon("image", "#ffffff", 18)).pack(side="left")

    def run(self):
        folder = self.folder.get().strip()
        if not Path(folder).is_dir():
            messagebox.showerror("Folder not found", "Choose a valid folder.")
            return
        delete = bool(self.delete_originals.get())
        if delete and not messagebox.askyesno(
                "Confirm", "Original .webp files will be sent to the Recycle Bin after converting. Continue?"):
            return
        self.app.run_background(webp_convert.convert_webp_to_jpg, folder, bool(self.recursive.get()), delete)


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


def _ask_dir(title):
    from tkinter import filedialog
    return filedialog.askdirectory(title=title)


# Sidebar entries: key, label, icon name
NAV = [
    ("silent", "Silent videos", "silent"),
    ("gif", "GIF maker", "gif"),
    ("zip", "Zip subfolders", "zip"),
    ("webp", "WebP to JPG", "image"),
    ("copy", "Copy folder structure", "copy_folder"),
]
PAGES = {
    "silent": SilentPage,
    "gif": GifTab,
    "zip": ZipPage,
    "webp": WebpPage,
    "copy": CopyPage,
}


class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        theme.setup(self)
        self.title("Media Toolbox")
        self.geometry("1180x900")
        self.minsize(1000, 760)
        self.ui_queue = queue.Queue()
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)
        self.nav = {}

        self._build_sidebar()
        self._build_main()
        self.show("silent")
        self.after(80, self._drain)

    # ---------- layout ----------
    def _build_sidebar(self):
        side = ctk.CTkFrame(self, width=236, corner_radius=0, fg_color=theme.SIDEBAR)
        side.grid(row=0, column=0, sticky="nsew")

        brand = ctk.CTkFrame(side, fg_color="transparent")
        brand.pack(fill="x", padx=18, pady=(22, 20))
        ctk.CTkLabel(brand, text="", image=icons.icon("logo", theme.GREEN, 30)).pack(side="left")
        names = ctk.CTkFrame(brand, fg_color="transparent")
        names.pack(side="left", padx=12)
        theme.label(names, "Media Toolbox", size=15, weight="bold").pack(anchor="w")
        muted(names, "Everyday file tools", size=11).pack(anchor="w")

        theme.label(side, "TOOLS", size=11, weight="bold", color=theme.MUTED).pack(anchor="w", padx=24, pady=(4, 8))
        for key, text, icon_name in NAV:
            btn = ctk.CTkButton(side, text=f"  {text}", anchor="w", height=42, corner_radius=10,
                                fg_color="transparent", hover_color=theme.NAV_HOVER,
                                text_color=theme.MUTED, font=theme.font(14, "bold"),
                                image=icons.icon(icon_name, theme.MUTED, 20), compound="left",
                                command=lambda k=key: self.show(k))
            btn.pack(fill="x", padx=12, pady=3)
            self.nav[key] = (btn, icon_name)

    def _build_main(self):
        main = ctk.CTkFrame(self, fg_color=theme.APP_BG, corner_radius=0)
        main.grid(row=0, column=1, sticky="nsew")
        main.grid_columnconfigure(0, weight=1)
        main.grid_rowconfigure(0, weight=1)

        host = ctk.CTkFrame(main, fg_color="transparent")
        host.grid(row=0, column=0, sticky="nsew", padx=24, pady=(20, 10))
        host.grid_columnconfigure(0, weight=1)
        host.grid_rowconfigure(0, weight=1)
        self.pages = {}
        for key, cls in PAGES.items():
            page = cls(host, self)
            page.grid(row=0, column=0, sticky="nsew")
            self.pages[key] = page

        self._build_activity(main)

    def _build_activity(self, main):
        panel = card(main)
        panel.grid(row=1, column=0, sticky="ew", padx=24, pady=(0, 20))

        top = ctk.CTkFrame(panel, fg_color="transparent")
        top.pack(fill="x", padx=18, pady=(14, 8))
        self.status = theme.label(top, "Ready", size=13, weight="bold", width=300, anchor="w")
        self.status.pack(side="left")
        button(top, "Clear log", self._clear_log, width=110).pack(side="right")
        self.bar = ctk.CTkProgressBar(top, height=12, corner_radius=6, progress_color=theme.GREEN,
                                      fg_color=theme.TRACK)
        self.bar.set(0)
        self.bar.pack(side="left", fill="x", expand=True, padx=16)

        self.log_box = ctk.CTkTextbox(panel, height=150, corner_radius=10, fg_color=theme.FIELD,
                                      text_color="#dcdce2", font=(theme.MONO, 12), wrap="word")
        self.log_box.pack(fill="x", padx=18, pady=(0, 16))
        self.log_box.configure(state="disabled")

    def show(self, key):
        self.pages[key].tkraise()
        for k, (btn, icon_name) in self.nav.items():
            active = k == key
            btn.configure(fg_color=theme.NAV_ACTIVE if active else "transparent",
                          text_color=theme.TEXT if active else theme.MUTED,
                          image=icons.icon(icon_name, theme.TEXT if active else theme.MUTED, 20))

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
                self.ui_queue.get_nowait()()
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


if __name__ == "__main__":
    App().mainloop()
