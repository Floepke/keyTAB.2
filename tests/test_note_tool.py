from __future__ import annotations

import unittest
from unittest.mock import Mock

from PySide6.QtCore import QPointF, QRect
from PySide6.QtGui import QImage, QPainter
from PySide6.QtWidgets import QApplication

from keytab2_model import KeyTab2Document
from ui.drawers.stave_drawer import StaveDrawer
from ui.paper_canvas import PaperCanvas


class NoteToolTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.application = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.document = KeyTab2Document.new()
        self.canvas = PaperCanvas(self.document)
        self.system = self.document.pages[0].systems[0]
        self.stave = self.system.staves[0]
        self.left_mm = self.canvas.stave_left_mm(self.system, self.stave)

    def _point(self, pitch: int, time: int) -> QPointF:
        x_mm = StaveDrawer.pitch_to_x_mm(
            pitch,
            self.stave.pitch_range[0],
            self.left_mm,
            self.document.layout.engraving_mm(2.0, self.stave.scale),
        )
        return QPointF(x_mm, self.canvas._time_to_y_mm(self.system, time))

    def _notehead_interior(self) -> QPointF:
        render_data = self.canvas._stave_render_data(self.system, self.stave, self.left_mm)
        points = render_data.notes.geometries[0].head.points_mm
        return QPointF(
            sum(x_mm for x_mm, _ in points) / len(points),
            sum(y_mm for _, y_mm in points) / len(points),
        )

    def test_note_mode_creates_resizes_and_deletes_a_selected_hand_note(self) -> None:
        self.canvas.select_note_hand("right")
        tool = self.canvas._tool_manager.active_tool
        start = self._point(60, 256)

        self.assertIsNotNone(tool)
        self.assertFalse(tool.is_editing)
        self.assertTrue(tool.on_left_press(start))
        self.assertTrue(tool.is_editing)
        self.assertEqual((self.stave.events[0].time, self.stave.events[0].duration, self.stave.events[0].pitch, self.stave.events[0].hand), (256, 64, 60, "right"))
        self.assertTrue(tool.on_left_drag(self._point(60, 512)))
        self.assertEqual(self.stave.events[0].duration, 64)
        self.assertTrue(tool.on_left_release(self._point(60, 512)))
        self.assertEqual(self.stave.events[0].duration, 256)
        self.assertFalse(tool.is_editing)
        self.assertTrue(tool.on_right_click(start))
        self.assertEqual(self.stave.events, [])

    def test_dragging_a_notehead_moves_time_and_pitch(self) -> None:
        tool = self.canvas._tool_manager.active_tool
        source = self._point(60, 256)

        self.assertTrue(tool.on_left_press(source))
        self.assertTrue(tool.on_left_release(source))
        self.assertTrue(tool.on_left_press(self._notehead_interior()))
        self.assertTrue(tool.on_left_drag(self._point(62, 512)))
        self.assertTrue(tool.on_left_release(source))

        note = self.stave.events[0]
        self.assertEqual((note.time, note.pitch, note.duration), (512, 62, 64))

    def test_notehead_drag_uses_overlay_until_release(self) -> None:
        tool = self.canvas._tool_manager.active_tool
        source = self._point(60, 256)
        self.assertTrue(tool.on_left_press(source))
        self.assertTrue(tool.on_left_release(source))
        notehead = self._notehead_interior()
        self.assertTrue(tool.on_left_press(notehead))
        invalidate = Mock(wraps=self.canvas.invalidate_system_render_cache)
        self.canvas.invalidate_system_render_cache = invalidate

        self.assertTrue(tool.on_left_drag(self._point(62, 512)))

        self.assertEqual(self.stave.events, [])
        self.assertIsNotNone(tool.drag_preview)
        invalidate.assert_not_called()
        self.assertTrue(tool.on_left_release(source))
        self.assertEqual((self.stave.events[0].time, self.stave.events[0].pitch), (512, 62))
        invalidate.assert_called_once_with(self.system.id, self.stave.id)

    def test_notehead_drag_overlay_paints_with_a_balanced_painter_state(self) -> None:
        tool = self.canvas._tool_manager.active_tool
        source = self._point(60, 256)
        self.assertTrue(tool.on_left_press(source))
        self.assertTrue(tool.on_left_release(source))
        self.assertTrue(tool.on_left_press(self._notehead_interior()))
        self.assertTrue(tool.on_left_drag(self._point(62, 512)))
        image = QImage(self.canvas.size(), QImage.Format.Format_ARGB32_Premultiplied)
        painter = QPainter(image)

        self.canvas._draw_interaction_overlay(painter, QRect(0, 0, image.width(), image.height()))

        self.assertTrue(painter.isActive())
        painter.end()

    def test_stem_does_not_grab_the_existing_note(self) -> None:
        tool = self.canvas._tool_manager.active_tool
        source = self._point(60, 256)

        self.assertTrue(tool.on_left_press(source))
        self.assertTrue(tool.on_left_release(source))
        geometry = self.canvas._stave_render_data(self.system, self.stave, self.left_mm).notes.geometries[0]

        self.assertTrue(tool.on_left_press(QPointF(geometry.stem[2], geometry.stem[3])))
        self.assertEqual(len(self.stave.events), 2)
        self.assertNotEqual(self.stave.events[0].id, self.stave.events[1].id)

    def test_right_click_deletes_the_note_at_snapped_cursor_pitch_in_a_cluster(self) -> None:
        tool = self.canvas._tool_manager.active_tool
        self.assertTrue(tool.on_left_press(self._point(60, 256)))
        self.assertTrue(tool.on_left_release(self._point(60, 256)))
        self.assertTrue(tool.on_left_press(self._point(64, 256)))
        self.assertTrue(tool.on_left_release(self._point(64, 256)))

        self.assertTrue(tool.on_right_click(self._point(64, 280)))

        self.assertEqual([note.pitch for note in self.stave.events], [60])

    def test_mouse_cursor_snaps_time_and_pitch(self) -> None:
        self.canvas.set_input_snap_ticks(128)
        point = self._point(62, 290)

        self.canvas.update_mouse_cursor(point)

        self.assertEqual((self.canvas.mouse_time, self.canvas.mouse_pitch), (256, 62))

    def test_note_mode_places_a_note_outside_the_configured_stave_range(self) -> None:
        tool = self.canvas._tool_manager.active_tool
        ledger_point = self._point(34, 256)
        natural_width = self.document._system_required_width_mm(self.system)

        self.assertFalse(tool.on_left_press(ledger_point))
        self.assertTrue(tool.on_left_press(self._point(36, 256)))
        self.assertTrue(tool.on_left_release(self._point(36, 256)))
        geometry = self.canvas._stave_render_data(self.system, self.stave, self.left_mm).notes.geometries[0]
        notehead = QPointF(
            sum(x_mm for x_mm, _ in geometry.head.points_mm) / len(geometry.head.points_mm),
            sum(y_mm for _, y_mm in geometry.head.points_mm) / len(geometry.head.points_mm),
        )
        self.assertTrue(tool.on_left_press(notehead))
        self.assertTrue(tool.on_left_drag(ledger_point))
        self.assertTrue(tool.on_left_release(ledger_point))
        self.assertEqual(self.stave.events[0].pitch, 34)
        self.assertGreater(self.document._system_required_width_mm(self.system), natural_width)

    def test_dragging_a_ledger_notehead_uses_its_owning_stave(self) -> None:
        tool = self.canvas._tool_manager.active_tool
        source = self._point(36, 256)
        self.assertTrue(tool.on_left_press(source))
        self.assertTrue(tool.on_left_release(source))
        geometry = self.canvas._stave_render_data(self.system, self.stave, self.left_mm).notes.geometries[0]
        in_range_head = QPointF(
            sum(x_mm for x_mm, _ in geometry.head.points_mm) / len(geometry.head.points_mm),
            sum(y_mm for _, y_mm in geometry.head.points_mm) / len(geometry.head.points_mm),
        )
        self.assertTrue(tool.on_left_press(in_range_head))
        self.assertTrue(tool.on_left_drag(self._point(34, 256)))
        self.assertTrue(tool.on_left_release(self._point(34, 256)))
        system = self.canvas.document.pages[0].systems[0]
        stave = system.staves[0]
        left_mm = self.canvas.stave_left_mm(system, stave)
        geometry = self.canvas._stave_render_data(system, stave, left_mm).notes.geometries[0]
        notehead = QPointF(
            sum(x_mm for x_mm, _ in geometry.head.points_mm) / len(geometry.head.points_mm),
            sum(y_mm for _, y_mm in geometry.head.points_mm) / len(geometry.head.points_mm),
        )
        target = QPointF(
            StaveDrawer.pitch_to_x_mm(36, stave.pitch_range[0], left_mm, self.document.layout.engraving_mm(2.0, stave.scale)),
            self.canvas._time_to_y_mm(system, 512),
        )

        self.assertTrue(tool.on_left_press(notehead))
        self.assertTrue(tool.on_left_drag(target))
        self.assertTrue(tool.on_left_release(notehead))

        note = stave.events[0]
        self.assertEqual((note.time, note.pitch), (512, 36))

    def test_dragging_a_ledger_notehead_uses_overlay_until_release(self) -> None:
        tool = self.canvas._tool_manager.active_tool
        self.assertTrue(tool.on_left_press(self._point(36, 256)))
        self.assertTrue(tool.on_left_release(self._point(36, 256)))
        geometry = self.canvas._stave_render_data(self.system, self.stave, self.left_mm).notes.geometries[0]
        head = QPointF(
            sum(x_mm for x_mm, _ in geometry.head.points_mm) / len(geometry.head.points_mm),
            sum(y_mm for _, y_mm in geometry.head.points_mm) / len(geometry.head.points_mm),
        )
        self.assertTrue(tool.on_left_press(head))
        self.assertTrue(tool.on_left_drag(self._point(34, 256)))
        self.assertTrue(tool.on_left_release(self._point(34, 256)))
        system = self.canvas.document.pages[0].systems[0]
        stave = system.staves[0]
        left_mm = self.canvas.stave_left_mm(system, stave)
        geometry = self.canvas._stave_render_data(system, stave, left_mm).notes.geometries[0]
        ledger_head = QPointF(
            sum(x_mm for x_mm, _ in geometry.head.points_mm) / len(geometry.head.points_mm),
            sum(y_mm for _, y_mm in geometry.head.points_mm) / len(geometry.head.points_mm),
        )
        target = QPointF(
            StaveDrawer.pitch_to_x_mm(36, stave.pitch_range[0], left_mm, self.document.layout.engraving_mm(2.0, stave.scale)),
            self.canvas._time_to_y_mm(system, 512),
        )
        invalidate = Mock(wraps=self.canvas.invalidate_system_render_cache)
        self.canvas.invalidate_system_render_cache = invalidate

        self.assertTrue(tool.on_left_press(ledger_head))
        invalidate.reset_mock()
        self.assertTrue(tool.on_left_drag(target))

        self.assertEqual(stave.events, [])
        self.assertIsNotNone(tool.drag_preview)
        invalidate.assert_not_called()
        self.assertTrue(tool.on_left_release(ledger_head))
        self.assertEqual((stave.events[0].time, stave.events[0].pitch), (512, 36))

    def test_in_range_note_edits_do_not_repaginate_the_document(self) -> None:
        tool = self.canvas._tool_manager.active_tool
        repaginate = Mock(wraps=self.canvas.repaginate_document)
        self.canvas.repaginate_document = repaginate
        point = self._point(60, 256)

        self.assertTrue(tool.on_left_press(point))
        self.assertTrue(tool.on_left_release(point))

        repaginate.assert_not_called()

    def test_in_range_note_edits_retain_cached_page_system_dimensions(self) -> None:
        tool = self.canvas._tool_manager.active_tool
        page = self.document.pages[0]
        self.canvas._system_column_bounds(page, self.system)
        cached_bounds = self.canvas._page_system_bounds_cache[page.id][1]
        point = self._point(60, 256)

        self.assertTrue(tool.on_left_press(point))
        self.assertTrue(tool.on_left_release(point))

        self.assertIs(self.canvas._page_system_bounds_cache[page.id][1], cached_bounds)

    def test_deleting_an_in_range_note_invalidates_rendered_tiles(self) -> None:
        tool = self.canvas._tool_manager.active_tool
        point = self._point(60, 256)
        self.assertTrue(tool.on_left_press(point))
        self.assertTrue(tool.on_left_release(point))
        page = self.document.pages[0]
        dirty_rect = self.canvas._system_pixel_rect(page, self.system)
        tile_key = (1.0, dirty_rect.center().x() // self.canvas.TILE_SIZE_PX, dirty_rect.center().y() // self.canvas.TILE_SIZE_PX)
        self.canvas._tile_cache[tile_key] = object()

        self.assertTrue(tool.on_right_click(point))

        self.assertNotIn(tile_key, self.canvas._tile_cache)

    def test_resizing_note_defers_continuation_work_until_release(self) -> None:
        tool = self.canvas._tool_manager.active_tool
        point = self._point(60, 256)
        self.assertTrue(tool.on_left_press(point))
        rebuild = Mock(wraps=tool._set_spanning_duration)
        invalidate = Mock(wraps=self.canvas.invalidate_render_cache)
        tool._set_spanning_duration = rebuild
        self.canvas.invalidate_render_cache = invalidate

        self.assertTrue(tool.on_left_drag(self._point(60, 260)))
        self.assertTrue(tool.on_left_drag(self._point(60, 300)))

        rebuild.assert_not_called()
        invalidate.assert_not_called()
        self.assertTrue(tool.on_left_drag(self._point(60, 512)))
        rebuild.assert_not_called()
        invalidate.assert_not_called()
        self.assertIsNotNone(tool.duration_preview)
        self.assertTrue(tool.on_left_release(self._point(60, 512)))
        rebuild.assert_called_once()
        invalidate.assert_called_once()

    def test_duration_drag_overlay_paints_without_rebuilding_render_data(self) -> None:
        tool = self.canvas._tool_manager.active_tool
        point = self._point(60, 256)
        self.assertTrue(tool.on_left_press(point))
        self.assertTrue(tool.on_left_drag(self._point(60, 512)))
        self.canvas._draw_selection_overlay = Mock()
        render_data = Mock(wraps=self.canvas._stave_render_data)
        self.canvas._stave_render_data = render_data
        image = QImage(self.canvas.size(), QImage.Format.Format_ARGB32_Premultiplied)
        painter = QPainter(image)

        self.canvas._draw_interaction_overlay(painter, QRect(0, 0, image.width(), image.height()))

        self.assertTrue(painter.isActive())
        painter.end()
        render_data.assert_not_called()
        self.assertGreater(sum(image.pixelColor(x, y).alpha() for x in range(image.width()) for y in range(image.height())), 0)

    def test_dragging_a_note_body_across_a_system_break_creates_continuations(self) -> None:
        following_system = self.document.split_system_at(self.document.pages[0].id, self.system.id, 1024)
        tool = self.canvas._tool_manager.active_tool
        leading_left_mm = self.canvas.stave_left_mm(self.system, self.stave)
        start_x_mm = StaveDrawer.pitch_to_x_mm(60, self.stave.pitch_range[0], leading_left_mm, self.document.layout.engraving_mm(2.0, self.stave.scale))
        start = QPointF(start_x_mm, self.canvas._time_to_y_mm(self.system, 256))
        following_left_mm = self.canvas.stave_left_mm(following_system, following_system.staves[0])
        end_x_mm = StaveDrawer.pitch_to_x_mm(60, following_system.staves[0].pitch_range[0], following_left_mm, self.document.layout.engraving_mm(2.0, following_system.staves[0].scale))
        end = QPointF(end_x_mm, self.canvas._time_to_y_mm(following_system, 1280))

        self.assertTrue(tool.on_left_press(start))
        self.assertTrue(tool.on_left_drag(end))
        self.assertTrue(tool.on_left_release(end))

        leading_note = self.system.staves[0].events[0]
        following_note = following_system.staves[0].events[0]
        self.assertEqual((leading_note.time, leading_note.duration), (256, 768))
        self.assertEqual((following_note.time, following_note.duration), (1024, 256))
        self.assertTrue(leading_note.continues_to_next)
        self.assertTrue(following_note.continues_from_previous)
        self.assertEqual(leading_note.continuation_id, following_note.continuation_id)

    def test_deleting_a_continuation_tail_removes_the_entire_linked_note(self) -> None:
        following_system = self.document.split_system_at(self.document.pages[0].id, self.system.id, 1024)
        tool = self.canvas._tool_manager.active_tool
        leading_left_mm = self.canvas.stave_left_mm(self.system, self.stave)
        start = QPointF(
            StaveDrawer.pitch_to_x_mm(60, self.stave.pitch_range[0], leading_left_mm, self.document.layout.engraving_mm(2.0, self.stave.scale)),
            self.canvas._time_to_y_mm(self.system, 256),
        )
        following_left_mm = self.canvas.stave_left_mm(following_system, following_system.staves[0])
        end = QPointF(
            StaveDrawer.pitch_to_x_mm(60, following_system.staves[0].pitch_range[0], following_left_mm, self.document.layout.engraving_mm(2.0, following_system.staves[0].scale)),
            self.canvas._time_to_y_mm(following_system, 1280),
        )

        self.assertTrue(tool.on_left_press(start))
        self.assertTrue(tool.on_left_drag(end))
        self.assertTrue(tool.on_left_release(end))
        tail_geometry = self.canvas._stave_render_data(
            following_system,
            following_system.staves[0],
            following_left_mm,
        ).notes.geometries[0]
        tail_point = QPointF(
            sum(x_mm for x_mm, _ in tail_geometry.head.points_mm) / len(tail_geometry.head.points_mm),
            sum(y_mm for _, y_mm in tail_geometry.head.points_mm) / len(tail_geometry.head.points_mm),
        )
        self.assertTrue(tool.on_right_click(tail_point))

        self.assertEqual(self.system.staves[0].events, [])
        self.assertEqual(following_system.staves[0].events, [])


if __name__ == "__main__":
    unittest.main()
