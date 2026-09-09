from __future__ import annotations

import unittest
from unittest.mock import Mock

from PySide6.QtCore import QPointF, QRect
from PySide6.QtGui import QImage, QPainter
from PySide6.QtWidgets import QApplication

from keytab2_model import KeyTab2Document, SlurEvent
from ui.drawers.stave_drawer import StaveDrawer
from ui.paper_canvas import PaperCanvas


class SlurToolTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.application = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.document = KeyTab2Document.new()
        self.canvas = PaperCanvas(self.document)
        self.system = self.document.pages[0].systems[0]
        self.stave = self.system.staves[0]
        self.left_mm = self.canvas.stave_left_mm(self.system, self.stave)
        self.canvas.select_slur_mode("left")
        self.tool = self.canvas._tool_manager.active_tool

    def _point(self, pitch: int, tick: int) -> QPointF:
        return QPointF(
            StaveDrawer.pitch_to_x_mm(pitch, self.stave.pitch_range[0], self.left_mm, self.document.layout.engraving_mm(2.0, self.stave.scale)),
            self.canvas._time_to_y_mm(self.system, tick),
        )

    def test_dragging_new_slur_sets_endpoint_and_linked_control_handle(self) -> None:
        self.assertTrue(self.tool.on_left_press(self._point(60, 256)))
        self.assertTrue(self.tool.on_left_drag(self._point(67, 512)))
        self.assertTrue(self.tool.on_left_release(self._point(67, 512)))

        slur = self.stave.events[0]
        self.assertIsInstance(slur, SlurEvent)
        self.assertEqual((slur.x1_rpitch, slur.y1_tick), (0, 256))
        self.assertEqual((slur.x4_rpitch, slur.y4_tick), (7, 512))
        self.assertEqual((slur.x3_rpitch, slur.y3_tick), (1, 512))

    def test_handle_drag_is_limited_by_page_bounds_not_midi_or_system_bounds(self) -> None:
        self.document.pages[0].width_mm = 500.0
        self.canvas._update_size()
        self.left_mm = self.canvas.stave_left_mm(self.system, self.stave)
        slur = SlurEvent(x1_rpitch=0, y1_tick=256, x2_rpitch=-6, y2_tick=256, x3_rpitch=1, y3_tick=512, x4_rpitch=7, y4_tick=512)
        self.stave.events.append(slur)
        self.stave.touch()

        self.assertTrue(self.tool.on_left_press(self._point(67, 512)))
        self.assertTrue(self.tool.on_left_drag(QPointF(1000.0, 1000.0)))
        self.assertTrue(self.tool.on_left_release(QPointF(1000.0, 1000.0)))

        points = self.tool._points_mm(self.system, self.stave, self.left_mm, slur)
        self.assertTrue(all(0.0 <= x_mm <= self.document.pages[0].width_mm for x_mm, _ in points))
        self.assertTrue(all(0.0 <= y_mm <= self.document.pages[0].height_mm for _, y_mm in points))
        self.assertGreater(slur.x4_rpitch, 67)
        self.assertGreater(slur.y4_tick, self.system.end_tick)

    def test_dragging_control_handle_moves_only_that_handle(self) -> None:
        slur = SlurEvent(x1_rpitch=0, y1_tick=256, x2_rpitch=-6, y2_tick=256, x3_rpitch=1, y3_tick=512, x4_rpitch=7, y4_tick=512)
        self.stave.events.append(slur)
        self.stave.touch()

        self.assertTrue(self.tool.on_left_press(self._point(54, 256)))
        self.assertTrue(self.tool.on_left_drag(self._point(57, 320)))
        self.assertTrue(self.tool.on_left_release(self._point(57, 320)))

        self.assertEqual((slur.x2_rpitch, slur.y2_tick), (-3, 320))
        self.assertEqual((slur.x1_rpitch, slur.y1_tick), (0, 256))

    def test_dragging_a_handle_uses_an_overlay_until_release(self) -> None:
        slur = SlurEvent(x1_rpitch=0, y1_tick=256, x2_rpitch=-6, y2_tick=256, x3_rpitch=1, y3_tick=512, x4_rpitch=7, y4_tick=512)
        self.stave.events.append(slur)
        self.stave.touch()
        invalidate = Mock(wraps=self.canvas.invalidate_system_render_cache)
        self.canvas.invalidate_system_render_cache = invalidate

        self.assertTrue(self.tool.on_left_press(self._point(54, 256)))
        self.assertTrue(self.tool.on_left_drag(self._point(57, 320)))

        self.assertEqual((slur.x2_rpitch, slur.y2_tick), (-6, 256))
        self.assertEqual(self.tool.drag_preview_points[1], self._point(57, 320).toTuple())
        invalidate.assert_not_called()
        self.assertTrue(self.tool.on_left_release(self._point(57, 320)))
        self.assertEqual((slur.x2_rpitch, slur.y2_tick), (-3, 320))
        invalidate.assert_called_once_with(self.system.id, self.stave.id)

    def test_drag_preview_paints_without_rebuilding_the_system(self) -> None:
        slur = SlurEvent(x1_rpitch=0, y1_tick=256, x2_rpitch=-6, y2_tick=256, x3_rpitch=1, y3_tick=512, x4_rpitch=7, y4_tick=512)
        self.stave.events.append(slur)
        self.stave.touch()
        self.assertTrue(self.tool.on_left_press(self._point(54, 256)))
        self.assertTrue(self.tool.on_left_drag(self._point(57, 320)))
        image = QImage(self.canvas.size(), QImage.Format.Format_ARGB32_Premultiplied)
        painter = QPainter(image)

        self.canvas._draw_interaction_overlay(painter, QRect(0, 0, image.width(), image.height()))

        self.assertTrue(painter.isActive())
        painter.end()

    def test_right_click_handle_deletes_slur(self) -> None:
        slur = SlurEvent(x1_rpitch=0, y1_tick=256)
        self.stave.events.append(slur)
        self.stave.touch()

        self.assertTrue(self.tool.on_right_click(self._point(60, 256)))
        self.assertEqual(self.stave.events, [])

    def test_copy_cut_and_paste_selected_handle_preserves_all_handle_offsets(self) -> None:
        slur = SlurEvent(x1_rpitch=0, y1_tick=256, x2_rpitch=-4, y2_tick=320, x3_rpitch=5, y3_tick=448, x4_rpitch=7, y4_tick=512)
        self.stave.events.append(slur)
        self.stave.touch()

        self.assertTrue(self.tool.on_left_press(self._point(56, 320)))
        self.assertEqual(self.canvas._selected_slur_ids, {slur.id})
        self.assertTrue(self.canvas.copy_selection())
        self.assertTrue(self.canvas.cut_selection())
        self.assertEqual(self.stave.events, [])
        self.canvas.update_mouse_cursor(self._point(62, 640))

        self.assertTrue(self.canvas.paste_selection())

        pasted = self.stave.events[0]
        self.assertIsInstance(pasted, SlurEvent)
        self.assertEqual(
            (pasted.x1_rpitch, pasted.y1_tick, pasted.x2_rpitch, pasted.y2_tick, pasted.x3_rpitch, pasted.y3_tick, pasted.x4_rpitch, pasted.y4_tick),
            (6, 640, 2, 704, 11, 832, 13, 896),
        )


if __name__ == "__main__":
    unittest.main()