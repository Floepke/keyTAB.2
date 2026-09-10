"""Main application window for the direct paper editor."""

from __future__ import annotations

import cairocffi as cairo
import sys

from PySide6.QtCore import QEvent, QPointF, QSize, Qt
from PySide6.QtGui import QAction, QActionGroup, QCursor, QKeySequence
from PySide6.QtWidgets import QApplication, QFileDialog, QMainWindow, QMenu, QMessageBox, QScrollArea, QSizePolicy, QToolBar, QVBoxLayout, QWidget

from appdata_manager import get_theme, set_theme
from file_manager import FileManager
from icons import get_qicon
from ui.dialogs.info_dialog import InfoDialog
from ui.dialogs.preferences_dialog import PreferencesDialog
from ui.dialogs.style_dialog import StyleDialog
from ui.ctlz import CtlZ
from ui.paper_canvas import PaperCanvas
from ui.fluidsynth_player import FluidSynthPlayer
from ui.theme import THEMES, apply_theme
from ui.widgets.snap_selector import SnapSizeDock
from settings_manager import get_preferences_manager


class PaperContainer(QWidget):
    """Grow to the viewport or paper size and center the paper in spare space."""

    OVERSCROLL_MARGIN_PX = 48

    def __init__(self, canvas: PaperCanvas) -> None:
        super().__init__()
        self.canvas = canvas
        layout = QVBoxLayout(self)
        layout.setContentsMargins(
            self.OVERSCROLL_MARGIN_PX,
            self.OVERSCROLL_MARGIN_PX,
            self.OVERSCROLL_MARGIN_PX,
            self.OVERSCROLL_MARGIN_PX,
        )
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(canvas)


class PaperView(QScrollArea):
    """Scroll viewport with middle-mouse panning and modifier-wheel zoom."""

    ZOOM_FACTOR = 1.15
    ZOOM_MODIFIERS = Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.MetaModifier

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._paper_canvas: PaperCanvas | None = None
        self._pan_global_position: QPointF | None = None
        self._pan_cursor = None
        self._middle_button_panning = False
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMouseTracking(True)

    def setWidget(self, widget: QWidget) -> None:
        if not isinstance(widget, PaperCanvas):
            raise TypeError("PaperView requires a PaperCanvas")
        previous_widget = self.widget()
        if previous_widget is not None:
            previous_widget.canvas.removeEventFilter(self)
        self._paper_canvas = widget
        widget.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        widget.setMouseTracking(True)
        widget.installEventFilter(self)
        super().setWidget(PaperContainer(widget))
        self.setWidgetResizable(True)

    def paper_canvas(self) -> PaperCanvas | None:
        return self._paper_canvas

    def eventFilter(self, watched, event) -> bool:
        if watched is self._paper_canvas and event.type() == QEvent.Type.MouseButtonPress:
            self.setFocus()
            if event.button() == Qt.MouseButton.MiddleButton:
                self._middle_button_panning = True
                self._set_pan_mode(True, event.globalPosition())
                return True
        elif watched is self._paper_canvas and event.type() == QEvent.Type.MouseMove:
            if self._middle_button_panning:
                self._pan_from_mouse_move(event)
                return True
            self.setFocus(Qt.FocusReason.MouseFocusReason)
        elif watched is self._paper_canvas and event.type() == QEvent.Type.MouseButtonRelease:
            if event.button() == Qt.MouseButton.MiddleButton:
                self._middle_button_panning = False
                self._set_pan_mode(False)
                return True
        elif watched is self._paper_canvas and event.type() == QEvent.Type.Leave:
            self._middle_button_panning = False
            self._set_pan_mode(False)
        return super().eventFilter(watched, event)

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self.window().close()
            event.accept()
            return
        if self._paper_canvas is not None:
            self._paper_canvas.keyPressEvent(event)
            return
        super().keyPressEvent(event)

    def _set_pan_mode(self, enabled: bool, anchor: QPointF | None = None) -> None:
        canvas = self._paper_canvas
        if canvas is None:
            return
        if enabled:
            if self._pan_cursor is None:
                self._pan_cursor = canvas.cursor()
                canvas.setCursor(Qt.CursorShape.BlankCursor)
            if anchor is not None:
                self._pan_global_position = anchor
            return
        if self._pan_cursor is not None:
            canvas.setCursor(self._pan_cursor)
            self._pan_cursor = None
        self._pan_global_position = None

    def _pan_from_mouse_move(self, event) -> None:
        if not event.buttons() & Qt.MouseButton.MiddleButton:
            self._middle_button_panning = False
            self._set_pan_mode(False)
            return
        global_position = event.globalPosition()
        self._set_pan_mode(True, global_position if self._pan_global_position is None else None)
        if self._pan_global_position is None:
            return
        delta = global_position - self._pan_global_position
        self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() + round(delta.x()))
        self.verticalScrollBar().setValue(self.verticalScrollBar().value() + round(delta.y()))
        if delta.x() or delta.y():
            QCursor.setPos(self._pan_global_position.toPoint())

    def wheelEvent(self, event) -> None:
        modifiers = event.modifiers()
        if modifiers & Qt.KeyboardModifier.ShiftModifier:
            delta = event.angleDelta().y() or event.pixelDelta().y()
            if delta:
                self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() - delta)
            event.accept()
            return
        if not modifiers & self.ZOOM_MODIFIERS:
            super().wheelEvent(event)
            return
        delta = event.angleDelta().y() or event.pixelDelta().y()
        if not delta:
            event.accept()
            return
        steps = max(1, round(abs(delta) / 120.0)) * (1 if delta > 0 else -1)
        canvas = self._paper_canvas
        if canvas is None:
            event.ignore()
            return
        position = event.position()
        old_pixels_per_mm = canvas.pixels_per_mm
        document_x_mm = (self.horizontalScrollBar().value() + position.x() - canvas.x()) / old_pixels_per_mm
        document_y_mm = (self.verticalScrollBar().value() + position.y() - canvas.y()) / old_pixels_per_mm
        canvas.set_zoom(canvas.zoom * self.ZOOM_FACTOR ** steps)
        new_pixels_per_mm = canvas.pixels_per_mm
        self.horizontalScrollBar().setValue(round(document_x_mm * new_pixels_per_mm + canvas.x() - position.x()))
        self.verticalScrollBar().setValue(round(document_y_mm * new_pixels_per_mm + canvas.y() - position.y()))
        event.accept()


