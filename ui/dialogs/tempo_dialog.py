"""Native dialog for a tempo marking."""

from __future__ import annotations

from PySide6.QtCore import QTimer
from PySide6.QtGui import QShowEvent
from PySide6.QtWidgets import QCheckBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFormLayout, QSpinBox

from keytab2_model import TempoEvent


class TempoDialog(QDialog):
    """Edit the value and appearance of one tempo marker."""

    def __init__(self, tempo: TempoEvent, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Tempo")
        layout = QFormLayout(self)
        self.tempo = QSpinBox(self)
        self.tempo.setRange(1, 1000)
        self.tempo.setValue(tempo.tempo)
        self.duration = QSpinBox(self)
        self.duration.setRange(1, 1_000_000)
        self.duration.setValue(tempo.duration_ticks)
        self.x_offset = QDoubleSpinBox(self)
        self.x_offset.setRange(-500.0, 500.0)
        self.x_offset.setDecimals(2)
        self.x_offset.setSingleStep(0.1)
        self.x_offset.setValue(tempo.x_offset_mm)
        self.visible = QCheckBox(self)
        self.visible.setChecked(not tempo.invisible)
        layout.addRow("Quarter notes per minute", self.tempo)
        layout.addRow("Duration (ticks)", self.duration)
        layout.addRow("Horizontal offset (mm)", self.x_offset)
        layout.addRow("Visible", self.visible)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel, self)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        QTimer.singleShot(0, self._select_tempo)

    def _select_tempo(self) -> None:
        self.tempo.setFocus()
        self.tempo.selectAll()

    def apply_to(self, tempo: TempoEvent) -> None:
        tempo.tempo = self.tempo.value()
        tempo.duration_ticks = self.duration.value()
        tempo.x_offset_mm = self.x_offset.value()
        tempo.invisible = not self.visible.isChecked()