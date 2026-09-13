from __future__ import annotations

import unittest

from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QColor, QKeyEvent, QMouseEvent, QWheelEvent
from PySide6.QtWidgets import QApplication

from keytab2_model import KeyTab2Document
from ui.drawers.stave_drawer import StaveDrawer
from ui.main_window import PaperView
from ui.paper_canvas import PaperCanvas


class SelectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.application = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.document = KeyTab2Document.new()
        self.canvas = PaperCanvas(self.document)
        self.system = self.document.pages[0].systems[0]
        self.stave = self.system.staves[0]
        self.left_mm = self.canvas.stave_left_mm(self.system, self.stave)
        self.tool = self.canvas._tool_manager.active_tool

    def _point(self, pitch: int, time: int) -> QPointF:
        x_mm = StaveDrawer.pitch_to_x_mm(
            pitch,
            self.stave.pitch_range[0],
            self.left_mm,
            self.document.layout.engraving_mm(2.0, self.stave.scale),
        )
        return QPointF(x_mm, self.canvas._time_to_y_mm(self.system, time))

    def _add_note(self, pitch: int, time: int) -> None:
        point = self._point(pitch, time)
        self.assertTrue(self.tool.on_left_press(point))
        self.assertTrue(self.tool.on_left_release(point))

    def _mouse_event(
        self,
        event_type: QEvent.Type,
        point_mm: QPointF,
        button: Qt.MouseButton,
        buttons: Qt.MouseButton,
    ) -> QMouseEvent:
        return QMouseEvent(
            event_type,
            point_mm * self.canvas.pixels_per_mm,
            button,
            buttons,
            Qt.KeyboardModifier.NoModifier,
        )

    def test_marquee_selects_notes_and_brackets_map_their_hand(self) -> None:
        self._add_note(60, 256)
        self._add_note(64, 512)
        self.canvas._selection_anchor_mm = self._point(59, 192)
        self.canvas._selection_current_mm = self._point(61, 320)

        self.canvas._select_notes_in_rectangle()

        self.assertEqual(self.canvas._selected_note_ids, {self.stave.events[0].id})
        self.assertTrue(self.canvas.set_selected_notes_hand("right"))
        self.assertEqual([note.hand for note in self.stave.events], ["right", "left"])

    def test_shift_click_selection_uses_exact_note_geometry(self) -> None:
        self._add_note(60, 256)
        geometry = self.canvas._stave_render_data(self.system, self.stave, self.left_mm).notes.geometries[0]
        point = QPointF(
            sum(x_mm for x_mm, _ in geometry.head.points_mm) / len(geometry.head.points_mm),
            sum(y_mm for _, y_mm in geometry.head.points_mm) / len(geometry.head.points_mm),
        )
        self.canvas._selection_anchor_mm = point
        self.canvas._selection_current_mm = QPointF(point)

        self.canvas._select_notes_in_rectangle()

        self.assertEqual(self.canvas._selected_note_ids, {self.stave.events[0].id})

    def test_clicking_a_note_selects_it_before_editing(self) -> None:
        self._add_note(60, 256)
        note_id = self.stave.events[0].id
        hands: list[str] = []
        self.canvas.note_hand_changed.connect(hands.append)
        geometry = self.canvas._stave_render_data(self.system, self.stave, self.left_mm).notes.geometries[0]
        point_mm = QPointF(
            sum(x_mm for x_mm, _ in geometry.head.points_mm) / len(geometry.head.points_mm),
            sum(y_mm for _, y_mm in geometry.head.points_mm) / len(geometry.head.points_mm),
        )
        point_px = point_mm * self.canvas.pixels_per_mm
        press_event = QMouseEvent(
            QEvent.Type.MouseButtonPress,
            point_px,
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
        release_event = QMouseEvent(
            QEvent.Type.MouseButtonRelease,
            point_px,
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.NoModifier,
        )

        self.canvas.mousePressEvent(press_event)
        self.assertEqual(self.canvas._selected_note_ids, {note_id})
        self.assertEqual(hands, ["left"])
        self.canvas.mouseReleaseEvent(release_event)

    def test_right_click_deletes_a_note_on_release(self) -> None:
        self._add_note(60, 256)
        point_mm = self._point(60, 256)

        self.canvas.mousePressEvent(self._mouse_event(
            QEvent.Type.MouseButtonPress,
            point_mm,
            Qt.MouseButton.RightButton,
            Qt.MouseButton.RightButton,
        ))

        self.assertEqual(len(self.stave.events), 1)
        self.canvas.mouseReleaseEvent(self._mouse_event(
            QEvent.Type.MouseButtonRelease,
            point_mm,
            Qt.MouseButton.RightButton,
            Qt.MouseButton.NoButton,
        ))

        self.assertEqual(self.stave.events, [])

    def test_right_drag_selects_notes_without_deleting_them(self) -> None:
        self._add_note(60, 256)
        self._add_note(64, 512)
        start_mm = self._point(59, 192)
        end_mm = self._point(61, 320)

        self.canvas.mousePressEvent(self._mouse_event(
            QEvent.Type.MouseButtonPress,
            start_mm,
            Qt.MouseButton.RightButton,
            Qt.MouseButton.RightButton,
        ))
        self.canvas.mouseMoveEvent(self._mouse_event(
            QEvent.Type.MouseMove,
            end_mm,
            Qt.MouseButton.NoButton,
            Qt.MouseButton.RightButton,
        ))
        self.canvas.mouseReleaseEvent(self._mouse_event(
            QEvent.Type.MouseButtonRelease,
            end_mm,
            Qt.MouseButton.RightButton,
            Qt.MouseButton.NoButton,
        ))

        self.assertEqual(len(self.stave.events), 2)
        self.assertEqual(self.canvas._selected_note_ids, {self.stave.events[0].id})

    def test_right_click_clears_the_existing_selection(self) -> None:
        self._add_note(60, 256)
        self._add_note(64, 512)
        self.canvas._selected_note_ids = {note.id for note in self.stave.events}
        empty_point_mm = self._point(67, 768)

        self.canvas.mousePressEvent(self._mouse_event(
            QEvent.Type.MouseButtonPress,
            empty_point_mm,
            Qt.MouseButton.RightButton,
            Qt.MouseButton.RightButton,
        ))
        self.canvas.mouseReleaseEvent(self._mouse_event(
            QEvent.Type.MouseButtonRelease,
            empty_point_mm,
            Qt.MouseButton.RightButton,
            Qt.MouseButton.NoButton,
        ))

        self.assertEqual([(note.time, note.pitch) for note in self.stave.events], [(256, 60), (512, 64)])
        self.assertEqual(self.canvas._selected_note_ids, set())

    def test_inserting_a_note_clears_the_previous_selection(self) -> None:
        self._add_note(60, 256)
        self.canvas._selected_note_ids = {self.stave.events[0].id}
        point_px = self._point(64, 512) * self.canvas.pixels_per_mm
        press_event = QMouseEvent(
            QEvent.Type.MouseButtonPress,
            point_px,
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
        release_event = QMouseEvent(
            QEvent.Type.MouseButtonRelease,
            point_px,
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.NoModifier,
        )

        self.canvas.mousePressEvent(press_event)

        self.assertEqual(self.canvas._selected_note_ids, set())
        self.canvas.mouseReleaseEvent(release_event)
        self.assertEqual([(note.time, note.pitch) for note in self.stave.events], [(256, 60), (512, 64)])

    def test_middle_mouse_button_starts_and_stops_panning(self) -> None:
        paper_view = PaperView()
        paper_view.setWidget(self.canvas)
        position = QPointF(100, 100)
        press_event = QMouseEvent(
            QEvent.Type.MouseButtonPress,
            position,
            Qt.MouseButton.MiddleButton,
            Qt.MouseButton.MiddleButton,
            Qt.KeyboardModifier.NoModifier,
        )
        release_event = QMouseEvent(
            QEvent.Type.MouseButtonRelease,
            position,
            Qt.MouseButton.MiddleButton,
            Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.NoModifier,
        )

        self.assertTrue(paper_view.eventFilter(self.canvas, press_event))
        self.assertTrue(paper_view._middle_button_panning)
        self.assertTrue(paper_view.eventFilter(self.canvas, release_event))
        self.assertFalse(paper_view._middle_button_panning)

    def test_control_wheel_zooms_the_paper(self) -> None:
        paper_view = PaperView()
        paper_view.setWidget(self.canvas)
        wheel_event = QWheelEvent(
            QPointF(100, 100),
            QPointF(100, 100),
            QPoint(),
            QPoint(0, 120),
            Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.ControlModifier,
            Qt.ScrollPhase.ScrollUpdate,
            False,
        )

        paper_view.wheelEvent(wheel_event)

        self.assertEqual(self.canvas.zoom, PaperView.ZOOM_FACTOR)

    def test_paper_view_keeps_its_editor_surround_dark(self) -> None:
        paper_view = PaperView()
        paper_view.setWidget(self.canvas)

        paper_view.set_editor_background("#252a30")

        self.assertEqual(paper_view.viewport().palette().color(paper_view.viewport().backgroundRole()), QColor("#252a30"))
        self.assertEqual(paper_view.widget().palette().color(paper_view.widget().backgroundRole()), QColor("#252a30"))

    def test_copy_cut_and_paste_preserve_original_note_pitches(self) -> None:
        self._add_note(60, 256)
        self._add_note(64, 384)
        original_ids = {note.id for note in self.stave.events}
        self.canvas._selected_note_ids = original_ids

        self.assertTrue(self.canvas.copy_selection())
        self.assertTrue(self.canvas.cut_selection())
        self.assertEqual(self.stave.events, [])
        self.canvas.update_mouse_cursor(self._point(62, 512))

        self.assertTrue(self.canvas.paste_selection())

        self.assertEqual([(note.time, note.pitch) for note in self.stave.events], [(512, 60), (640, 64)])
        self.assertTrue(original_ids.isdisjoint({note.id for note in self.stave.events}))

    def test_paste_remaps_continuation_ids_before_right_click_deletion(self) -> None:
        self._add_note(60, 256)
        original = self.stave.events[0]
        original.continuation_id = original.id
        self.canvas._selected_note_ids = {original.id}

        self.assertTrue(self.canvas.copy_selection())
        self.canvas.update_mouse_cursor(self._point(60, 512))
        self.assertTrue(self.canvas.paste_selection())

        pasted = next(note for note in self.stave.events if note.time == 512)
        self.assertNotEqual(pasted.continuation_id, original.continuation_id)
        self.assertTrue(self.tool.on_right_click(self._point(60, 512)))
        self.assertEqual(self.stave.events, [original])

    def test_spacebar_requests_playback_from_the_mouse_time(self) -> None:
        requested_ticks: list[int] = []
        self.canvas.playback_toggle_requested.connect(requested_ticks.append)
        self.canvas.mouse_time = 1024

        self.canvas.keyPressEvent(QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_Space, Qt.KeyboardModifier.NoModifier))

        self.assertEqual(requested_ticks, [1024])

    def test_delete_selection_removes_notes_without_changing_clipboard(self) -> None:
        self._add_note(60, 256)
        self._add_note(64, 384)
        selected_id = self.stave.events[0].id
        self.canvas._clipboard_notes = [self.stave.events[1]]
        self.canvas._selected_note_ids = {selected_id}

        self.assertTrue(self.canvas.delete_selection())

        self.assertEqual([(note.time, note.pitch) for note in self.stave.events], [(384, 64)])
        self.assertEqual(self.canvas._clipboard_notes[0].pitch, 64)

    def test_transpose_selection_moves_every_selected_note_by_a_semitone(self) -> None:
        self._add_note(60, 256)
        self._add_note(64, 384)
        self.canvas._selected_note_ids = {note.id for note in self.stave.events}

        self.assertTrue(self.canvas.transpose_selection(1))

        self.assertEqual([(note.time, note.pitch) for note in self.stave.events], [(256, 61), (384, 65)])

    def test_shift_selection_moves_every_selected_note_by_the_input_snap(self) -> None:
        self._add_note(60, 256)
        self._add_note(64, 384)
        self.canvas._selected_note_ids = {note.id for note in self.stave.events}

        self.assertTrue(self.canvas.shift_selection_in_time(self.canvas.input_snap_ticks))

        self.assertEqual([(note.time, note.pitch) for note in self.stave.events], [(320, 60), (448, 64)])

    def test_selection_motion_is_rejected_when_it_would_overlap_an_unselected_note(self) -> None:
        self._add_note(60, 256)
        self._add_note(61, 256)
        self.canvas._selected_note_ids = {self.stave.events[0].id}

        self.assertFalse(self.canvas.transpose_selection(1))
        self.assertFalse(self.canvas.shift_selection_in_time(0))

        self.assertEqual([(note.time, note.pitch) for note in self.stave.events], [(256, 60), (256, 61)])
