"""Shared page layout: a scrolling area and helpers used by every tool page."""
import tkinter as tk
import weakref
from tkinter import filedialog, ttk

import customtkinter as ctk

import theme
from theme import button, entry, label, muted


def _pick(var, title, on_change=None):
    chosen = filedialog.askdirectory(title=title)
    if chosen:
        var.set(chosen)
        if on_change:
            on_change()


_live_areas = weakref.WeakSet()  # every page's scroll area, so the mouse wheel can find the one under the pointer


def _dispatch_wheel(event):
    for area in list(_live_areas):
        try:
            if area.winfo_exists():
                area._wheel(event)
        except tk.TclError:
            pass


class ScrollArea(ctk.CTkFrame):
    """Holds a page's content. When there is room the content fills the area and resizes with the window;
    when there isn't, it scrolls up/down and left/right."""

    def __init__(self, master):
        super().__init__(master, fg_color="transparent")
        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(0, weight=1)
        self.canvas = tk.Canvas(self, background=theme.APP_BG, highlightthickness=0, bd=0)
        vbar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        hbar = ttk.Scrollbar(self, orient="horizontal", command=self.canvas.xview)
        self.canvas.configure(yscrollcommand=vbar.set, xscrollcommand=hbar.set)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        vbar.grid(row=0, column=1, sticky="ns")
        hbar.grid(row=1, column=0, sticky="ew")

        self.inner = tk.Frame(self.canvas, background=theme.APP_BG)
        self._window = self.canvas.create_window(0, 0, window=self.inner, anchor="nw")
        self._callbacks = []
        self._last_size = None
        self._minimum = None  # (width, height) set by a page; None means "as big as its contents"
        _live_areas.add(self)
        self.canvas.bind("<Configure>", self._fit)
        self.inner.bind("<Configure>", self._fit)
        # bind_all is not allowed on CustomTkinter widgets, so the wheel is bound on the plain canvas.
        # Without add, this replaces the previous binding instead of stacking another one on every rebuild.
        self.canvas.bind_all("<MouseWheel>", _dispatch_wheel)

    def add_resize_callback(self, fn):
        self._callbacks.append(fn)

    def set_minimum(self, width, height):
        """The page fits the window down to this size, and only scrolls when the window is smaller."""
        self._minimum = (width, height)
        self._fit()

    def _fit(self, _event=None):
        cw, ch = self.canvas.winfo_width(), self.canvas.winfo_height()
        if self._minimum:
            w, h = max(cw, self._minimum[0]), max(ch, self._minimum[1])
        else:
            w = max(cw, self.inner.winfo_reqwidth())
            h = max(ch, self.inner.winfo_reqheight())
        self.canvas.itemconfigure(self._window, width=w, height=h)
        self.canvas.configure(scrollregion=(0, 0, w, h))
        # Only tell the page when the visible area really changed. Scrolling and content growth must not
        # trigger a redraw, or pages that resize their pictures to fit can feed back into themselves.
        if (cw, ch) != self._last_size:
            self._last_size = (cw, ch)
            for fn in self._callbacks:
                fn()

    def _wheel(self, event):
        # Scroll this page when the pointer is over it. Tables and text boxes scroll themselves.
        try:
            target = self.canvas.winfo_containing(event.x_root, event.y_root)
        except (KeyError, tk.TclError):
            return
        if target is None:
            return
        name = str(target)
        if name != str(self) and not name.startswith(str(self) + "."):
            return
        if isinstance(target, (ttk.Treeview, tk.Text)):
            return
        if event.state & 0x0001:  # Shift held: scroll sideways
            self.canvas.xview_scroll(int(-event.delta / 120), "units")
        else:
            self.canvas.yview_scroll(int(-event.delta / 120), "units")


def tree_in_card(parent, columns, headings, widths):
    """A table with a scrollbar, placed inside a rounded card. Every column can be resized by dragging
    the dividers in its heading. Returns the Treeview."""
    inner = ctk.CTkFrame(parent, fg_color="transparent")
    inner.pack(fill="both", expand=True, padx=12, pady=12)
    tree = ttk.Treeview(inner, columns=columns, show="headings", selectmode="extended", height=8)
    for col, text, width in zip(columns, headings, widths):
        tree.heading(col, text=text)
        tree.column(col, width=theme.px(width), minwidth=theme.px(90), stretch=True)
    scroll = ttk.Scrollbar(inner, orient="vertical", command=tree.yview)
    tree.configure(yscrollcommand=scroll.set)
    tree.pack(side="left", fill="both", expand=True)
    scroll.pack(side="right", fill="y")
    return tree


class Page(ctk.CTkFrame):
    """A tool page: a title and subtitle, then the page content in a scrolling area. Subclasses build() it."""
    title = ""
    subtitle = ""

    def __init__(self, master, app):
        super().__init__(master, fg_color="transparent")
        self.app = app
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        head = ctk.CTkFrame(self, fg_color="transparent")
        head.grid(row=0, column=0, sticky="ew", pady=(0, 16))
        label(head, self.title, size=28, weight="bold").pack(anchor="w")
        muted(head, self.subtitle, size=14).pack(anchor="w", pady=(4, 0))

        self.scroll = ScrollArea(self)
        self.scroll.grid(row=1, column=0, sticky="nsew")
        self.scroll.inner.grid_rowconfigure(0, weight=1)
        self.scroll.inner.grid_columnconfigure(0, weight=1)

        self.body = ctk.CTkFrame(self.scroll.inner, fg_color="transparent")
        self.body.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        self.body.grid_columnconfigure(0, weight=1)
        self.build()

    def build(self):
        raise NotImplementedError

    def folder_row(self, parent, row, text, var, title="Choose a folder", on_change=None):
        """Label, path box and Browse button on one row. The parent needs column 1 to stretch.
        on_change runs after a folder is picked."""
        label(parent, text).grid(row=row, column=0, sticky="w", padx=(18, 12), pady=8)
        entry(parent, var).grid(row=row, column=1, sticky="ew", padx=6, pady=8)
        button(parent, "Browse", lambda: _pick(var, title, on_change), width=110).grid(
            row=row, column=2, padx=(6, 18), pady=8)
