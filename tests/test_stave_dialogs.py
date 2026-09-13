from __future__ import annotations

import unittest
from unittest.mock import patch

from PySide6.QtCore import QSize
from PySide6.QtWidgets import QApplication

from keytab2_model import KeyTab2Document, NoteEvent, Stave
from ui.dialogs.stave_dialogs import StaveRangeVisualizer, StavesDialog
from ui.paper_canvas import PaperCanvas


class StaveDialogsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.application = QApplication.instance() or QApplication([])

    def test_range_visualizer_keeps_a_valid_low_high_pair(self) -> None:
        visualizer = StaveRangeVisualizer(36, 84)
        visualizer.resize(420, 180)
        visualizer._active_handle = "low"
        visualizer._update_active_handle(visualizer.rect().topRight())

        self.assertEqual(visualizer.pitch_range[0], 83)
        visualizer._active_handle = "high"
        visualizer._update_active_handle(visualizer.rect().topLeft())
        self.assertEqual(visualizer.pitch_range[1], 84)

    def test_staves_dialog_retains_source_ids_for_existing_staves(self) -> None:
        staves = [Stave(name="Upper"), Stave(name="Lower")]
        dialog = StavesDialog(staves)

        self.assertEqual([stave.id for stave in dialog.staves], [stave.id for stave in staves])

    def test_staves_dialog_action_icons_use_dark_button_text(self) -> None:
        dialog = StavesDialog([Stave(name="Upper")])

        for button in (dialog._add_button, dialog._remove_button):
            pixmap = button.icon().pixmap(QSize(18, 18))
            visible_colors = [
                pixmap.toImage().pixelColor(x, y)
                for x in range(pixmap.width())
                for y in range(pixmap.height())
                if pixmap.toImage().pixelColor(x, y).alpha() > 0
            ]
            self.assertTrue(visible_colors)
            self.assertTrue(all(max(color.red(), color.green(), color.blue()) < 80 for color in visible_colors))

    def test_staves_dialog_renames_the_selected_stave(self) -> None:
        dialog = StavesDialog([Stave(name="Upper")])

        with patch("ui.dialogs.stave_dialogs.QInputDialog.getText", return_value=("Treble", True)):
            dialog._edit_name()

        self.assertEqual(dialog.staves[0].name, "Treble")
        self.assertEqual(dialog._name_button.text(), "Set Stave Name")
        self.assertEqual(dialog._range_button.text(), "Set Stave Range")

    def test_staves_dialog_sets_the_selected_stave_scale(self) -> None:
        dialog = StavesDialog([Stave(name="Upper", scale=1.0)])

        with patch("ui.dialogs.stave_dialogs.QInputDialog.getDouble", return_value=(1.5, True)):
            dialog._edit_scale()

        self.assertEqual(dialog.staves[0].scale, 1.5)
        self.assertEqual(dialog._scale_button.text(), "Set Stave Scale")

    def test_staves_dialog_marks_margin_edits_for_global_propagation(self) -> None:
        source_stave = Stave(name="Upper")
        dialog = StavesDialog([source_stave])

        with patch("ui.dialogs.stave_dialogs.QInputDialog.getDouble", return_value=(12.5, True)):
            dialog._edit_margin("left")

        self.assertEqual(dialog.staves[0].left_margin_mm, 12.5)
        self.assertEqual(dialog.edited_fields_by_id, {source_stave.id: {"left_margin_mm"}})

    def test_applying_stave_order_preserves_system_stave_events(self) -> None:
        document = KeyTab2Document.new()
        leading = document.pages[0].systems[0]
        leading.staves.append(Stave(name="Lower"))
        leading.staves[0].events.append(NoteEvent(time=0, duration=64, pitch=60))
        leading.staves[1].events.append(NoteEvent(time=0, duration=64, pitch=48))
        following = document.split_system_at(document.pages[0].id, leading.id, 1024)
        following.staves[0].events.append(NoteEvent(time=1024, duration=64, pitch=62))
        following.staves[1].events.append(NoteEvent(time=1024, duration=64, pitch=50))
        canvas = PaperCanvas(document)
        configured = [
            Stave(name="Bass", pitch_range=[30, 72], id=leading.staves[1].id),
            Stave(name="Treble", pitch_range=[48, 96], id=leading.staves[0].id),
        ]

        canvas._apply_stave_configuration(leading.staves, configured)

        self.assertEqual([stave.name for stave in leading.staves], ["Bass", "Treble"])
        self.assertEqual([event.pitch for event in leading.staves[0].events], [48])
        self.assertEqual([event.pitch for event in leading.staves[1].events], [60])
        self.assertEqual([event.pitch for event in following.staves[0].events], [50])
        self.assertEqual([event.pitch for event in following.staves[1].events], [62])

    def test_setting_a_stave_scale_leaves_sibling_staves_unchanged(self) -> None:
        document = KeyTab2Document.new()
        system = document.pages[0].systems[0]
        system.staves.append(Stave(name="Lower", scale=0.75))
        canvas = PaperCanvas(document)

        canvas._apply_stave_scale(system, system.staves[1], 1.5)

        self.assertEqual(system.staves[0].scale, 1.0)
        self.assertEqual(system.staves[1].scale, 1.5)

    def test_setting_a_stave_margin_leaves_siblings_and_following_system_unchanged(self) -> None:
        document = KeyTab2Document.new()
        leading = document.pages[0].systems[0]
        leading.staves.append(Stave(name="Lower"))
        following = document.split_system_at(document.pages[0].id, leading.id, 1024)
        canvas = PaperCanvas(document)

        canvas._apply_stave_margin(leading, leading.staves[1], "left", 18.0)

        self.assertEqual(leading.staves[0].left_margin_mm, 5.0)
        self.assertEqual(leading.staves[1].left_margin_mm, 18.0)
        self.assertEqual(following.staves[1].left_margin_mm, 5.0)

    def test_explicit_global_stave_configuration_preserves_unedited_local_values(self) -> None:
        document = KeyTab2Document.new()
        leading = document.pages[0].systems[0]
        following = document.split_system_at(document.pages[0].id, leading.id, 1024)
        following.staves[0].left_margin_mm = 14.0
        canvas = PaperCanvas(document)
        configured = Stave(
            name="Treble",
            pitch_range=[48, 96],
            scale=1.5,
            left_margin_mm=22.0,
            right_margin_mm=9.0,
            id=leading.staves[0].id,
        )

        canvas._apply_stave_configuration(
            leading.staves,
            [configured],
            {configured.id: {"name", "scale", "right_margin_mm"}},
        )

        self.assertEqual([stave.name for stave in (leading.staves[0], following.staves[0])], ["Treble", "Treble"])
        self.assertEqual([stave.scale for stave in (leading.staves[0], following.staves[0])], [1.5, 1.5])
        self.assertEqual([stave.right_margin_mm for stave in (leading.staves[0], following.staves[0])], [9.0, 9.0])
        self.assertEqual(leading.staves[0].left_margin_mm, 5.0)
        self.assertEqual(following.staves[0].left_margin_mm, 14.0)
        self.assertEqual([stave.pitch_range for stave in (leading.staves[0], following.staves[0])], [[36, 84], [36, 84]])


if __name__ == "__main__":
    unittest.main()