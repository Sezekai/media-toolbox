"""Shared page layout and helpers used by every tool page."""
import tkinter as tk
from tkinter import filedialog, ttk

import customtkinter as ctk

import theme
from theme import button, card, entry, label, muted


def _pick(var, title):
    chosen = filedialog.askdirectory(title=title)
    if chosen:
        var.set(chosen)


def tree_in_card(parent, columns, headings, widths):
    """A table with a scrollbar, placed inside a rounded card. Returns the Treeview."""
    inner = ctk.CTkFrame(parent, fg_color="transparent")
    inner.pack(fill="both", expand=True, padx=12, pady=12)
    tree = ttk.Treeview(inner, columns=columns, show="headings", selectmode="extended")
    for i, (col, text, width) in enumerate(zip(columns, headings, widths)):
        tree.heading(col, text=text)
        tree.column(col, width=width, stretch=(i == 0))
    scroll = ttk.Scrollbar(inner, orient="vertical", command=tree.yview)
    tree.configure(yscrollcommand=scroll.set)
    tree.pack(side="left", fill="both", expand=True)
    scroll.pack(side="right", fill="y")
    return tree


class Page(ctk.CTkFrame):
    """A tool page: a title, a subtitle, then the page body built by build()."""
    title = ""
    subtitle = ""

    def __init__(self, master, app):
        super().__init__(master, fg_color="transparent")
        self.app = app
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        head = ctk.CTkFrame(self, fg_color="transparent")
        head.grid(row=0, column=0, sticky="ew", pady=(0, 16))
        label(head, self.title, size=24, weight="bold").pack(anchor="w")
        muted(head, self.subtitle, size=13).pack(anchor="w", pady=(4, 0))

        self.body = ctk.CTkFrame(self, fg_color="transparent")
        self.body.grid(row=1, column=0, sticky="nsew")
        self.body.grid_columnconfigure(0, weight=1)
        self.build()

    def build(self):
        raise NotImplementedError

    def folder_row(self, parent, row, text, var, title="Choose a folder"):
        """Label, path box and Browse button on one row. The parent needs column 1 to stretch."""
        label(parent, text).grid(row=row, column=0, sticky="w", padx=(18, 12), pady=8)
        entry(parent, var).grid(row=row, column=1, sticky="ew", padx=6, pady=8)
        button(parent, "Browse", lambda: _pick(var, title), width=100).grid(
            row=row, column=2, padx=(6, 18), pady=8)
