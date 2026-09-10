from __future__ import annotations

import unittest

from PySide6.QtWidgets import QApplication, QFontComboBox

from keytab2_model import GridBandEvent, KeyTab2Document
from ui.dialogs.info_dialog import InfoDialog
from ui.dialogs.preferences_dialog import PreferencesDialog
from ui.dialogs.style_dialog import StyleDialog


class DocumentDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.application = QApplication.instance() or QApplication([])

    def test_info_dialog_applies_score_metadata(self) -> None:
        document = KeyTab2Document.new()
        dialog = InfoDialog(document)
        dialog._title_edit.setText("Prelude")
        dialog._composer_edit.setText("J. S. Bach")
        dialog._copyright_edit.setText("Public domain")

        dialog.apply_to_document()

        self.assertEqual(document.score_info.title, "Prelude")
        self.assertEqual(document.score_info.composer, "J. S. Bach")
        self.assertEqual(document.score_info.copyright, "Public domain")

    def test_preferences_dialog_returns_save_on_exit_value(self) -> None:
        dialog = PreferencesDialog(False)

        self.assertFalse(dialog.save_on_exit_enabled())
        dialog.save_on_exit.setChecked(True)
        self.assertTrue(dialog.save_on_exit_enabled())

    def test_style_dialog_round_trips_every_layout_field(self) -> None:
        document = KeyTab2Document.new()
        dialog = StyleDialog(document.layout)

        self.assertEqual(dialog.value(), document.layout)
        self.assertEqual(set(dialog._editors), set(document.layout.__dataclass_fields__))

    def test_style_dialog_returns_edited_layout_values(self) -> None:
        document = KeyTab2Document.new()
        dialog = StyleDialog(document.layout)
        dialog._editors["scale"].setValue(0.5)
        dialog._editors["note_head_visible"].setChecked(False)

        layout = dialog.value()

        self.assertEqual(layout.scale, 0.5)
        self.assertFalse(layout.note_head_visible)

    def test_style_dialog_round_trips_grid_band_events(self) -> None:
        document = KeyTab2Document.new()
        document.layout.grid_band_track = [GridBandEvent(start_tick=512, duration_ticks=128)]

        layout = StyleDialog(document.layout).value()

        self.assertEqual(
            [(event.start_tick, event.duration_ticks) for event in layout.grid_band_track],
            [(512, 128)],
        )

    def test_style_dialog_uses_qt_font_family_selectors(self) -> None:
        dialog = StyleDialog(KeyTab2Document.new().layout)
        font_editor = dialog._editors["font_title"]

        self.assertIsInstance(font_editor.family, QFontComboBox)
        self.assertEqual(dialog.value().font_title.family, font_editor.family.currentFont().family())


if __name__ == "__main__":
    unittest.main()