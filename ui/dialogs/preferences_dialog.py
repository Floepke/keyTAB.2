"""Application preference controls for keyTAB2."""

from __future__ import annotations

from PySide6.QtWidgets import QCheckBox, QDialog, QDialogButtonBox, QFormLayout, QVBoxLayout


class PreferencesDialog(QDialog):
    """Edit persisted application preferences."""

    def __init__(self, save_on_exit: bool, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Preferences")
        self.save_on_exit = QCheckBox(self)
        self.save_on_exit.setChecked(save_on_exit)
        form = QFormLayout()
        form.addRow("Save On Exit:", self.save_on_exit)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel, self)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)

    def save_on_exit_enabled(self) -> bool:
        return self.save_on_exit.isChecked()