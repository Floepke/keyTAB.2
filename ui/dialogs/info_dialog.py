"""Document metadata dialog for keyTAB2 scores."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
)

from keytab2_model.document import KeyTab2Document


class InfoDialog(QDialog):
    """Edit the metadata currently supported by a keyTAB2 document."""

    def __init__(self, document: KeyTab2Document, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Titles and Info")
        self.setMinimumWidth(420)
        self._document = document
        self._title_edit = QLineEdit(document.score_info.title, self)
        self._composer_edit = QLineEdit(document.score_info.composer, self)
        self._copyright_edit = QLineEdit(document.score_info.copyright, self)

        info_group = QGroupBox("Info", self)
        info_form = QFormLayout(info_group)
        info_form.addRow("Title:", self._title_edit)
        info_form.addRow("Composer:", self._composer_edit)
        info_form.addRow("Copyright:", self._copyright_edit)

        metadata_group = QGroupBox("Document", self)
        metadata_form = QFormLayout(metadata_group)
        for label, value in (
            ("Format:", document.format),
            ("Version:", str(document.format_version)),
            ("Created:", document.created_at),
            ("Modified:", document.modified_at),
        ):
            text = QLabel(value, self)
            text.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            metadata_form.addRow(label, text)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel, self)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addWidget(info_group)
        layout.addWidget(metadata_group)
        layout.addWidget(buttons)

    def apply_to_document(self) -> None:
        self._document.score_info.title = self._title_edit.text().strip() or "Untitled"
        self._document.score_info.composer = self._composer_edit.text().strip()
        self._document.score_info.copyright = self._copyright_edit.text().strip()