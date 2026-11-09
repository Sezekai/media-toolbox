"""What the tool screens share: several source folders, the main button's wording, and the queue."""
from pathlib import Path

from PySide6.QtWidgets import QCheckBox, QFileDialog

import dialogs
import icons
import settings
import theme
from widgets import ElidedLabel, Page, button, divider, field_label, repolish


def plural(n, one, many=None):
    return f"{n} {one if n == 1 else (many or one + 's')}"


class ToolPage(Page):
    """A tool screen with a list of source folders (C4) and one main button that names its action and count,
    and says "Add … to the queue" while another job runs (B5, B13)."""
    key = "tool"
    folder_noun = "folder"

    def folders_row(self, row, recursive_default=True, add_text="Add folder…"):
        """Row one of the toolbar: Folders, what's added, Add folder…, Include subfolders."""
        saved = settings.load()
        self.roots = [r for r in saved.get(f"{self.key}_folders", []) if isinstance(r, str)]
        row.addWidget(field_label("Folders"))
        self.roots_label = ElidedLabel("", "muted")
        row.addWidget(self.roots_label, 1)
        self.add_btn = button(add_text, icon=icons.icon("folder_plus", theme.TEXT, 16),
                              tip="Add a folder to work on. Add as many as you like.")
        self.add_btn.clicked.connect(self.pick_root)
        row.addWidget(self.add_btn)
        self.recursive = QCheckBox("Include subfolders")
        self.recursive.setChecked(saved.get(f"{self.key}_recursive", recursive_default))
        self.recursive.toggled.connect(lambda on: (settings.save({f"{self.key}_recursive": on}), self.roots_changed()))
        row.addWidget(self.recursive)
        row.addWidget(divider())
        self._show_roots()
        theme.on_change(lambda: self.add_btn.setIcon(icons.icon("folder_plus", theme.TEXT, 16)))

    def _show_roots(self):
        if not self.roots:
            self.roots_label.setText("None yet. Add a folder to start.")
        else:
            names = ", ".join(Path(r).name or r for r in self.roots)
            self.roots_label.setText(f"{plural(len(self.roots), 'folder')}: {names}")
        self.roots_label.setToolTip("\n".join(self.roots))

    def pick_root(self):
        start = self.roots[-1] if self.roots else ""
        chosen = QFileDialog.getExistingDirectory(self, "Add a folder", start)
        if not chosen:
            return
        chosen = str(Path(chosen))
        if any(Path(chosen) == Path(r) for r in self.roots):
            self.app.toast(f"{Path(chosen).name} is already on the list.", "info")
            return
        self.roots.append(chosen)
        self._save_roots()
        self.roots_changed()

    def remove_root(self, root):
        self.roots = [r for r in self.roots if Path(r) != Path(root)]
        self._save_roots()
        self.roots_changed()

    def _save_roots(self):
        settings.save({f"{self.key}_folders": self.roots})
        self._show_roots()

    def roots_changed(self):
        """Folders were added or removed."""

    def missing_roots(self):
        """Folders that are gone (a drive unplugged, or deleted): named, never silently skipped."""
        return [r for r in self.roots if not Path(r).is_dir()]

    def check_roots(self):
        if not self.roots:
            dialogs.info("Add a folder first", "Choose at least one folder with Add folder…", icon_name="folder")
            return False
        gone = self.missing_roots()
        if gone:
            if not dialogs.ask("Some folders can't be found",
                               "These folders aren't there right now. Their drive may be unplugged. "
                               "Carry on with the others?", "Carry on without them", items=gone, icon_name="warn"):
                return False
        return True

    def live_roots(self):
        return [r for r in self.roots if Path(r).is_dir()]

    # ----- the main button -----
    def set_main(self, b, text, queued_text):
        """text: "Convert 12 videos"; queued_text: "12 videos" for "Add 12 videos to the queue"."""
        busy = self.app.queue.busy()
        b.setText(f"Add {queued_text} to the queue" if busy else text)
        b.setToolTip("Another job is running. This one starts when it finishes." if busy else "")

    def queue_changed(self, busy):
        self.refresh_buttons()

    def refresh_buttons(self):
        """Update the main button's text."""
