"""Dialogs for configuring document staves and their visible pitch ranges."""

from __future__ import annotations

import cairocffi as cairo

from PySide6.QtCore import QPointF, Qt, Signal
from PySide6.QtGui import QColor, QIcon, QImage, QMouseEvent, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from keytab2_model import Stave
from keytab2_model.document import BLACK_PITCH_CLASSES, PIANO_HIGH_MIDI_PITCH, PIANO_LOW_MIDI_PITCH


def _pitch_name(pitch: int) -> str:
    names = ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")
    return f"{names[pitch % 12]}{pitch // 12 - 1}"


class StaveRangeVisualizer(QWidget):
    """Cairo-drawn vertical keyboard stave with draggable low/high range handles."""

    rangeChanged = Signal(int, int)

    HANDLE_RADIUS_PX = 9
    LEFT_MARGIN_PX = 24
    RIGHT_MARGIN_PX = 24
    TOP_MARGIN_PX = 48
    BOTTOM_MARGIN_PX = 48

    def __init__(self, low_pitch: int, high_pitch: int, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._low_pitch = int(low_pitch)
        self._high_pitch = int(high_pitch)
        self._active_handle: str | None = None
        self.setMinimumSize(420, 180)
        self.setMouseTracking(True)

    @property
    def pitch_range(self) -> tuple[int, int]:
        return self._low_pitch, self._high_pitch

    def _x_for_pitch(self, pitch: int) -> float:
        usable_width = max(1, self.width() - self.LEFT_MARGIN_PX - self.RIGHT_MARGIN_PX)
        return self.LEFT_MARGIN_PX + (pitch - PIANO_LOW_MIDI_PITCH) * usable_width / (PIANO_HIGH_MIDI_PITCH - PIANO_LOW_MIDI_PITCH)

    def _pitch_for_x(self, x_px: float) -> int:
        usable_width = max(1, self.width() - self.LEFT_MARGIN_PX - self.RIGHT_MARGIN_PX)
        value = PIANO_LOW_MIDI_PITCH + round((x_px - self.LEFT_MARGIN_PX) * (PIANO_HIGH_MIDI_PITCH - PIANO_LOW_MIDI_PITCH) / usable_width)
        return max(PIANO_LOW_MIDI_PITCH, min(PIANO_HIGH_MIDI_PITCH, value))

    def paintEvent(self, event) -> None:
        del event
        image = QImage(self.size(), QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(QColor("#f8f6f0"))
        surface = cairo.ImageSurface.create_for_data(image.bits(), cairo.FORMAT_ARGB32, image.width(), image.height(), image.bytesPerLine())
        context = cairo.Context(surface)
        context.set_antialias(cairo.ANTIALIAS_BEST)
        stave_top = self.TOP_MARGIN_PX
        stave_bottom = self.height() - self.BOTTOM_MARGIN_PX
        low_x = self._x_for_pitch(self._low_pitch)
        high_x = self._x_for_pitch(self._high_pitch)

        context.set_source_rgb(0.12, 0.16, 0.17)
        context.set_line_width(1.0)
        for pitch in range(PIANO_LOW_MIDI_PITCH, PIANO_HIGH_MIDI_PITCH + 1):
            if pitch % 12 not in BLACK_PITCH_CLASSES:
                continue
            x_px = self._x_for_pitch(pitch)
            key_number = pitch - 20
            is_three_line_group = pitch == PIANO_LOW_MIDI_PITCH + 1 or (key_number - 1) % 12 in {1, 9, 11}
            context.set_line_width(2.0 if is_three_line_group else 1.0)
            context.set_dash((4.0, 3.0) if pitch in (61, 63) else ())
            context.move_to(x_px, stave_top)
            context.line_to(x_px, stave_bottom)
            context.stroke()
        context.set_dash(())

        context.set_source_rgba(0.09, 0.41, 0.67, 0.18)
        context.rectangle(low_x, stave_top - 12.0, high_x - low_x, stave_bottom - stave_top + 24.0)
        context.fill()
        context.set_source_rgb(0.09, 0.41, 0.67)
        context.set_line_width(2.0)
        context.move_to(low_x, (stave_top + stave_bottom) * 0.5)
        context.line_to(high_x, (stave_top + stave_bottom) * 0.5)
        context.stroke()

        for handle_x, label in ((low_x, _pitch_name(self._low_pitch)), (high_x, _pitch_name(self._high_pitch))):
            context.set_source_rgb(0.09, 0.41, 0.67)
            context.arc(handle_x, (stave_top + stave_bottom) * 0.5, self.HANDLE_RADIUS_PX, 0.0, 6.283185307179586)
            context.fill()
            context.set_source_rgb(1.0, 1.0, 1.0)
            context.set_line_width(2.0)
            context.move_to(handle_x, (stave_top + stave_bottom) * 0.5 - 4.0)
            context.line_to(handle_x, (stave_top + stave_bottom) * 0.5 + 4.0)
            context.stroke()
            context.set_source_rgb(0.12, 0.16, 0.17)
            context.select_font_face("Sans", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_NORMAL)
            context.set_font_size(12.0)
            context.move_to(handle_x - 10.0, stave_bottom + 28.0)
            context.show_text(label)

        surface.flush()
        painter = QPainter(self)
        painter.drawImage(0, 0, image)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        point = event.position()
        handle_y = (self.TOP_MARGIN_PX + self.height() - self.BOTTOM_MARGIN_PX) * 0.5
        if abs(point.y() - handle_y) > self.HANDLE_RADIUS_PX * 2:
            return
        low_distance = abs(point.x() - self._x_for_pitch(self._low_pitch))
        high_distance = abs(point.x() - self._x_for_pitch(self._high_pitch))
        self._active_handle = "low" if low_distance <= high_distance else "high"
        self._update_active_handle(point)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._active_handle is not None:
            self._update_active_handle(event.position())

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        del event
        self._active_handle = None

    def _update_active_handle(self, point: QPointF) -> None:
        pitch = self._pitch_for_x(point.x())
        if self._active_handle == "low":
            pitch = min(pitch, self._high_pitch - 1)
            if pitch == self._low_pitch:
                return
            self._low_pitch = pitch
        else:
            pitch = max(pitch, self._low_pitch + 1)
            if pitch == self._high_pitch:
                return
            self._high_pitch = pitch
        self.rangeChanged.emit(self._low_pitch, self._high_pitch)
        self.update()


class StaveRangeDialog(QDialog):
    """Edit a stave's MIDI pitch range with a direct visual control."""

    def __init__(self, stave: Stave, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"Stave Range - {stave.name}")
        self.setMinimumWidth(280)
        self._range_visualizer = StaveRangeVisualizer(*stave.pitch_range, self)
        self._range_label = QLabel(self)
        self._range_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._range_visualizer.rangeChanged.connect(self._update_range_label)
        self._update_range_label(*stave.pitch_range)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Drag the handles to set the displayed pitch range.", self))
        layout.addWidget(self._range_visualizer)
        layout.addWidget(self._range_label)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel, self)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    @property
    def pitch_range(self) -> list[int]:
        return list(self._range_visualizer.pitch_range)

    def _update_range_label(self, low_pitch: int, high_pitch: int) -> None:
        self._range_label.setText(f"{_pitch_name(low_pitch)} to {_pitch_name(high_pitch)}")


class StavesDialog(QDialog):
    """Configure stave membership and order for every system in a document."""

    def __init__(self, staves: list[Stave], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Staves")
        self.setMinimumSize(420, 340)
        self._staves = [
            Stave(name=stave.name, pitch_range=list(stave.pitch_range), scale=stave.scale, id=stave.id)
            for stave in staves
        ]
        self._list = QListWidget(self)
        self._list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._list.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self._list.setDefaultDropAction(Qt.DropAction.MoveAction)
        self._list.currentRowChanged.connect(self._update_controls)

        self._add_button = self._tool_button("add", "Add stave", self._add_stave)
        self._remove_button = self._tool_button("remove", "Remove selected stave", self._remove_stave)
        self._name_button = QPushButton("Set Stave Name", self)
        self._name_button.clicked.connect(self._edit_name)
        self._range_button = QPushButton("Set Stave Range", self)
        self._range_button.clicked.connect(self._edit_range)
        self._scale_button = QPushButton("Set Stave Scale", self)
        self._scale_button.clicked.connect(self._edit_scale)

        list_controls = QHBoxLayout()
        list_controls.addWidget(self._list, 1)
        buttons = QVBoxLayout()
        buttons.addWidget(self._add_button)
        buttons.addWidget(self._remove_button)
        buttons.addStretch(1)
        list_controls.addLayout(buttons)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Drag staves to change their order. Changes apply to every system.", self))
        layout.addLayout(list_controls)
        layout.addWidget(self._name_button, alignment=Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(self._range_button, alignment=Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(self._scale_button, alignment=Qt.AlignmentFlag.AlignLeft)
        dialog_buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel, self)
        dialog_buttons.accepted.connect(self.accept)
        dialog_buttons.rejected.connect(self.reject)
        layout.addWidget(dialog_buttons)
        self._refresh_list()

    @property
    def staves(self) -> list[Stave]:
        self._sync_order_from_list()
        return self._staves

    def _tool_button(self, action: str, tooltip: str, callback) -> QToolButton:
        button = QToolButton(self)
        button.setIcon(self._tool_icon(action))
        button.setToolTip(tooltip)
        button.clicked.connect(callback)
        return button

    def _tool_icon(self, action: str) -> QIcon:
        pixmap = QPixmap(18, 18)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(self.palette().buttonText(), 2.0, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        if action == "add":
            painter.drawLine(4, 9, 14, 9)
            painter.drawLine(9, 4, 9, 14)
        else:
            painter.drawLine(5, 6, 13, 6)
            painter.drawLine(7, 4, 11, 4)
            painter.drawLine(6, 8, 7, 14)
            painter.drawLine(7, 14, 11, 14)
            painter.drawLine(11, 14, 12, 8)
        painter.end()
        return QIcon(pixmap)

    def _refresh_list(self, selected_row: int = 0) -> None:
        self._list.clear()
        for stave in self._staves:
            item = QListWidgetItem(f"{stave.name}    {_pitch_name(stave.pitch_range[0])} - {_pitch_name(stave.pitch_range[1])}")
            item.setData(Qt.ItemDataRole.UserRole, stave)
            self._list.addItem(item)
        self._list.setCurrentRow(min(selected_row, len(self._staves) - 1))
        self._update_controls()

    def _sync_order_from_list(self) -> None:
        self._staves = [self._list.item(index).data(Qt.ItemDataRole.UserRole) for index in range(self._list.count())]

    def _selected_stave(self) -> Stave | None:
        item = self._list.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item is not None else None

    def _add_stave(self) -> None:
        name, accepted = QInputDialog.getText(self, "Add Stave", "Stave name:", text=f"Stave {len(self._staves) + 1}")
        if accepted and name.strip():
            self._sync_order_from_list()
            self._staves.append(Stave(name=name.strip()))
            self._refresh_list(len(self._staves) - 1)

    def _remove_stave(self) -> None:
        if len(self._staves) <= 1:
            return
        row = self._list.currentRow()
        if row >= 0:
            self._list.takeItem(row)
            self._sync_order_from_list()
            self._refresh_list(row)

    def _edit_range(self) -> None:
        stave = self._selected_stave()
        if stave is None:
            return
        dialog = StaveRangeDialog(stave, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            stave.pitch_range = dialog.pitch_range
            self._refresh_list(self._list.currentRow())

    def _edit_name(self) -> None:
        stave = self._selected_stave()
        if stave is None:
            return
        name, accepted = QInputDialog.getText(self, "Set Stave Name", "Stave name:", text=stave.name)
        if accepted and name.strip():
            stave.name = name.strip()
            self._refresh_list(self._list.currentRow())

    def _edit_scale(self) -> None:
        stave = self._selected_stave()
        if stave is None:
            return
        scale, accepted = QInputDialog.getDouble(
            self,
            "Set Stave Scale",
            "Stave scale:",
            stave.scale,
            0.1,
            4.0,
            2,
        )
        if accepted:
            stave.scale = scale

    def _update_controls(self) -> None:
        has_selection = self._selected_stave() is not None
        self._name_button.setEnabled(has_selection)
        self._range_button.setEnabled(has_selection)
        self._scale_button.setEnabled(has_selection)
        self._remove_button.setEnabled(len(self._staves) > 1 and has_selection)