"""The Downloads screen: gallery-dl with a memory.

Left: what to download - your two Twitter bookmark accounts (and both, one after the other), downloads you've
saved, and recent ones you ran without saving. Middle: that download's options. Right: the run in progress and
the files arriving, and what the download remembers (its history and where the next run stops).

Every download remembers what it downloaded, so running it again fetches only what's new. Both bookmark
accounts share one history, so something saved from one account is skipped on the other."""
import copy
import threading
import time
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QCheckBox, QComboBox, QDoubleSpinBox, QFileDialog,
                               QFrame, QHBoxLayout, QHeaderView, QLabel, QListWidget, QListWidgetItem,
                               QPlainTextEdit, QProgressBar, QSpinBox, QTreeWidget, QTreeWidgetItem, QVBoxLayout,
                               QWidget)

import browser_account as ba
import dialogs
import fileops
import gdl_engine as ge
import gdl_store as gs
import gdl_ui
import icons
import jobs
import theme
from app_pages import Box, group, setting, splitter
from media_utils import VIDEO_EXTENSIONS, open_path, show_in_explorer
from pages_common import plural
from widgets import Banner, ElidedLabel, Page, Segmented, button, label, line_edit, repolish, tool_row, toolbar

BOTH = "both"
BROWSERS = ["firefox", "chrome", "edge", "brave", "opera", "vivaldi", "chromium", "safari"]
ROLE = Qt.UserRole


