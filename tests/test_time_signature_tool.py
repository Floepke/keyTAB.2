from __future__ import annotations

import unittest

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QKeyEvent, QMouseEvent
from PySide6.QtWidgets import QApplication

from keytab2_model import KeyTab2Document, Stave
from ui.dialogs.time_signature_dialog import TimeSignatureDialog
from ui.paper_canvas import PaperCanvas


class TimeSignatureToolTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.application = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.canvas = PaperCanvas(KeyTab2Document.new())
        self.system = self.canvas.document.pages[0].systems[0]
        self.tool = self.canvas._time_signature_tool

    def _point(self, time: int) -> QPointF:
        left_mm, right_mm = self.canvas._system_column_bounds(self.canvas.current_page, self.system)
        return QPointF((left_mm + right_mm) * 0.5, self.canvas._time_to_y_mm(self.system, time))

    def test_targets_barlines_and_grid_lines(self) -> None:
        self.assertEqual(self.canvas.time_signature_target_at(self._point(0)), ("barline", 0))
        self.assertEqual(self.canvas.time_signature_target_at(self._point(256)), ("grid", 256))

    def test_time_signature_dialog_selects_the_current_signature(self) -> None:
        dialog = TimeSignatureDialog(self.canvas.document.base_grid[0])
        dialog.show()
        self.application.processEvents()

        self.assertTrue(dialog.signature.hasFocus())
        self.assertEqual(dialog.signature.selectedText(), "4/4")
        self.application.sendEvent(
            dialog.signature,
            QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_3, Qt.KeyboardModifier.NoModifier, "3"),
        )
        self.assertEqual(dialog.signature.text(), "3")
        dialog.close()

    def test_hovered_barline_exposes_all_valid_beats_for_its_measure(self) -> None:
        self.canvas.update_mouse_cursor(self._point(0))

        hovered_measure = self.canvas._time_signature_hovered_measure()

        self.assertIsNotNone(hovered_measure)
        system, measure_start, beat_duration, numerator = hovered_measure
        self.assertIs(system, self.system)
        self.assertEqual((measure_start, beat_duration, numerator), (0, 256, 4))

    def test_grid_lines_toggle_with_left_and_right_clicks(self) -> None:
        point = self._point(256)

        self.assertTrue(self.tool.on_right_click(point))
        self.assertEqual(self.canvas.document.base_grid[0].beat_grouping, [1, 3, 4])
        self.assertTrue(self.tool.on_left_press(point))
        self.assertEqual(self.canvas.document.base_grid[0].beat_grouping, [1, 2, 3, 4])

    def test_right_click_removes_a_time_signature_change(self) -> None:
        self.canvas.document.set_time_signature(2048, 3, 4, True)

        self.assertTrue(self.tool.on_right_click(self._point(2048)))

        self.assertEqual([(segment.numerator, segment.denominator, segment.measure_amount) for segment in self.canvas.document.base_grid], [(4, 4, 8)])

    def test_final_plus_control_appends_one_measure(self) -> None:
        left_mm, right_mm = self.canvas._system_column_bounds(self.canvas.current_page, self.system)
        point_mm = QPointF(
            (left_mm + right_mm) * 0.5 - (self.canvas.ADD_MEASURE_CONTROL_SIZE_MM + self.canvas.ADD_MEASURE_CONTROL_GAP_MM) * 0.5,
            self.system.top_mm + self.system.height_mm + self.canvas.ADD_MEASURE_CONTROL_GAP_MM + self.canvas.ADD_MEASURE_CONTROL_SIZE_MM * 0.5,
        )
        point_px = point_mm * self.canvas.pixels_per_mm
        event = QMouseEvent(
            QMouseEvent.Type.MouseButtonPress,
            point_px,
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )

        self.canvas.mousePressEvent(event)

        self.assertEqual(self.canvas.document.base_grid[-1].measure_amount, 9)

    def test_final_minus_control_removes_one_measure(self) -> None:
        left_mm, right_mm = self.canvas._system_column_bounds(self.canvas.current_page, self.system)
        point_mm = QPointF(
            (left_mm + right_mm) * 0.5 + (self.canvas.ADD_MEASURE_CONTROL_SIZE_MM + self.canvas.ADD_MEASURE_CONTROL_GAP_MM) * 0.5,
            self.system.top_mm + self.system.height_mm + self.canvas.ADD_MEASURE_CONTROL_GAP_MM + self.canvas.ADD_MEASURE_CONTROL_SIZE_MM * 0.5,
        )
        point_px = point_mm * self.canvas.pixels_per_mm
        event = QMouseEvent(QMouseEvent.Type.MouseButtonPress, point_px, Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)

        self.canvas.mousePressEvent(event)

        self.assertEqual(self.canvas.document.base_grid[-1].measure_amount, 7)

    def test_final_measure_controls_are_centred_on_multi_stave_system(self) -> None:
        self.system.staves.append(Stave(pitch_range=[60, 72]))
        left_mm, right_mm = self.canvas._system_column_bounds(self.canvas.current_page, self.system)
        centre_x_mm = (left_mm + right_mm) * 0.5
        centre_y_mm = self.system.top_mm + self.system.height_mm + self.canvas.ADD_MEASURE_CONTROL_GAP_MM + self.canvas.ADD_MEASURE_CONTROL_SIZE_MM * 0.5

        self.assertEqual(self.canvas._measure_control_at(QPointF(centre_x_mm - 3.5, centre_y_mm)), "add")
        self.assertEqual(self.canvas._measure_control_at(QPointF(centre_x_mm + 3.5, centre_y_mm)), "remove")
