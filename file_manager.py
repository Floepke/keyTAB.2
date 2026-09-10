"""Native keyTAB2 document lifecycle."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import QFileDialog, QMessageBox, QWidget

from appdata_manager import get_appdata_manager
from keytab2_model import KeyTab2Document
from midi_importer import MidiImportError, load_midi
from utils.CONSTANT import UTILS_SAVE_DIR


class FileManager:
    """Create, open, and save native .keytab2 score documents."""

    EXTENSION = ".keytab2"
    FILE_FILTER = "keyTAB2 Score (*.keytab2)"
    MIDI_FILE_FILTER = "MIDI files (*.mid *.midi)"
    RECENT_FILES_LIMIT = 20
    SESSION_PATH = UTILS_SAVE_DIR / "session.keytab2"

    def __init__(self, parent: QWidget | None = None) -> None:
        self.parent = parent
        self.document = KeyTab2Document.new()
        self.path: Path | None = None
        self._last_directory = Path.home()

    def new(self) -> KeyTab2Document:
        self.document = KeyTab2Document.new()
        self.path = None
        return self.document

    def new_test_score(self) -> KeyTab2Document:
        """Create an unsaved score containing representative note geometry."""
        self.document = KeyTab2Document.with_test_notes()
        self.path = None
        return self.document

    def load(self) -> bool:
        filename, _ = QFileDialog.getOpenFileName(
            self.parent, "Open keyTAB2 score", str(self._last_directory), self.FILE_FILTER
        )
        if not filename:
            return False
        return self.open_path(filename)

    def load_midi(self) -> bool:
        filename, _ = QFileDialog.getOpenFileName(
            self.parent, "Load MIDI", str(self._last_directory), self.MIDI_FILE_FILTER
        )
        if not filename:
            return False
        try:
            self.document = load_midi(filename)
        except (OSError, MidiImportError, ValueError) as error:
            self._show_error("MIDI import failed", f"Could not import {Path(filename).name}.\n\n{error}")
            return False
        self.path = None
        self._last_directory = Path(filename).parent
        return True

    def open_path(self, path: str | Path) -> bool:
        target = self._validate_path(path)
        try:
            self.document = KeyTab2Document.load(target)
        except (OSError, ValueError) as error:
            self._show_error("Open failed", f"Could not open {target.name}.\n\n{error}")
            return False
        self.path = target
        self._last_directory = target.parent
        self._remember_path(target, recent=True)
        return True

    def restore_startup_document(self) -> str | None:
        """Restore the last opened document, or the session recovery backup."""
        last_opened_file = get_appdata_manager().get("last_opened_file", "")
        last_path = Path(str(last_opened_file)).expanduser() if last_opened_file else None
        if last_path is not None and last_path.is_file() and self.open_path(last_path):
            return "last_opened"
        if not self.SESSION_PATH.is_file():
            return None
        try:
            self.document = KeyTab2Document.load(self.SESSION_PATH)
        except (OSError, ValueError):
            return None
        self.path = None
        self._last_directory = self.SESSION_PATH.parent
        return "session"

    def save_session(self) -> bool:
        """Write a recovery copy of the active document without changing its path."""
        try:
            self.SESSION_PATH.parent.mkdir(parents=True, exist_ok=True)
            self.document.save(self.SESSION_PATH)
        except (OSError, ValueError) as error:
            self._show_error("Session backup failed", f"Could not save the recovery session.\n\n{error}")
            return False
        return True

    def save(self) -> bool:
        if self.path is None:
            return self.save_as()
        return self.save_to_path(self.path)

    def save_as(self) -> bool:
        suggested_path = self._last_directory / self._suggested_filename()
        filename, _ = QFileDialog.getSaveFileName(
            self.parent, "Save keyTAB2 score", str(suggested_path), self.FILE_FILTER
        )
        if not filename:
            return False
        return self.save_to_path(filename)

    def save_to_path(self, path: str | Path) -> bool:
        try:
            target = self._with_extension(path)
            target.parent.mkdir(parents=True, exist_ok=True)
            self.document.save(target)
        except (OSError, ValueError) as error:
            self._show_error("Save failed", f"Could not save the score.\n\n{error}")
            return False
        self.path = target
        self._last_directory = target.parent
        self._remember_path(target)
        return True

    def _suggested_filename(self) -> str:
        title = str(self.document.score_info.title or "").strip()
        safe_title = "".join("_" if char in '/\\:*?"<>|' else char for char in title)
        return f"{safe_title or 'Untitled'}{self.EXTENSION}"

    def _validate_path(self, path: str | Path) -> Path:
        target = Path(path).expanduser()
        if target.suffix.lower() != self.EXTENSION:
            raise ValueError(f"Only {self.EXTENSION} files can be opened.")
        return target

    def _with_extension(self, path: str | Path) -> Path:
        target = Path(path).expanduser()
        if target.suffix.lower() != self.EXTENSION:
            target = target.with_suffix(self.EXTENSION)
        return target

    def recent_paths(self) -> tuple[Path, ...]:
        """Return persisted document paths in most-recent-first order."""
        recent_files = get_appdata_manager().get("recent_files", [])
        if not isinstance(recent_files, list):
            return ()
        return tuple(Path(str(path)).expanduser() for path in recent_files if str(path).strip())

    def clear_recent_paths(self) -> None:
        """Remove all persisted recent document paths."""
        app_data = get_appdata_manager()
        app_data.set("recent_files", [])
        app_data.save()

    def _remember_path(self, path: Path, *, recent: bool = False) -> None:
        app_data = get_appdata_manager()
        app_data.set("last_file_dialog_dir", str(path.parent))
        app_data.set("last_opened_file", str(path))
        if recent:
            recent_files = app_data.get("recent_files", [])
            if not isinstance(recent_files, list):
                recent_files = []
            paths = [str(candidate) for candidate in recent_files if str(candidate).strip() and str(candidate) != str(path)]
            app_data.set("recent_files", [str(path), *paths][:self.RECENT_FILES_LIMIT])
        app_data.save()

    def _show_error(self, title: str, message: str) -> None:
        if self.parent is not None:
            QMessageBox.critical(self.parent, title, message)