def ago(ts):
    if not ts:
        return "never"
    s = max(0, time.time() - ts)
    if s < 60:
        return "just now"
    if s < 3600:
        return plural(int(s // 60), "minute") + " ago"
    if s < 86400:
        return plural(int(s // 3600), "hour") + " ago"
    if s < 86400 * 14:
        return plural(int(s // 86400), "day") + " ago"
    return time.strftime("%d %b %Y", time.localtime(ts))


class DownloadsPage(Page):
    title = "Downloads"
    subtitle = ("Twitter bookmarks and any page gallery-dl can read. Only what's new downloads; everything "
                "downloaded before is remembered and skipped.")
    key = "gdl"
    icon = "download"

    def build(self):
        self.data = gs.load()
        self.sid = None            # the selected download's id ("main", "second", "both", or a saved/recent id)
        self.current = None        # a working copy of its settings
        self.dirty = False
        self.loading = False
        self.running = None        # the job, while one of ours runs
        self.run_files = []

        self.engine_banner = Banner("gallery-dl isn't set up.", "Use the gallery-dl.exe you have, or download "
                                    "the newest one (about 13 MB).", "Set up…", lambda: gdl_ui.setup(self.app),
                                    "download")
        self.banners.addWidget(self.engine_banner)
        self.switch_banner = Banner("Switch accounts in Firefox.", "", None, None, "bookmark")
        self.switch_banner.hide()
        self.banners.addWidget(self.switch_banner)
        gdl_ui.on_change(self.refresh_engine)

        # ----- toolbar: what's selected and the main actions -----
        bar, rows = toolbar()
        top = tool_row()
        self.sel_title = label("", "heading")
        top.addWidget(self.sel_title)
        self.sel_note = ElidedLabel("", "muted")
        top.addWidget(self.sel_note, 1)
        self.save_btn = button("Save", icon=icons.icon("save", theme.TEXT, 16),
                               tip="Keep these settings (and this download's history) in Saved")
        self.save_btn.clicked.connect(self.save)
        self.save_new_btn = button("Save as new…")
        self.save_new_btn.clicked.connect(self.save_as_new)
        self.revert_btn = button("Undo changes", "ghost")
        self.revert_btn.clicked.connect(self.revert)
        self.full_btn = button("Check everything", tip="Look through the whole page instead of stopping at what "
                               "you already have. Anything in the history is still skipped.")
        self.full_btn.clicked.connect(lambda: self.run(full=True))
        self.go_btn = button("Download new", "primary", icons.icon("download", theme.ON_ACCENT, 16))
        self.go_btn.clicked.connect(lambda: self.run())
        for b in (self.revert_btn, self.save_btn, self.save_new_btn, self.full_btn, self.go_btn):
            top.addWidget(b)
        rows.addLayout(top)
        self.body.addWidget(bar)
        self.panels.append(bar)

        # ----- left: the list -----
        self.list_box = Box("Downloads", min_w=230)
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setColumnCount(1)
        self.tree.setRootIsDecorated(False)
        self.tree.setIndentation(10)
        self.tree.setTextElideMode(Qt.ElideMiddle)
        self.tree.setSelectionMode(QAbstractItemView.SingleSelection)
        self.tree.currentItemChanged.connect(self._picked)
        self.tree.itemDoubleClicked.connect(lambda item, _c: self.run() if item.data(0, ROLE) else None)
        self.tree.setFrameShape(QFrame.NoFrame)
        self.list_box.v.addWidget(self.tree, 1)
        row = QHBoxLayout()
        row.setSpacing(theme.GAP - 2)
        new_btn = button("New download", icon=icons.icon("plus", theme.TEXT, 16))
        new_btn.clicked.connect(self.new_download)
        self.rename_btn = button("Rename", "ghost")
        self.rename_btn.clicked.connect(self.rename)
        self.delete_btn = button("", "danger-ghost", icons.icon("trash", theme.DANGER, 16),
                                 tip="Delete this download and its history (the downloaded files stay)")
        self.delete_btn.clicked.connect(self.delete)
        row.addWidget(new_btn)
        row.addStretch(1)
        row.addWidget(self.rename_btn)
        row.addWidget(self.delete_btn)
        self.list_box.v.addLayout(row)

        # ----- middle: the options -----
        self.opt_box = Box("Options", min_w=330)
        self._build_options(self.opt_box.v)
        self.opt_box.finish()

        # ----- right: the run and the history -----
        self.run_box = Box("This run", min_w=280)
        self._build_run(self.run_box.v)
        self.hist_box = Box("History", "what this download remembers", min_w=280)
        self._build_history(self.hist_box.v)
        self.hist_box.finish()
        right = splitter("gdl_right", Qt.Vertical, [self.run_box, self.hist_box], [420, 220])
        self.cols = splitter("gdl_cols", Qt.Horizontal, [self.list_box, self.opt_box, right], [260, 520, 380])
        self.body.addWidget(self.cols, 1)
        self.panels.append(self.list_box)

        self.timer = QTimer(self)
        self.timer.setInterval(250)
        self.timer.timeout.connect(self._tick)
        self.fill_list()
        self.refresh_engine()

    # ================================================================ options form
    def _build_options(self, v):
        self.w = {}
        # what and where
        group(v, "What and where")
        self.urls = QPlainTextEdit()
        self.urls.setPlaceholderText("https://x.com/someone/media\nOne address per line")
        self.urls.setFixedHeight(64)
        self.urls.textChanged.connect(self._urls_changed)
        self.urls_fixed = label("", "muted")
        self.urls_card, _n = setting(v, "Address", "A profile, a post, a gallery, a search: any page gallery-dl "
                                     "supports.", self.urls, self.urls_fixed)
        self.folder = line_edit("", "Choose where the files go")
        self.folder.setMinimumWidth(160)
        self.folder.editingFinished.connect(lambda: self._set("folder", self.folder.text().strip()))
        browse = button("Browse")
        browse.clicked.connect(self._browse_folder)
        open_btn = button("", "ghost", icons.icon("folder", theme.TEXT, 16), tip="Open the folder")
        open_btn.clicked.connect(lambda: self.folder.text().strip() and open_path(self.folder.text().strip()))
        setting(v, "Put the files in", "", self.folder, browse, open_btn)
        self.w["layout"] = Segmented([("flat", "All in this folder"), ("site", "Site and user subfolders")])
        self.w["layout"].changed.connect(lambda val: self._set("layout", val))
        setting(v, "Folders", "Subfolders are gallery-dl's own, like twitter\\name.", self.w["layout"])
        self.w["naming"] = Segmented([("original", "Original names"), ("default", "gallery-dl's"),
                                      ("custom", "Custom")])
        self.w["naming"].changed.connect(self._naming_changed)
        self.pattern = line_edit("", "{date:%Y-%m-%d}_{filename}.{extension}", mono=True)
        self.pattern.setMinimumWidth(180)
        self.pattern.editingFinished.connect(lambda: self._set("pattern", self.pattern.text().strip()))
        _f, self.naming_note = setting(v, "File names", "", self.w["naming"], self.pattern)

        # login
        group(v, "Login", "for pages you have to be signed in to see")
        self.w["login"] = Segmented([("none", "None"), ("browser", "From a browser"), ("file", "Cookies file")])
        self.w["login"].changed.connect(self._login_changed)
        self.browser = QComboBox()
        for b in BROWSERS:
            self.browser.addItem(b.capitalize(), b)
        self.browser.currentIndexChanged.connect(lambda _i: self._set("browser", self.browser.currentData()))
        self.profile = line_edit("", "Profile")
        self.profile.setFixedWidth(110)
        self.profile.editingFinished.connect(lambda: self._set("profile", self.profile.text().strip()))
        self.cookies = line_edit("", "cookies.txt")
        self.cookies.setMinimumWidth(140)
        self.cookies.editingFinished.connect(lambda: self._set("cookies_file", self.cookies.text().strip()))
        self.cookies_btn = button("Browse")
        self.cookies_btn.clicked.connect(self._browse_cookies)
        self.check_btn = button("Which account?", "ghost", tip="Read which Twitter account Firefox is signed in to")
        self.check_btn.clicked.connect(self.check_account)
        _f, self.login_note = setting(v, "Sign in with", "", self.w["login"])
        self.browser_card, _n = setting(v, "Browser", "Its usual profile unless you name one.", self.browser,
                                        self.profile, self.check_btn)
        self.cookies_card, _n = setting(v, "Cookies file", "", self.cookies, self.cookies_btn)

        # what to get
        group(v, "What to get")
        boxes = []
        for key, text in (("photos", "Pictures"), ("videos", "Videos"), ("gifs", "GIFs")):
            cb = QCheckBox(text)
            cb.toggled.connect(lambda on, k=key: self._set(k, on))
            self.w[key] = cb
            boxes.append(cb)
        setting(v, "Kinds of file", "", *boxes)
        tboxes = []
        for key, text in (("retweets", "Retweets"), ("replies", "Replies"), ("quoted", "Quoted tweets")):
            cb = QCheckBox(text)
            cb.toggled.connect(lambda on, k=key: self._set(k, on))
            self.w[key] = cb
            tboxes.append(cb)
        self.twitter_card, _n = setting(v, "Twitter also", "For profiles and searches.", *tboxes)

        # skipping
        group(v, "Skipping")
        self.w["history"] = QCheckBox("On")
        self.w["history"].toggled.connect(lambda on: (self._set("history", on), self._show_parts()))
        setting(v, "Remember what's downloaded", "Run it again and only new files download.", self.w["history"])
        self.w["stop_after"] = QSpinBox()
        self.w["stop_after"].setRange(0, 100000)
        self.w["stop_after"].setSpecialValueText("Never")
        self.w["stop_after"].setSuffix(" in a row")
        self.w["stop_after"].setFixedWidth(130)
        self.w["stop_after"].valueChanged.connect(lambda n: self._set("stop_after", n))
        self.stop_card, self.stop_note = setting(
            v, "Stop after", "Files in a row that were downloaded before. A few repeats don't stop it.",
            self.w["stop_after"])
        self.w["skip_bookmarks"] = QCheckBox("On")
        self.w["skip_bookmarks"].toggled.connect(lambda on: self._set("skip_bookmarks", on))
        self.skipbm_card, _n = setting(v, "Skip what your bookmarks downloaded",
                                       "Useful for an artist whose tweets you also bookmark.",
                                       self.w["skip_bookmarks"])
        self.skip_list = QListWidget()
        self.skip_list.setFixedHeight(74)
        self.skip_list.setTextElideMode(Qt.ElideMiddle)
        add_skip = button("Add…")
        add_skip.clicked.connect(self._add_skip)
        rem_skip = button("Remove", "ghost")
        rem_skip.clicked.connect(self._remove_skip)
        hold = QWidget()
        hv = QVBoxLayout(hold)
        hv.setContentsMargins(0, 0, 0, 0)
        hv.setSpacing(4)
        hv.addWidget(self.skip_list)
        hb = QHBoxLayout()
        hb.addWidget(add_skip)
        hb.addWidget(rem_skip)
        hb.addStretch(1)
        hv.addLayout(hb)
        hold.setMinimumWidth(220)
        self.skipf_card, _n = setting(v, "Also skip files already in", "Matched by file name, including subfolders "
                                      "(Twitter). For the folders you sort downloads into.", hold)

        # limits
        group(v, "Limits")
        self.after = line_edit("", "2025-01-31", width=110)
        self.after.editingFinished.connect(lambda: self._set("after", self.after.text().strip()))
        self.before = line_edit("", "2026-12-31", width=110)
        self.before.editingFinished.connect(lambda: self._set("before", self.before.text().strip()))
        setting(v, "Posts from … to", "Leave empty for all.", self.after, label("to", "muted"), self.before)
        self.w["first"] = QSpinBox()
        self.w["first"].setRange(0, 1000000)
        self.w["first"].setSpecialValueText("All")
        self.w["first"].setFixedWidth(110)
        self.w["first"].valueChanged.connect(lambda n: self._set("first", n))
        setting(v, "Only the first", "Files, newest first.", self.w["first"])
        self.size_min = line_edit("", "e.g. 50k", width=90)
        self.size_min.editingFinished.connect(lambda: self._set("size_min", self.size_min.text().strip()))
        self.size_max = line_edit("", "e.g. 200M", width=90)
        self.size_max.editingFinished.connect(lambda: self._set("size_max", self.size_max.text().strip()))
        setting(v, "File size", "Smallest and largest to download.", self.size_min, label("to", "muted"),
                self.size_max)
        self.rate = line_edit("", "e.g. 2M", width=90)
        self.rate.editingFinished.connect(lambda: self._set("rate", self.rate.text().strip()))
        self.w["wait"] = QDoubleSpinBox()
        self.w["wait"].setRange(0, 120)
        self.w["wait"].setDecimals(1)
        self.w["wait"].setSuffix(" s")
        self.w["wait"].setFixedWidth(90)
        self.w["wait"].valueChanged.connect(lambda n: self._set("wait", n))
        self.w["retries"] = QSpinBox()
        self.w["retries"].setRange(-1, 100)
        self.w["retries"].setSpecialValueText("Forever")
        self.w["retries"].setFixedWidth(90)
        self.w["retries"].valueChanged.connect(lambda n: self._set("retries", n))
        setting(v, "Speed and patience", "Speed limit per second, a wait between requests (helps with rate "
                "limits) and how often to retry.", self.rate, self.w["wait"], self.w["retries"])

        # extras
        group(v, "Extras")
        eboxes = []
        for key, text in (("metadata", "Save post details (.json)"), ("post_date", "File date = post date"),
                          ("zip", "Put them in a zip")):
            cb = QCheckBox(text)
            cb.toggled.connect(lambda on, k=key: self._set(k, on))
            self.w[key] = cb
            eboxes.append(cb)
        setting(v, "With each download", "", *eboxes)
        self.w["use_config"] = QCheckBox("On")
        self.w["use_config"].toggled.connect(lambda on: self._set("use_config", on))
        setting(v, "Use your gallery-dl settings file", "Logins and site options you set up for gallery-dl "
                "itself (config.json).", self.w["use_config"])

        # advanced
        group(v, "Advanced")
        self.extra = line_edit("", "--sleep 2 -o videos=false", mono=True)
        self.extra.setMinimumWidth(180)
        self.extra.editingFinished.connect(lambda: self._set("extra", self.extra.text().strip()))
        setting(v, "More gallery-dl options", "Added as typed.", self.extra)
        self.command = QPlainTextEdit()
        self.command.setReadOnly(True)
        self.command.setObjectName("mono")
        self.command.setFixedHeight(70)
        copy_btn = button("Copy", "ghost", icons.icon("copy", theme.TEXT, 16))
        copy_btn.clicked.connect(lambda: (QApplication.clipboard().setText(self.command.toPlainText()),
                                          self.app.toast("Command copied.", "ok")))
        hold2 = QWidget()
        h2 = QVBoxLayout(hold2)
        h2.setContentsMargins(0, 0, 0, 0)
        h2.addWidget(self.command)
        h2.addWidget(copy_btn, 0, Qt.AlignLeft)
        hold2.setMinimumWidth(240)
        setting(v, "The command", "The same download in a Command Prompt (without the app's history checks).",
                hold2)

    # ================================================================ run and history panels
    def _build_run(self, v):
        self.stage = label("Nothing running.", "value")
        self.stage.setWordWrap(True)
        v.addWidget(self.stage)
        self.bar = QProgressBar()
        self.bar.setTextVisible(False)
        self.bar.setRange(0, 1000)
        self.bar.setValue(0)
        v.addWidget(self.bar)
        self.times = label("", "caption")
        v.addWidget(self.times)
        self.counts = label("", "muted")
        self.counts.setWordWrap(True)
        v.addWidget(self.counts)
        self.files = QListWidget()
        self.files.setTextElideMode(Qt.ElideMiddle)
        self.files.setMinimumHeight(120)
        self._files_hint()
        self.files.itemDoubleClicked.connect(lambda it: open_path(it.data(ROLE)) if it.data(ROLE) else None)
        v.addWidget(self.files, 1)
        row = QHBoxLayout()
        self.open_run = button("Open the folder", icon=icons.icon("folder", theme.TEXT, 16))
        self.open_run.clicked.connect(self._open_run_folder)
        self.show_file = button("Show in Explorer", "ghost")
        self.show_file.clicked.connect(lambda: self.files.currentItem() and self.files.currentItem().data(ROLE)
                                       and show_in_explorer(self.files.currentItem().data(ROLE)))
        row.addWidget(self.open_run)
        row.addWidget(self.show_file)
        row.addStretch(1)
        v.addLayout(row)

    def _files_hint(self):
        self.files.clear()
        hint = QListWidgetItem("Files show here as they arrive. Double-click one to open it.")
        hint.setFlags(Qt.NoItemFlags)
        self.files.addItem(hint)

    def _build_history(self, v):
        self.hist_count = label("", "value")
        self.hist_count.setWordWrap(True)
        v.addWidget(self.hist_count)
        self.hist_stop = label("", "caption", wrap=True)
        v.addWidget(self.hist_stop)
        row = QHBoxLayout()
        self.mark_btn = button("Mark all as downloaded…", tip="Walk the whole page and remember every file "
                               "without downloading it")
        self.mark_btn.clicked.connect(self.mark_all)
        self.clear_btn = button("Clear…", "danger-ghost", tip="Forget what this download remembers")
        self.clear_btn.clicked.connect(self.clear_history)
        row.addWidget(self.mark_btn)
        row.addStretch(1)
        row.addWidget(self.clear_btn)
        v.addLayout(row)

    # ================================================================ the list
    def fill_list(self, select=None):
        self.data = gs.load()
        select = select or self.sid or "main"
        self.tree.blockSignals(True)
        self.tree.clear()
        bold = self.tree.font()
        bold.setBold(True)

        def head(text):
            it = QTreeWidgetItem([text])
            it.setFlags(Qt.ItemIsEnabled)
            it.setFont(0, bold)
            it.setForeground(0, self.palette().mid())
            self.tree.addTopLevelItem(it)
            it.setExpanded(True)
            return it

        def add(parent, sid, text, when, icon_name):
            it = QTreeWidgetItem([text])
            it.setData(0, ROLE, sid)
            it.setIcon(0, icons.icon(icon_name, theme.SEC, 16))
            it.setToolTip(0, f"{text}\nLast run: {when}" if when else text)
            parent.addChild(it)
            return it

        bm = head("Twitter bookmarks")
        for key, name in gs.ACCOUNTS:
            acc = self.data["accounts"][key]
            add(bm, key, name, ago((acc.get("last") or {}).get("when")), "bookmark")
        add(bm, BOTH, "Both, one after the other", "", "bookmark")
        sv = head(f"Saved  {len(self.data['saved'])}" if self.data["saved"] else "Saved")
        if not self.data["saved"]:
            hint = QTreeWidgetItem(["Save a download to keep it here"])
            hint.setFlags(Qt.NoItemFlags)
            sv.addChild(hint)
        for src in self.data["saved"]:
            add(sv, src["id"], gs.title(src), ago((src.get("last") or {}).get("when")), "save")
        rc = head(f"Recent  {len(self.data['recent'])}" if self.data["recent"] else "Recent")
        if not self.data["recent"]:
            hint = QTreeWidgetItem(["Downloads you run without saving"])
            hint.setFlags(Qt.NoItemFlags)
            rc.addChild(hint)
        for src in self.data["recent"]:
            add(rc, src["id"], gs.title(src), ago((src.get("last") or {}).get("when")), "history")
        if self.sid == "new" and select == "new":
            self.tree.setCurrentItem(None)
        self.tree.blockSignals(False)
        if select != "new":
            self._select(select)

    def _select(self, sid):
        for i in range(self.tree.topLevelItemCount()):
            top = self.tree.topLevelItem(i)
            for j in range(top.childCount()):
                if top.child(j).data(0, ROLE) == sid:
                    self.tree.setCurrentItem(top.child(j))
                    return
        self.tree.setCurrentItem(self.tree.topLevelItem(0).child(0))

    def _picked(self, item, _prev):
        if item is None or not item.data(0, ROLE):
            return
        sid = item.data(0, ROLE)
        if sid == self.sid:
            return
        if not self._leave_ok():
            self.tree.blockSignals(True)
            self._select(self.sid) if self.sid != "new" else self.tree.setCurrentItem(None)
            self.tree.blockSignals(False)
            return
        self.show_source(sid)

    def _leave_ok(self):
        """Unsaved changes to a saved download: keep them, drop them, or stay."""
        if not self.dirty or not self.current or self.current.get("kind") != "saved":
            return True
        answer = dialogs.choose("Save the changes first?", f"{gs.title(self.current)} has changes that aren't "
                                "saved.", [("drop", "Don't save", "ghost"), ("save", "Save", "primary")])
        if answer == "save":
            self.save()
            return True
        return answer == "drop"

    def show_source(self, sid):
        self.sid = sid
        self.data = gs.load()
        if sid == BOTH:
            src = copy.deepcopy(self.data["accounts"]["main"])
        elif sid == "new":
            src = self.current
        else:
            src = copy.deepcopy(gs.find(self.data, sid))
        if src is None:
            sid, src = "main", copy.deepcopy(self.data["accounts"]["main"])
            self.sid = sid
        self.current = src
        self.dirty = False
        self._fill_form()
        self.refresh_buttons()
        self.refresh_history()

    # ================================================================ form <-> settings
    def _fill_form(self):
        self.loading = True
        o = ge.options(self.current)
        bookmarks = self.current.get("kind") == "bookmarks"
        self.urls.setPlainText("\n".join(self.current.get("urls", [])))
        self.urls.setVisible(not bookmarks)
        self.urls_fixed.setVisible(bookmarks)
        self.urls_fixed.setText(gs.BOOKMARKS_URL)
        self.urls_card.note.setText("Your bookmarks, as the account Firefox is signed in to sees them."
                                    if bookmarks else "A profile, a post, a gallery, a search: any page gallery-dl "
                                    "supports. One per line.")
        self.folder.setText(o["folder"])
        for key in ("layout", "naming", "login"):
            self.w[key].set_value(o[key])
        self.pattern.setText(o["pattern"])
        i = self.browser.findData(o["browser"])
        self.browser.setCurrentIndex(max(0, i))
        self.profile.setText(o["profile"])
        self.cookies.setText(o["cookies_file"])
        for key in ("photos", "videos", "gifs", "retweets", "replies", "quoted", "history", "skip_bookmarks",
                    "metadata", "post_date", "zip", "use_config"):
            self.w[key].setChecked(bool(o[key]))
        for key in ("stop_after", "first", "retries"):
            self.w[key].setValue(int(o[key] or 0))
        self.w["wait"].setValue(float(o["wait"] or 0))
        self.after.setText(o["after"])
        self.before.setText(o["before"])
        self.size_min.setText(o["size_min"])
        self.size_max.setText(o["size_max"])
        self.rate.setText(o["rate"])
        self.extra.setText(o["extra"])
        self.skip_list.clear()
        for f in o["skip_folders"]:
            self.skip_list.addItem(f)
        self.loading = False
        self._show_parts()
        self._show_command()

    def _set(self, key, value):
        if self.loading or self.current is None:
            return
        opts = self.current.setdefault("options", {})
        if opts.get(key, ge.DEFAULTS.get(key)) == value:
            return
        opts[key] = value
        self._changed()

    def _changed(self):
        self._show_command()
        self._show_parts()
        kind = self.current.get("kind")
        if kind == "bookmarks":
            self._store_account()
        elif kind == "recent":
            gs.put(self.current)
        else:
            self.dirty = True
        self.refresh_buttons()

    def _store_account(self):
        """Bookmark accounts save as you change them. "Both" changes what the two have in common."""
        data = gs.load()
        if self.sid == BOTH:
            for key, _n in gs.ACCOUNTS:
                own_folder = data["accounts"][key]["options"].get("folder", "")
                merged = dict(self.current["options"])
                merged["folder"] = own_folder
                data["accounts"][key]["options"] = merged
        else:
            data["accounts"][self.sid] = self.current
            # what you already have is the same for both accounts
            other = "second" if self.sid == "main" else "main"
            data["accounts"][other]["options"]["skip_folders"] = list(self.current["options"].get("skip_folders", []))
        gs.save(data)

    def _urls_changed(self):
        if self.loading or self.current is None:
            return
        urls = [u.strip() for u in self.urls.toPlainText().splitlines() if u.strip()]
        if urls != self.current.get("urls"):
            self.current["urls"] = urls
            self._changed()

    def _naming_changed(self, val):
        self._set("naming", val)
        self._show_parts()

    def _login_changed(self, val):
        self._set("login", val)
        self._show_parts()

    def _show_parts(self):
        if self.current is None:
            return
        o = ge.options(self.current)
        urls = self.current.get("urls", [])
        twitter = bool(urls) and all(ge.is_twitter(u) for u in urls)
        bookmarks = self.current.get("kind") == "bookmarks"
        self.pattern.setVisible(o["naming"] == "custom")
        self.naming_note.setText({"original": "As the site named them (gallery-dl -f /O).",
                                  "default": "gallery-dl's usual names, like name_tweetid_1.jpg.",
                                  "custom": "Fields in {curly brackets}. gallery-dl -K <address> lists them."}
                                 [o["naming"]])
        browser = o["login"] == "browser"
        self.browser_card.setVisible(browser)
        self.cookies_card.setVisible(o["login"] == "file")
        self.check_btn.setVisible(browser and o["browser"] == "firefox" and twitter)
        self.login_note.setText({"none": "Public pages only.",
                                 "browser": "Uses the browser's sign-in. Firefox works best: Chrome and Edge lock "
                                 "their cookies on Windows.",
                                 "file": "A cookies.txt exported from your browser."}[o["login"]])
        self.twitter_card.setVisible(twitter and not bookmarks)
        self.stop_card.setVisible(o["history"])
        self.skipbm_card.setVisible(twitter and not bookmarks and o["history"])
        self.skipf_card.setVisible(twitter and o["history"])

    def _show_command(self):
        if self.current is None:
            return
        try:
            self.command.setPlainText(ge.show_command(self.current, gs.history_file(self.current)
                                                      if ge.options(self.current)["history"] else None))
        except Exception as exc:
            self.command.setPlainText(f"(can't show the command: {exc})")

    def _browse_folder(self):
        chosen = QFileDialog.getExistingDirectory(self, "Put the downloads in", self.folder.text().strip())
        if chosen:
            self.folder.setText(str(Path(chosen)))
            self._set("folder", str(Path(chosen)))

    def _browse_cookies(self):
        chosen, _f = QFileDialog.getOpenFileName(self, "Choose a cookies file", self.cookies.text().strip(),
                                                 "Cookies (*.txt);;All files (*)")
        if chosen:
            self.cookies.setText(str(Path(chosen)))
            self._set("cookies_file", str(Path(chosen)))

    def _add_skip(self):
        chosen = QFileDialog.getExistingDirectory(self, "Skip files already in this folder")
        if not chosen:
            return
        folders = list(ge.options(self.current)["skip_folders"])
        if str(Path(chosen)) not in folders:
            folders.append(str(Path(chosen)))
            self.skip_list.addItem(str(Path(chosen)))
            self._set("skip_folders", folders)

    def _remove_skip(self):
        it = self.skip_list.currentItem()
        if it is None:
            return
        folders = [f for f in ge.options(self.current)["skip_folders"] if f != it.text()]
        self.skip_list.takeItem(self.skip_list.row(it))
        self._set("skip_folders", folders)

    # ================================================================ buttons
    def refresh_buttons(self):
        if self.current is None:
            return
        kind = self.current.get("kind")
        name = "Both bookmark accounts" if self.sid == BOTH else gs.title(self.current)
        self.sel_title.setText(name)
        self.opt_box.title_label.setText("Options" if self.sid != BOTH else
                                               "Options shared by both accounts (each keeps its folder)")
        notes = {"bookmarks": "Settings save as you change them.",
                 "saved": "Unsaved changes." if self.dirty else "Saved.",
                 "recent": "Not saved. Save it to keep it in Saved.",
                 "new": "Not run yet. It goes to Recent when you run it."}
        last = (self.current.get("last") or {}).get("when")
        self.sel_note.setText(notes.get(kind, "") + (f"  Last run {ago(last)}." if last and self.sid != BOTH else ""))
        self.save_btn.setVisible(kind in ("saved", "recent", "new"))
        self.save_btn.setEnabled(kind != "saved" or self.dirty)
        self.save_new_btn.setVisible(kind == "saved")
        self.revert_btn.setVisible(kind == "saved" and self.dirty)
        self.rename_btn.setEnabled(kind in ("saved", "recent"))
        self.delete_btn.setEnabled(kind in ("saved", "recent"))
        self.full_btn.setEnabled(ge.options(self.current)["history"])
        what = "Download new" if ge.options(self.current)["history"] else "Download"
        if self.sid == BOTH:
            what += " from both accounts"
        busy = self.app.queue.busy()
        self.go_btn.setText("Add to the queue" if busy else what)
        self.go_btn.setToolTip("Another job is running. This one starts when it finishes." if busy else
                               "Double-clicking a download in the list does the same.")

    def queue_changed(self, busy):
        self.refresh_buttons()

    def refresh_engine(self):
        ready = ge.find_exe() is not None
        self.engine_banner.setVisible(not ready)
        self.go_btn.setEnabled(ready)
        self.full_btn.setEnabled(ready)
        self.mark_btn.setEnabled(ready)
        self._show_command()

    def shown(self):
        self.refresh_engine()
        if self.current is None:
            self.show_source("main")
        self.refresh_history()

    def new_download(self):
        if not self._leave_ok():
            return
        base = copy.deepcopy(self.current) if self.current and self.current.get("kind") != "bookmarks" else None
        src = gs.new_download()
        src["kind"] = "new"
        if base:
            src["options"] = copy.deepcopy(base.get("options", {}))
        self.tree.blockSignals(True)
        self.tree.setCurrentItem(None)
        self.tree.clearSelection()
        self.tree.blockSignals(False)
        self.current = src
        self.sid = "new"
        self.dirty = False
        self._fill_form()
        self.refresh_buttons()
        self.refresh_history()
        self.urls.setFocus()

    def save(self):
        kind = self.current.get("kind")
        if kind == "saved":
            gs.put(self.current)
            self.dirty = False
            self.app.toast(f"Saved {gs.title(self.current)}.", "ok")
            self.fill_list(self.current["id"])
            self.refresh_buttons()
            return
        name = dialogs.get_text("Save this download", "Give it a name you'll recognise. It keeps its settings "
                                "and what it has downloaded.", gs.title(self.current) if self.current.get("urls")
                                else "", "Save")
        if not name:
            return
        self.current["name"] = name
        self.current["kind"] = "saved"
        gs.put(self.current)
        self.dirty = False
        self.sid = self.current["id"]
        self.fill_list(self.sid)
        self.app.toast(f"Saved {name}.", "ok")

    def save_as_new(self):
        name = dialogs.get_text("Save as a new download", "The new one starts with the same history, so it skips "
                                "what this one downloaded.", gs.title(self.current) + " (copy)", "Save")
        if not name:
            return
        old = self.current
        new = copy.deepcopy(old)
        new["id"] = gs.new_download()["id"]
        new["name"] = name
        new["kind"] = "saved"
        new["last"] = None
        gs.copy_history(old, new)
        gs.put(new)
        self.dirty = False
        self.sid = new["id"]
        self.current = new
        self.fill_list(self.sid)
        self.app.toast(f"Saved {name}.", "ok")

    def revert(self):
        self.sid, sid = None, self.sid
        self.show_source(sid)

    def rename(self):
        if self.current.get("kind") not in ("saved", "recent"):
            return
        name = dialogs.get_text("Rename", "", gs.title(self.current), "Rename")
        if not name:
            return
        self.current["name"] = name
        stored = gs.find(gs.load(), self.current["id"])
        if stored is not None:
            stored["name"] = name
            gs.put(stored)
        self.fill_list(self.current["id"])
        self.refresh_buttons()

    def delete(self):
        src = self.current
        if src.get("kind") not in ("saved", "recent"):
            return
        count = ge.history_count(gs.history_file(src))
        if not dialogs.ask(f"Delete {gs.title(src)}?", "It comes off the list and its history goes to the Recycle "
                           f"Bin ({plural(count, 'file')} remembered). The files it downloaded stay where they are.",
                           "Delete", kind="danger", icon_name="trash"):
            return
        try:
            gs.remove(src["id"], self.app.log)
        except fileops.RecycleError as exc:
            dialogs.error("Couldn't delete the history", str(exc))
            return
        self.sid = None
        self.fill_list("main")
        self.app.toast(f"Deleted {gs.title(src)}.", "ok")

    def check_account(self):
        o = ge.options(self.current)
        uid = ba.twitter_user_id(o["profile"])
        data = gs.load()
        if uid is None:
            dialogs.info("Firefox isn't signed in to Twitter",
                         "No Twitter/X sign-in was found in Firefox. Sign in at x.com in Firefox, then try again.",
                         icon_name="bookmark")
            return
        owner = next((name for key, name in gs.ACCOUNTS if data["accounts"][key].get("twitter_user") == uid), None)
        text = (f"Firefox is signed in to your {owner} (Twitter user {uid})." if owner else
                f"Firefox is signed in to Twitter user {uid}, which isn't linked to an account here yet. The first "
                "download from an account links it.")
        dialogs.info("Firefox's Twitter account", text, icon_name="bookmark")

    # ================================================================ history panel
    def refresh_history(self):
        if self.current is None:
            return
        o = ge.options(self.current)
        if not o["history"]:
            self.hist_count.setText("Not remembering for this download.")
            self.hist_stop.setText("Every run downloads everything it finds (files already in the folder are "
                                   "still skipped by gallery-dl).")
            self.mark_btn.setEnabled(False)
            self.clear_btn.setEnabled(False)
            return
        hist = gs.history_file(self.current)
        n = ge.history_count(hist)
        shared = self.current.get("kind") == "bookmarks"
        self.hist_count.setText(f"{n:,} files remembered" + (", shared by both accounts." if shared else "."))
        self.mark_btn.setEnabled(ge.find_exe() is not None and bool(self.current.get("urls")))
        self.clear_btn.setEnabled(n > 0)
        if self.sid == BOTH:
            self.hist_stop.setText("Main account runs first, then Second. When Main is done the app waits for you "
                                   "to switch Firefox to your Second account, and carries on by itself.")
        elif shared:
            acc = self.current
            folder = o["folder"]
            if acc.get("markers"):
                stop = ("Next run stops when it reaches the tweets that were at the top of the last run "
                        f"(last run {ago((acc.get('last') or {}).get('when'))}).")
            else:
                seeds = gs.seeds_from_folder(folder)
                stop = (f"First run stops at the {plural(len(seeds), 'file')} already in the folder "
                        f"({', '.join(seeds[:3])}{'…' if len(seeds) > 3 else ''})." if seeds else
                        "First run: no stop point yet (the folder is empty), so it checks everything until "
                        f"{o['stop_after']} files in a row were downloaded before. If it finds far more than "
                        "usual it asks first.")
            user = acc.get("twitter_user")
            stop += f" Linked to Twitter user {user}." if user else ""
            self.hist_stop.setText(stop + f" Safety net: {o['stop_after'] or 'no'} files in a row already had.")
        else:
            stop = (f"Stops after {o['stop_after']} files in a row that were downloaded before."
                    if o["stop_after"] else "Looks through the whole page each run (Stop after is Never).")
            last = self.current.get("last") or {}
            if last:
                stop += f" Last run {ago(last.get('when'))}: {plural(last.get('new', 0), 'new file')}."
            self.hist_stop.setText(stop)

    def mark_all(self):
        src = copy.deepcopy(self.current)
        if not dialogs.ask("Mark everything as downloaded?",
                           "gallery-dl looks through the whole page and remembers every file on it without "
                           "downloading anything. Afterwards only files added from now on download. Best done just "
                           "after a download, so nothing new gets marked. On a big bookmarks list this can take a "
                           "while because Twitter limits how fast pages load.", "Mark all", icon_name="history"):
            return
        if src.get("kind") == "new":
            src = self._promote(src)

        def job(log, progress):
            if src.get("kind") == "bookmarks":
                self._account(src, log, progress)
            n = ge.mark_all(src, gs.history_file(src), log, progress)
            return {"summary": f"{n:,} files remembered"}
        self.app.start(jobs.Job(f"Marking {gs.title(src)} as downloaded", job, short="Marking", own_log=True,
                                done=lambda _j: self.refresh_history(),
                                failed=lambda j: dialogs.error("Couldn't mark them", str(j.error))))

    def clear_history(self):
        src = self.current
        n = ge.history_count(gs.history_file(src))
        shared = " It's shared by both bookmark accounts." if src.get("kind") == "bookmarks" else ""
        if not dialogs.ask("Forget what's been downloaded?", f"{plural(n, 'file')} remembered.{shared} The history "
                           "file goes to the Recycle Bin; downloaded files stay. The next run downloads everything "
                           "again, unless it's in the folder already.", "Clear history", kind="danger",
                           icon_name="history"):
            return
        try:
            gs.clear_history(src, self.app.log)
        except fileops.RecycleError as exc:
            dialogs.error("Couldn't clear it", str(exc))
        self.refresh_history()

    # ================================================================ running
    def _promote(self, src):
        """A new download that's being run joins Recent (or reuses the recent one with the same setup)."""
        data = gs.load()
        for old in data["recent"] + data["saved"]:
            if gs.same_setup(old, src):
                old["options"] = src["options"]
                src = old
                break
        else:
            src["kind"] = "recent"
        gs.put(src)
        self.sid = src["id"]
        self.current = copy.deepcopy(src)
        self.fill_list(self.sid)
        return src

    def run(self, full=False):
        if self.current is None:
            return
        if ge.find_exe() is None:
            gdl_ui.setup(self.app)
            return
        for edit in (self.folder, self.pattern, self.profile, self.cookies, self.after, self.before, self.size_min,
                     self.size_max, self.rate, self.extra):
            edit.editingFinished.emit()
        if self.sid == BOTH:
            data = gs.load()
            sources = [copy.deepcopy(data["accounts"]["main"]), copy.deepcopy(data["accounts"]["second"])]
        else:
            src = copy.deepcopy(self.current)
            if not src.get("urls"):
                dialogs.info("Add an address first", "Paste the address of the page to download.", icon_name="download")
                return
            if src.get("kind") == "new":
                src = self._promote(src)
            elif src.get("kind") == "saved" and self.dirty:
                if dialogs.choose("Save the changes first?", "Run with the changes, and save them?",
                                  [("save", "Save and run", "primary")]) != "save":
                    return
                self.save()
                src = copy.deepcopy(self.current)
            sources = [src]
        for src in sources:
            if not ge.options(src)["folder"]:
                dialogs.info("Choose a folder first", f"Choose where {gs.title(src)} downloads go.", icon_name="folder")
                return
        title = ("both bookmark accounts" if self.sid == BOTH else gs.title(sources[0]))
        self.files.clear()
        self._files_hint()
        self.run_files = []
        self.run_folder = ge.options(sources[0])["folder"]
        self.stage.setText("Waiting to start…")
        self.counts.setText("")
        self.bar.setValue(0)
        job = jobs.Job(f"Downloading {title}" if not full else f"Checking all of {title}", self._job, sources, full,
                       short="Downloading", own_log=True, done=self._finished,
                       failed=self._failed)
        self.running = job
        self.app.start(job)
        self.timer.start()

    def _job(self, sources, full, log, progress):
        page = self
        parts = []
        total_new = total_done = total_failed = 0
        last_folder = None

        class Events:
            def started(self, name):
                pass

            def finished(self, path):
                page.app.on_main(lambda: page._file_arrived(path))

            def status(self, text):
                pass

        for n, src in enumerate(sources):
            name = gs.title(src)
            bookmarks = src.get("kind") == "bookmarks"
            if bookmarks:
                self._account(src, log, progress, wait=n > 0)
            o = ge.options(src)
            ctx = {"full": full, "bookmarks": bookmarks, "confirm": self._confirm_many}
            if bookmarks:
                ctx["markers"] = src.get("markers") or []
                if not ctx["markers"]:
                    ctx["seeds"] = gs.seeds_from_folder(o["folder"])
            elif o["skip_bookmarks"]:
                ctx["shared"] = [gs.history_file({"kind": "bookmarks"})]
            hist = gs.history_file(src) if o["history"] else None
            page.app.on_main(lambda nm=name: page.stage.setText(f"{nm}: looking for new files…"))
            log(f"{name}: starting.")
            rep = ge.run(src, hist, ctx, log, progress, Events())
            # retry anything that failed last time (Twitter bookmarks)
            retry = [t for t in src.get("retry", []) if t]
            retried = 0
            if retry and bookmarks:
                log(f"{name}: trying again {plural(len(retry), 'tweet')} that failed last time.")
                rsrc = dict(src, kind="recent", urls=[f"https://x.com/i/status/{t}" for t in retry])
                try:
                    rrep = ge.run(rsrc, hist, {"confirm": None}, log, progress, Events())
                    retried = len(rrep.done)
                    rep.done += rrep.done
                except ge.GdlError as exc:
                    log(f"{name}: the retry didn't work: {exc}")
            # remember where this run stopped and what failed
            stored = gs.find(gs.load(), src["id"]) or src
            if bookmarks and rep.top_tweets:
                stored["markers"] = rep.top_tweets
            if bookmarks:
                failed_tweets = sorted({ln.tweet for ln in rep.new if ln.name in rep.failed and ln.tweet})
                stored["retry"] = failed_tweets
                if src.get("twitter_user"):
                    stored["twitter_user"] = src["twitter_user"]
            stored["last"] = {"when": time.time(), "new": len(rep.done), "failed": len(rep.failed),
                              "have": rep.have, "stop": rep.stop_reason}
            gs.put(stored)
            total_new += len(rep.new) + retried
            total_done += len(rep.done)
            total_failed += len(rep.failed)
            last_folder = o["folder"]
            bits = [plural(len(rep.done), "new file")]
            if rep.have:
                bits.append(f"{rep.have:,} already in your folders")
            if rep.failed:
                bits.append(f"{len(rep.failed)} failed")
            parts.append(f"{name}: " + ", ".join(bits) + f" ({rep.stop_reason})")
            log(parts[-1])
            page.app.on_main(lambda t=" · ".join(parts): page.counts.setText(t))
        summary = (f"{plural(total_done, 'new file')} downloaded" +
                   (f", {total_failed} failed (tried again next time)" if total_failed else ""))
        if not total_done and not total_failed:
            summary = "Nothing new"
        return {"summary": summary, "detail": parts,
                "next": ("Open the folder", lambda f=last_folder: open_path(f)) if total_done else None}

    def _account(self, src, log, progress, wait=False):
        """Check Firefox is signed in to this bookmarks account; wait for you to switch when it isn't."""
        o = ge.options(src)
        if o["login"] != "browser" or o["browser"] != "firefox":
            return
        name = src["name"]
        other_key = "second" if src["id"] == "main" else "main"
        other = gs.load()["accounts"][other_key]
        uid = ba.twitter_user_id(o["profile"])
        if uid is None:
            log(f"{name}: couldn't tell which Twitter account Firefox is signed in to; carrying on.")
            return
        mine = src.get("twitter_user")
        theirs = other.get("twitter_user")
        if uid == theirs and uid != mine:
            started = time.monotonic()
            self.app.on_main(lambda: self._show_switch(name))
            log(f"{name}: Firefox is signed in to your {other['name']}. Waiting for you to switch.")
            try:
                while uid == theirs:
                    waited = fileops.clock(time.monotonic() - started)
                    progress(0, 0, f"Switch Firefox to your {name} (waiting {waited})", eta=False)
                    for _ in range(8):
                        time.sleep(0.25)
                        jobs.check_stop()
                    uid = ba.twitter_user_id(o["profile"]) or uid
            finally:
                self.app.on_main(self.switch_banner.hide)
            log(f"{name}: Firefox switched to Twitter user {uid}.")
        if not mine:
            src["twitter_user"] = uid
            log(f"{name} is Twitter user {uid}. The app checks it's the right account before each download.")
            return
        if uid != mine:
            answer = self._ask_main(lambda: dialogs.choose(
                f"Firefox is signed in to a different account",
                f"{name} was Twitter user {mine} last time; Firefox is now signed in to {uid}. Switch accounts in "
                f"Firefox and press Try again, or use this account as your {name} from now on.",
                [("use", f"Use it as {name}", "secondary"), ("retry", "Try again", "primary")]))
            if answer == "use":
                src["twitter_user"] = uid
            elif answer == "retry":
                return self._account(src, log, progress, wait)
            else:
                raise jobs.JobStopped()

    def _show_switch(self, name):
        self.switch_banner.set("Switch accounts in Firefox.", f"Sign in to your {name} at x.com in Firefox. The "
                               "download carries on by itself once you have.")
        self.switch_banner.show()

    def _confirm_many(self, count):
        return self._ask_main(lambda: dialogs.choose(
            f"{count:,} new files found",
            "That's far more than usual, so the stop point may have been lost (for example, the tweets it stops at "
            "were un-bookmarked). Download them all, or remember them as already downloaded without downloading?",
            [("mark", "Remember without downloading", "secondary"), ("all", f"Download all {count:,}", "primary")]))

    def _ask_main(self, fn):
        """Ask a question on the UI thread from the download's thread, and wait for the answer."""
        box, done = {}, threading.Event()

        def go():
            try:
                box["v"] = fn()
            finally:
                done.set()
        self.app.on_main(go)
        while not done.wait(0.2):
            jobs.check_stop()
        return box.get("v")

    def _file_arrived(self, path):
        if not self.run_files:
            self.files.clear()
        self.run_files.append(path)
        it = QListWidgetItem(Path(path).name)
        it.setData(ROLE, path)
        video = Path(path).suffix.lower() in VIDEO_EXTENSIONS
        it.setIcon(icons.icon("silent" if video else "image", theme.SEC, 16))
        it.setToolTip(path)
        self.files.insertItem(0, it)
        if self.files.count() > 2000:
            self.files.takeItem(self.files.count() - 1)

    def _tick(self):
        job = self.running
        if job is None:
            self.timer.stop()
            return
        if job.started is None:
            self.stage.setText("Waiting for the job before it to finish…")
            return
        frac = job.fraction()
        if frac is None:
            self.bar.setRange(0, 0)  # moving stripe: working, total not known yet
        else:
            self.bar.setRange(0, 1000)
            self.bar.setValue(int(frac * 1000))
        self.stage.setText(job.what)
        left = job.time_left()
        pct = f"{frac * 100:.0f}% · " if frac is not None else ""
        self.times.setText(f"{pct}{fileops.clock(job.elapsed())} elapsed" +
                           (f" · about {fileops.clock(left)} left" if left is not None else
                            " · time left once the new files are counted" if frac is None else ""))
        if job.total:
            self.counts.setText(f"{job.done_count:,} of {job.total:,} files · {len(self.run_files):,} arrived")

    def _finished(self, job):
        self.timer.stop()
        self.running = None
        self.bar.setRange(0, 1000)
        self.bar.setValue(1000 if job.finished == "done" else self.bar.value())
        self.times.setText(f"Took {fileops.clock(job.elapsed())}")
        result = job.result if isinstance(job.result, dict) else {}
        if job.finished == "done":
            self.stage.setText(result.get("summary", "Done."))
            self.counts.setText("\n".join(result.get("detail", [])))
        else:
            self.stage.setText("Stopped. Files that finished are kept and remembered.")
        self.switch_banner.hide()
        self.data = gs.load()
        if self.current and self.current.get("kind") != "new":
            stored = gs.find(self.data, self.current["id"]) if self.sid != BOTH else None
            if stored is not None and not self.dirty:
                self.current = copy.deepcopy(stored)
        self.fill_list(self.sid if self.sid != "new" else None)
        self.refresh_history()

    def _failed(self, job):
        self.timer.stop()
        self.running = None
        self.bar.setRange(0, 1000)
        self.switch_banner.hide()
        self.stage.setText("Didn't finish.")
        self.times.setText("")
        self.counts.setText(str(job.error))
        self.refresh_history()
        if isinstance(job.error, ge.GdlError):
            dialogs.error("The download didn't work", str(job.error))

    def _open_run_folder(self):
        folder = getattr(self, "run_folder", None) or (ge.options(self.current)["folder"] if self.current else "")
        if folder:
            open_path(folder)

    # ----- dropping a links file or a folder: nothing to take -----
    def step(self, delta):
        return False
