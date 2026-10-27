"""Media Toolbox: a GUI wrapper around small file utilities."""
import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

import folder_tools
import silent_videos
import webp_convert


def _browse(var):
    chosen = filedialog.askdirectory()
    if chosen:
        var.set(chosen)


def folder_row(parent, row, label, var):
    """A label, an entry and a Browse button on one grid row."""
    ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", padx=6, pady=4)
    ttk.Entry(parent, textvariable=var).grid(row=row, column=1, sticky="ew", padx=6, pady=4)
    ttk.Button(parent, text="Browse...", command=lambda: _browse(var)).grid(row=row, column=2, padx=6, pady=4)


class ToolTab(ttk.Frame):
    def __init__(self, master, app):
        super().__init__(master, padding=10)
        self.app = app
        self.columnconfigure(1, weight=1)


class VideoTab(ToolTab):
    def __init__(self, master, app):
        super().__init__(master, app)
        self.folder = tk.StringVar()
        self.recursive = tk.BooleanVar(value=True)
        self.check_loudness = tk.BooleanVar(value=False)
        self.threshold = tk.StringVar(value="-60")
        self.results = []  # Path objects currently listed

        folder_row(self, 0, "Video folder:", self.folder)

        opts = ttk.Frame(self)
        opts.grid(row=1, column=0, columnspan=3, sticky="w", padx=6, pady=4)
        ttk.Checkbutton(opts, text="Include subfolders", variable=self.recursive).pack(side="left", padx=(0, 12))
        ttk.Checkbutton(opts, text="Also detect silent audio (slower)",
                        variable=self.check_loudness).pack(side="left")
        ttk.Label(opts, text="Silence threshold (dB):").pack(side="left", padx=(12, 4))
        ttk.Entry(opts, textvariable=self.threshold, width=6).pack(side="left")

        buttons = ttk.Frame(self)
        buttons.grid(row=2, column=0, columnspan=3, sticky="w", padx=6, pady=6)
        ttk.Button(buttons, text="Scan", command=self.scan).pack(side="left")
        ttk.Button(buttons, text="Move all listed to folder...",
                   command=self.move_listed).pack(side="left", padx=8)
        self.summary = ttk.Label(buttons, text="")
        self.summary.pack(side="left", padx=8)

        self.tree = ttk.Treeview(self, columns=("path", "reason"), show="headings")
        self.tree.heading("path", text="File")
        self.tree.heading("reason", text="Reason")
        self.tree.column("path", width=520)
        self.tree.column("reason", width=240)
        self.tree.grid(row=3, column=0, columnspan=3, sticky="nsew", padx=6, pady=4)
        self.rowconfigure(3, weight=1)

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
        self.app.run_background(self._scan_worker, folder, self.recursive.get(),
                                self.check_loudness.get(), threshold)

    def _scan_worker(self, folder, recursive, check_loudness, threshold):
        silent = silent_videos.scan_folder(folder, recursive, check_loudness, threshold, log=self.app.log)
        self.app.on_main(lambda: self._show_results(silent))

    def _show_results(self, silent):
        self.results = [path for path, _ in silent]
        self.tree.delete(*self.tree.get_children())
        for path, reason in silent:
            self.tree.insert("", "end", iid=str(path), values=(str(path), reason))
        self.summary.config(text=f"{len(silent)} silent video(s)")

    def move_listed(self):
        if not self.results:
            messagebox.showinfo("Nothing to move", "Scan first, or no silent videos were found.")
            return
        dest = filedialog.askdirectory(title="Move silent videos to...")
        if not dest:
            return
        self.app.run_background(self._move_worker, list(self.results), dest)

    def _move_worker(self, paths, dest):
        moved = silent_videos.move_files(paths, dest, log=self.app.log)
        moved_ids = {str(p) for p in moved}
        self.app.on_main(lambda: self._remove_from_list(moved_ids))

    def _remove_from_list(self, moved_ids):
        self.results = [p for p in self.results if str(p) not in moved_ids]
        for iid in moved_ids:
            if self.tree.exists(iid):
                self.tree.delete(iid)
        self.summary.config(text=f"{len(self.results)} silent video(s)")


class ZipTab(ToolTab):
    def __init__(self, master, app):
        super().__init__(master, app)
        self.source = tk.StringVar()
        self.dest = tk.StringVar()
        folder_row(self, 0, "Parent folder:", self.source)
        folder_row(self, 1, "Save zips to (optional):", self.dest)
        ttk.Label(self, text="Each subfolder of the parent becomes FolderName.zip. "
                             "Leave the destination empty to save the zips beside the folders.").grid(
            row=2, column=0, columnspan=3, sticky="w", padx=6)
        ttk.Button(self, text="Zip subfolders", command=self.run).grid(
            row=3, column=0, sticky="w", padx=6, pady=8)

    def run(self):
        src = self.source.get().strip()
        dst = self.dest.get().strip() or None
        if not Path(src).is_dir():
            messagebox.showerror("Folder not found", "Choose a valid parent folder.")
            return
        self.app.run_background(folder_tools.zip_subfolders, src, dst, log=self.app.log)