class MainWindow(QMainWindow):
    """Hosts the document and the future direct paper editing surface."""

    def __init__(self) -> None:
        super().__init__()
        self.file_manager = FileManager(self)
        restored_source = self.file_manager.restore_startup_document()
        self.document = self.file_manager.document
        self._ctlz = CtlZ(self.document, max_steps=64)

        self.resize(1200, 800)
        self.showMaximized()
        self.paper_canvas = PaperCanvas(self.document)
        self._player = FluidSynthPlayer(self)
        self._player.initialize()
        self.paper_canvas.note_audition_requested.connect(self._player.audition)
        self.paper_canvas.set_document_change_callback(self._record_document_change)
        self.paper_canvas.set_history_callbacks(self.undo, self.redo)
        self.paper_view = PaperView()
        self.paper_view.setWidget(self.paper_canvas)
        self.paper_view.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter)
        self.setCentralWidget(self.paper_view)
        self._create_menus()
        self._create_toolbar()
        self._create_snap_dock()
        self._set_theme(get_theme(), persist=False)
        self.statusBar().showMessage(
            "Last document restored" if restored_source == "last_opened" else "Recovery session restored" if restored_source == "session" else "New score"
        )
        self._update_title()

    def _create_menus(self) -> None:
        menu_bar = self.menuBar()
        if sys.platform == "darwin":
            menu_bar.setNativeMenuBar(False)

        file_menu = menu_bar.addMenu("&File")
        new_action = QAction("&New", self)
        new_action.setShortcut("Ctrl+N")
        new_action.triggered.connect(self.new_document)
        file_menu.addAction(new_action)
        test_notes_action = file_menu.addAction("Load &Test Notes")
        test_notes_action.triggered.connect(self.load_test_notes)
        load_midi_action = file_menu.addAction("Load &MIDI...")
        load_midi_action.triggered.connect(self.load_midi)
        file_menu.addSeparator()

        self.open_action = file_menu.addAction("&Open...")
        self.open_action.setShortcut("Ctrl+O")
        self.open_action.triggered.connect(self.open_document)
        self.recent_files_menu = file_menu.addMenu("Recent Files")
        self.recent_files_menu.aboutToShow.connect(self._refresh_recent_files_menu)
        self.save_action = file_menu.addAction("&Save")
        self.save_action.setShortcut("Ctrl+S")
        self.save_action.triggered.connect(self.save_document)
        self.save_as_action = file_menu.addAction("Save &As...")
        self.save_as_action.setShortcut("Ctrl+Shift+S")
        self.save_as_action.triggered.connect(self.save_document_as)
        file_menu.addSeparator()
        export_pdf_action = file_menu.addAction("Export &PDF...")
        export_pdf_action.setShortcut("Ctrl+E")
        export_pdf_action.triggered.connect(self.export_pdf)

        edit_menu = self.menuBar().addMenu("&Edit")
        score_info_action = edit_menu.addAction("Score &Info...")
        score_info_action.triggered.connect(self.edit_score_info)
        style_action = edit_menu.addAction("&Style...")
        style_action.triggered.connect(self.edit_style)
        preferences_action = edit_menu.addAction("&Preferences...")
        preferences_action.triggered.connect(self.edit_preferences)
        edit_menu.addSeparator()
        cut_action = edit_menu.addAction("Cu&t")
        cut_action.setShortcut(QKeySequence.StandardKey.Cut)
        cut_action.triggered.connect(self.paper_canvas.cut_selection)
        copy_action = edit_menu.addAction("&Copy")
        copy_action.setShortcut(QKeySequence.StandardKey.Copy)
        copy_action.triggered.connect(self.paper_canvas.copy_selection)
        paste_action = edit_menu.addAction("&Paste")
        paste_action.setShortcut(QKeySequence.StandardKey.Paste)
        paste_action.triggered.connect(self.paper_canvas.paste_selection)
        edit_menu.addSeparator()
        self.undo_action = edit_menu.addAction("&Undo")
        self.undo_action.setShortcut(QKeySequence.StandardKey.Undo)
        self.undo_action.triggered.connect(self.undo)
        self.redo_action = edit_menu.addAction("&Redo")
        self.redo_action.setShortcut("Ctrl+Shift+Z")
        self.redo_action.triggered.connect(self.redo)
        self.undo_action.setEnabled(False)
        self.redo_action.setEnabled(False)

        view_menu = self.menuBar().addMenu("&View")
        self.light_theme_action = QAction("Light Theme", self)
        self.light_theme_action.setCheckable(True)
        self.light_theme_action.triggered.connect(lambda: self._set_theme("light"))
        view_menu.addAction(self.light_theme_action)
        self.dark_theme_action = QAction("Dark Theme", self)
        self.dark_theme_action.setCheckable(True)
        self.dark_theme_action.triggered.connect(lambda: self._set_theme("dark"))
        view_menu.addAction(self.dark_theme_action)
        theme_group = QActionGroup(view_menu)
        theme_group.setExclusive(True)
        theme_group.addAction(self.light_theme_action)
        theme_group.addAction(self.dark_theme_action)

        view_menu.addSeparator()
        self.snap_band_action = QAction("Snap Band on/off", self)
        self.snap_band_action.setCheckable(True)
        self.snap_band_action.setChecked(self.document.layout.grid_band_visible)
        self.snap_band_action.toggled.connect(self.paper_canvas.set_snap_band_visible)
        view_menu.addAction(self.snap_band_action)

        help_menu = self.menuBar().addMenu("&Help")
        about_action = help_menu.addAction("&About keyTAB 2")
        about_action.triggered.connect(self._show_about)

    def _create_toolbar(self) -> None:
        toolbar = QToolBar("Note Input", self)
        toolbar.setObjectName("noteInputToolbar")
        toolbar.setMovable(False)
        toolbar.setIconSize(QSize(28, 28))

        self.left_note_input_action = QAction(get_qicon("note_left", (28, 28)), "", self)
        self.left_note_input_action.setObjectName("leftNoteInputAction")
        self.left_note_input_action.setToolTip("Left Note Input")
        self.left_note_input_action.setShortcut(",")
        self.left_note_input_action.setCheckable(True)
        self.left_note_input_action.setChecked(True)
        self.left_note_input_action.triggered.connect(lambda: self.paper_canvas.select_note_hand("left"))
        toolbar.addAction(self.left_note_input_action)

        self.right_note_input_action = QAction(get_qicon("note_right", (28, 28)), "", self)
        self.right_note_input_action.setObjectName("rightNoteInputAction")
        self.right_note_input_action.setToolTip("Right Note Input")
        self.right_note_input_action.setShortcut(".")
        self.right_note_input_action.setCheckable(True)
        self.right_note_input_action.triggered.connect(lambda: self.paper_canvas.select_note_hand("right"))
        toolbar.addAction(self.right_note_input_action)

        self.system_break_action = QAction(get_qicon("line_break", (28, 28)), "", self)
        self.system_break_action.setObjectName("systemBreakAction")
        self.system_break_action.setToolTip("Insert or remove a system break")
        self.system_break_action.setCheckable(True)
        self.system_break_action.triggered.connect(self.paper_canvas.select_system_break_mode)
        toolbar.addAction(self.system_break_action)

        self.time_signature_action = QAction(get_qicon("time_signature", (28, 28)), "", self)
        self.time_signature_action.setObjectName("timeSignatureAction")
        self.time_signature_action.setToolTip("Edit time signatures and grid lines")
        self.time_signature_action.setCheckable(True)
        self.time_signature_action.triggered.connect(self.paper_canvas.select_time_signature_mode)
        toolbar.addAction(self.time_signature_action)

        self.left_slur_action = QAction(get_qicon("mirror:slur", (28, 28)), "", self)
        self.left_slur_action.setObjectName("leftSlurAction")
        self.left_slur_action.setToolTip("Insert and edit left-hand slurs")
        self.left_slur_action.setCheckable(True)
        self.left_slur_action.triggered.connect(lambda: self.paper_canvas.select_slur_mode("left"))
        toolbar.addAction(self.left_slur_action)

        self.right_slur_action = QAction(get_qicon("slur", (28, 28)), "", self)
        self.right_slur_action.setObjectName("rightSlurAction")
        self.right_slur_action.setToolTip("Insert and edit right-hand slurs")
        self.right_slur_action.setCheckable(True)
        self.right_slur_action.triggered.connect(lambda: self.paper_canvas.select_slur_mode("right"))
        toolbar.addAction(self.right_slur_action)

        note_hand_group = QActionGroup(toolbar)
        note_hand_group.setExclusive(True)
        note_hand_group.addAction(self.left_note_input_action)
        note_hand_group.addAction(self.right_note_input_action)
        note_hand_group.addAction(self.system_break_action)
        note_hand_group.addAction(self.time_signature_action)
        note_hand_group.addAction(self.left_slur_action)
        note_hand_group.addAction(self.right_slur_action)
        self._note_hand_group = note_hand_group
        self._note_hand_group.triggered.connect(lambda _action: self._refresh_toolbar_icons())
        self.paper_canvas.note_hand_changed.connect(self._sync_note_input_toolbar)
        toolbar.addSeparator()

        self.previous_page_action = QAction(get_qicon("previous", (28, 28)), "", self)
        self.previous_page_action.setToolTip("Previous page")
        self.previous_page_action.triggered.connect(lambda: self._change_page(-1))
        toolbar.addAction(self.previous_page_action)
        self.next_page_action = QAction(get_qicon("next", (28, 28)), "", self)
        self.next_page_action.setToolTip("Next page")
        self.next_page_action.triggered.connect(lambda: self._change_page(1))
        toolbar.addAction(self.next_page_action)

        spacer = QWidget(toolbar)
        spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        toolbar.addWidget(spacer)

        self.play_action = QAction(get_qicon("play", (28, 28)), "", self)
        self.play_action.setToolTip("Play score")
        self.play_action.triggered.connect(self._play_score)
        toolbar.addAction(self.play_action)
        self.stop_action = QAction(get_qicon("stop", (28, 28)), "", self)
        self.stop_action.setToolTip("Stop playback")
        self.stop_action.setEnabled(False)
        self.stop_action.triggered.connect(self._player.stop)
        toolbar.addAction(self.stop_action)
        self._player.playback_started.connect(self._set_playback_actions)
        self._player.playback_finished.connect(self._set_playback_actions)
        self._player.playback_failed.connect(self._show_playback_error)

        self.addToolBar(toolbar)

    def _create_snap_dock(self) -> None:
        self.snap_dock = SnapSizeDock(self)
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, self.snap_dock)
        self.snap_dock.selector.snapChanged.connect(self._on_snap_changed)
        self._on_snap_changed(
            self.snap_dock.selector.get_snap_base(),
            self.snap_dock.selector.get_snap_divide(),
        )

    def _on_snap_changed(self, _base: int, _divide: int) -> None:
        self.paper_canvas.set_input_snap_ticks(self.snap_dock.selector.get_snap_size())

    def new_document(self) -> None:
        if not self._confirm_document_replacement("creating a new score"):
            return
        self.document = self.file_manager.new()
        self.paper_canvas.set_document(self.document)
        self.snap_band_action.setChecked(self.document.layout.grid_band_visible)
        self._reset_undo_history()
        self.statusBar().showMessage("New document")
        self._update_title()

    def load_test_notes(self) -> None:
        if not self._confirm_document_replacement("loading test notes"):
            return
        self.document = self.file_manager.new_test_score()
        self.paper_canvas.set_document(self.document)
        self.snap_band_action.setChecked(self.document.layout.grid_band_visible)
        self._reset_undo_history()
        self.statusBar().showMessage("Test notes loaded")
        self._update_title()

    def load_midi(self) -> None:
        if not self._confirm_document_replacement("loading MIDI"):
            return
        if self.file_manager.load_midi():
            self.document = self.file_manager.document
            self.paper_canvas.set_document(self.document)
            self.snap_band_action.setChecked(self.document.layout.grid_band_visible)
            self._reset_undo_history()
            self.statusBar().showMessage("MIDI loaded", 3000)
            self._update_title()

    def open_document(self) -> None:
        if not self._confirm_document_replacement("opening another score"):
            return
        if self.file_manager.load():
            self._finish_document_open()

    def _refresh_recent_files_menu(self) -> None:
        self.recent_files_menu.clear()
        paths = self.file_manager.recent_paths()
        if not paths:
            empty_action = self.recent_files_menu.addAction("No Recent Files")
            empty_action.setEnabled(False)
            return
        for path in paths:
            action = self.recent_files_menu.addAction(path.name)
            action.setToolTip(str(path))
            action.setEnabled(path.is_file())
            action.triggered.connect(lambda _checked=False, recent_path=path: self.open_recent_document(recent_path))
        self.recent_files_menu.addSeparator()
        clear_action = self.recent_files_menu.addAction("Clear Recent Files")
        clear_action.triggered.connect(self._clear_recent_files)

    def _clear_recent_files(self) -> None:
        self.file_manager.clear_recent_paths()
        self.statusBar().showMessage("Recent files cleared", 3000)

    def open_recent_document(self, path) -> None:
        if not path.is_file() or not self._confirm_document_replacement("opening another score"):
            return
        if self.file_manager.open_path(path):
            self._finish_document_open()

    def _finish_document_open(self) -> None:
        self.document = self.file_manager.document
        self.paper_canvas.set_document(self.document)
        self.snap_band_action.setChecked(self.document.layout.grid_band_visible)
        self._reset_undo_history()
        self.statusBar().showMessage("Document opened", 3000)
        self._update_title()

    def save_document(self) -> None:
        if self.file_manager.save():
            self.statusBar().showMessage("Document saved", 3000)
            self._update_title()

    def save_document_as(self) -> None:
        if self.file_manager.save_as():
            self.statusBar().showMessage("Document saved", 3000)
            self._update_title()

    def export_pdf(self) -> None:
        suggested_name = f"{self.document.score_info.title.strip() or 'Untitled'}.pdf"
        path, _ = QFileDialog.getSaveFileName(self, "Export PDF", suggested_name, "PDF files (*.pdf)")
        if not path:
            return
        try:
            self.paper_canvas.export_pdf(path)
        except cairo.Error as error:
            QMessageBox.critical(self, "Export PDF failed", str(error))
            return
        self.statusBar().showMessage("PDF exported", 3000)

    def edit_score_info(self) -> None:
        dialog = InfoDialog(self.document, self)
        if dialog.exec() != dialog.DialogCode.Accepted:
            return
        dialog.apply_to_document()
        self._record_document_change()
        self._update_title()
        self.statusBar().showMessage("Score info updated", 3000)

    def edit_style(self) -> None:
        dialog = StyleDialog(self.document.layout, self)
        if dialog.exec() != dialog.DialogCode.Accepted:
            return
        self.document.layout = dialog.value()
        for page in self.document.pages:
            page.width_mm = self.document.layout.page_width_mm
            page.height_mm = self.document.layout.page_height_mm
        self.paper_canvas.repaginate_document()
        self._record_document_change()
        self.snap_band_action.setChecked(self.document.layout.grid_band_visible)
        self.statusBar().showMessage("Style updated", 3000)

    def edit_preferences(self) -> None:
        preferences = get_preferences_manager()
        dialog = PreferencesDialog(bool(preferences.get("save_on_exit", False)), self)
        if dialog.exec() != dialog.DialogCode.Accepted:
            return
        preferences.set("save_on_exit", dialog.save_on_exit_enabled())
        preferences.save()

    def _change_page(self, offset: int) -> None:
        self.paper_canvas.set_page_index((self.paper_canvas.page_index + offset) % self.paper_canvas.page_count)
        self.statusBar().showMessage(
            f"Page {self.paper_canvas.page_index + 1} of {self.paper_canvas.page_count}",
            3000,
        )

    def _update_title(self) -> None:
        name = self.file_manager.path.name if self.file_manager.path else "Untitled"
        self.setWindowTitle(f"keyTAB 2 - {name}")

    def _confirm_document_replacement(self, action: str) -> bool:
        choice = QMessageBox.warning(
            self,
            "Save keyTAB 2 score",
            f"Do you want to save changes before {action}?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if choice == QMessageBox.StandardButton.Yes:
            return self.file_manager.save()
        return choice == QMessageBox.StandardButton.No

    def _record_document_change(self) -> None:
        self._ctlz.add_ctlz(self.document)
        self._update_undo_actions()

    def _reset_undo_history(self) -> None:
        self._ctlz.reset_ctlz(self.document)
        self._update_undo_actions()

    def _update_undo_actions(self) -> None:
        self.undo_action.setEnabled(self._ctlz.can_undo)
        self.redo_action.setEnabled(self._ctlz.can_redo)

    def _restore_history_document(self, document) -> None:
        self.document = document
        self.file_manager.document = document
        self.paper_canvas.set_document(document)
        self.snap_band_action.blockSignals(True)
        self.snap_band_action.setChecked(document.layout.grid_band_visible)
        self.snap_band_action.blockSignals(False)
        self._update_undo_actions()

    def undo(self) -> None:
        document = self._ctlz.undo()
        if document is not None:
            self._restore_history_document(document)

    def redo(self) -> None:
        document = self._ctlz.redo()
        if document is not None:
            self._restore_history_document(document)

    def _set_theme(self, theme: str, *, persist: bool = True) -> None:
        self._theme = theme
        apply_theme(QApplication.instance(), theme)
        self._refresh_toolbar_icons()
        self.snap_dock.selector.refresh_icons(THEMES[theme]["text"])
        self.light_theme_action.setChecked(theme == "light")
        self.dark_theme_action.setChecked(theme == "dark")
        if persist:
            set_theme(theme)

    def _refresh_toolbar_icons(self) -> None:
        colors = THEMES[self._theme]
        for action, icon_name in (
            (self.left_note_input_action, "note_left"),
            (self.right_note_input_action, "note_right"),
            (self.system_break_action, "line_break"),
            (self.time_signature_action, "time_signature"),
            (self.left_slur_action, "mirror:slur"),
            (self.right_slur_action, "slur"),
            (self.previous_page_action, "previous"),
            (self.next_page_action, "next"),
            (self.play_action, "play"),
            (self.stop_action, "stop"),
        ):
            tint = colors["highlight"] if action.isCheckable() and action.isChecked() else colors["text"]
            action.setIcon(get_qicon(icon_name, (28, 28), tint))

    def _play_score(self) -> None:
        self._player.play(self.document)

    def _set_playback_actions(self) -> None:
        playing = self._player.is_playing
        self.play_action.setEnabled(not playing)
        self.stop_action.setEnabled(playing)

    def _show_playback_error(self, message: str) -> None:
        self._set_playback_actions()
        QMessageBox.warning(self, "Playback unavailable", message)

    def _sync_note_input_toolbar(self, hand: str) -> None:
        action = self.left_note_input_action if hand == "left" else self.right_note_input_action
        action.setChecked(True)
        self._refresh_toolbar_icons()

    def _show_about(self) -> None:
        QMessageBox.about(
            self,
            "About keyTAB 2",
            "keyTAB 2\n\nA direct paper editor for keyTAB scores.",
        )

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self.close()
            event.accept()
            return
        super().keyPressEvent(event)

    def closeEvent(self, event) -> None:
        if self.file_manager.path is not None and bool(get_preferences_manager().get("save_on_exit", False)):
            if not self.file_manager.save():
                event.ignore()
                return
            self.file_manager.save_session()
            self._player.shutdown()
            event.accept()
            return
        choice = QMessageBox.warning(
            self,
            "Close keyTAB 2",
            "Do you want to save changes before closing?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if choice == QMessageBox.StandardButton.Yes:
            if self.file_manager.save():
                self.file_manager.save_session()
                self._player.shutdown()
                event.accept()
            else:
                event.ignore()
            return
        if choice == QMessageBox.StandardButton.No:
            self.file_manager.save_session()
            self._player.shutdown()
            event.accept()
            return
        event.ignore()