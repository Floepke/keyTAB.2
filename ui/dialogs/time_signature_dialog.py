"""Native dialog for one base-grid time-signature segment."""

from __future__ import annotations

from PySide6.QtCore import QRegularExpression, QTimer
from PySide6.QtGui import QRegularExpressionValidator, QShowEvent
from PySide6.QtWidgets import QCheckBox, QDialog, QDialogButtonBox, QFormLayout, QLineEdit

from keytab2_model.base_grid import BaseGrid


class TimeSignatureDialog(QDialog):
    """Edit a meter signature and whether its indicator is drawn."""

    def __init__(self, segment: BaseGrid, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Time Signature")
        self.setModal(True)
        layout = QFormLayout(self)
        self.signature = QLineEdit(f"{segment.numerator}/{segment.denominator}", self)
        self.signature.setValidator(QRegularExpressionValidator(QRegularExpression(r"[0-9]*/?[0-9]*"), self.signature))
        self.indicator_enabled = QCheckBox(self)
        self.indicator_enabled.setChecked(segment.indicator_enabled)
        layout.addRow("Time signature", self.signature)
        layout.addRow("Indicator enabled", self.indicator_enabled)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel, self)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        QTimer.singleShot(0, self._select_signature)

    def _select_signature(self) -> None:
        self.signature.setFocus()
        self.signature.selectAll()

    def value(self) -> tuple[int, int, bool]:
        numerator, separator, denominator = self.signature.text().strip().partition("/")
        if not separator or not numerator.isdigit() or not denominator.isdigit():
            raise ValueError("Time signature must use the form N/D")
        numerator_value, denominator_value = int(numerator), int(denominator)
        if numerator_value < 1 or denominator_value < 1 or denominator_value & (denominator_value - 1):
            raise ValueError("Denominator must be a positive power of two")
        return numerator_value, denominator_value, self.indicator_enabled.isChecked()