class WebpTab(ToolTab):
    def __init__(self, master, app):
        super().__init__(master, app)
        self.folder = tk.StringVar()
        self.recursive = tk.BooleanVar(value=False)
        self.delete_originals = tk.BooleanVar(value=False)
        folder_row(self, 0, "Folder:", self.folder)

        opts = ttk.Frame(self)
        opts.grid(row=1, column=0, columnspan=3, sticky="w", padx=6, pady=4)
        ttk.Checkbutton(opts, text="Include subfolders",
                        variable=self.recursive).pack(side="left", padx=(0, 12))
        ttk.Checkbutton(opts, text="Send original .webp files to Recycle Bin after converting",
                        variable=self.delete_originals).pack(side="left")

        ttk.Label(self, text="Converted .jpg files are saved in the same directory as each original.").grid(
            row=2, column=0, columnspan=3, sticky="w", padx=6)
        ttk.Button(self, text="Convert to JPG", command=self.run).grid(
            row=3, column=0, sticky="w", padx=6, pady=8)

    def run(self):
        folder = self.folder.get().strip()
        if not Path(folder).is_dir():
            messagebox.showerror("Folder not found", "Choose a valid folder.")
            return
        delete = self.delete_originals.get()
        if delete and not messagebox.askyesno(
                "Confirm",
                "Original .webp files will be sent to the Recycle Bin after converting. Continue?"):
            return
        self.app.run_background(webp_convert.convert_webp_to_jpg, folder,
                                self.recursive.get(), delete, log=self.app.log)


class CopyTab(ToolTab):
    def __init__(self, master, app):
        super().__init__(master, app)
        self.source = tk.StringVar()
        self.dest = tk.StringVar()
        folder_row(self, 0, "Folder to copy:", self.source)
        folder_row(self, 1, "Copy into:", self.dest)
        ttk.Label(self, text="Recreates the folder tree (no files) inside the destination.").grid(
            row=2, column=0, columnspan=3, sticky="w", padx=6)
        ttk.Button(self, text="Copy folder structure", command=self.run).grid(
            row=3, column=0, sticky="w", padx=6, pady=8)

    def run(self):
        src = self.source.get().strip()
        dst = self.dest.get().strip()
        if not Path(src).is_dir() or not dst:
            messagebox.showerror("Missing input", "Choose a source folder and a destination.")
            return
        self.app.run_background(folder_tools.copy_folder_structure, src, dst, log=self.app.log)


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Media Toolbox")
        self.geometry("900x640")
        self.minsize(760, 520)
        self.ui_queue = queue.Queue()

        notebook = ttk.Notebook(self)
        notebook.pack(fill="both", expand=True, padx=8, pady=(8, 4))
        notebook.add(VideoTab(notebook, self), text="Silent videos")
        notebook.add(ZipTab(notebook, self), text="Zip subfolders")
        notebook.add(WebpTab(notebook, self), text="WebP to JPG")
        notebook.add(CopyTab(notebook, self), text="Copy folder structure")

        log_frame = ttk.LabelFrame(self, text="Log")
        log_frame.pack(fill="both", padx=8, pady=(0, 8))
        self.log_text = tk.Text(log_frame, height=10, state="disabled", wrap="word")
        self.log_text.pack(fill="both", expand=True, padx=4, pady=4)

        self.after(100, self._drain)

    # Background threads never touch Tk directly; they queue callables for the UI thread.
    def log(self, msg):
        self.ui_queue.put(lambda: self._append_log(msg))

    def on_main(self, fn):
        self.ui_queue.put(fn)

    def _append_log(self, msg):
        self.log_text.configure(state="normal")
        self.log_text.insert("end", msg + "\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def _drain(self):
        try:
            while True:
                self.ui_queue.get_nowait()()
        except queue.Empty:
            pass
        self.after(100, self._drain)

    def run_background(self, fn, *args, **kwargs):
        def worker():
            self.log("Started...")
            try:
                fn(*args, **kwargs)
                self.log("Finished.")
            except Exception as exc:  # report errors in the log instead of crashing
                self.log(f"ERROR: {exc}")
        threading.Thread(target=worker, daemon=True).start()


if __name__ == "__main__":
    App().mainloop()
