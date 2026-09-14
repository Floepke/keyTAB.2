from __future__ import annotations

import unittest

from PySide6.QtCore import QPointF
from PySide6.QtWidgets import QApplication

from keytab2_model import BeamEvent, KeyTab2Document, NoteEvent, Stave, TempoEvent
from ui.drawers.stave_drawer import StaveDrawer
from ui.paper_canvas import PaperCanvas


class TempoToolTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.application = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.document = KeyTab2Document.new()
        self.canvas = PaperCanvas(self.document)
        self.system = self.document.pages[0].systems[0]
        self.stave = self.system.staves[0]
        self.canvas.select_tempo_mode()
        self.tool = self.canvas._tool_manager.active_tool

    def _stave_point(self, pitch: int, tick: int) -> QPointF:
        left_mm = self.canvas.stave_left_mm(self.system, self.stave)
        semitone_mm = self.document.layout.engraving_mm(2.0, self.stave.scale)
        return QPointF(
            StaveDrawer.pitch_to_x_mm(pitch, self.stave.pitch_range[0], left_mm, semitone_mm),
            self.canvas._time_to_y_mm(self.system, tick),
        )

    def test_creates_and_resizes_a_tempo_marker(self) -> None:
        start = self._stave_point(60, 512)
        end = self._stave_point(60, 768)

        self.assertTrue(self.tool.on_left_press(start))
        self.assertTrue(self.tool.on_left_drag(end))
        self.assertTrue(self.tool.on_left_release(end))

        tempo = self.document.timeline_events[-1]
        self.assertIsInstance(tempo, TempoEvent)
        self.assertEqual((tempo.start_tick, tempo.duration_ticks, tempo.tempo), (512, 256, 60))
        right_outer_stave_x_mm = StaveDrawer(None, self.canvas.INK_COLOR).bounds(
            self.stave,
            self.document.layout,
            self.canvas.stave_left_mm(self.system, self.stave),
        )[1]
        marker_x_mm, marker_y_mm = self.canvas._tempo_marker_position(self.system, right_outer_stave_x_mm, tempo)
        self.assertIs(self.canvas.tempo_target_at(QPointF(marker_x_mm, marker_y_mm)), tempo)

    def test_right_click_deletes_later_but_not_initial_tempo(self) -> None:
        tempo = TempoEvent(start_tick=512, duration_ticks=256, tempo=90)
        self.document.timeline_events.append(tempo)
        right_outer_stave_x_mm = StaveDrawer(None, self.canvas.INK_COLOR).bounds(
            self.stave,
            self.document.layout,
            self.canvas.stave_left_mm(self.system, self.stave),
        )[1]
        marker_x_mm, marker_y_mm = self.canvas._tempo_marker_position(self.system, right_outer_stave_x_mm, tempo)

        self.assertTrue(self.tool.on_right_click(QPointF(marker_x_mm, marker_y_mm)))
        self.assertNotIn(tempo, self.document.timeline_events)
        initial = self.document.timeline_events[0]
        initial_x_mm, initial_y_mm = self.canvas._tempo_marker_position(self.system, right_outer_stave_x_mm, initial)
        self.assertFalse(self.tool.on_right_click(QPointF(initial_x_mm, initial_y_mm)))

    def test_marker_anchors_to_the_final_stave_outer_right_edge(self) -> None:
        final_stave = Stave(name="Flute", pitch_range=[60, 72], scale=0.5)
        self.system.staves.append(final_stave)
        tempo = TempoEvent(start_tick=512, duration_ticks=256, tempo=90, x_offset_mm=2.0)
        self.document.timeline_events.append(tempo)
        drawer = StaveDrawer(None, self.canvas.INK_COLOR)
        first_stave_bounds = drawer.bounds(
            self.stave,
            self.document.layout,
            self.canvas.stave_left_mm(self.system, self.stave),
        )
        final_stave_bounds = drawer.bounds(
            final_stave,
            self.document.layout,
            self.canvas.stave_left_mm(self.system, final_stave),
        )

        marker_x_mm, marker_y_mm = self.canvas._tempo_marker_position(self.system, final_stave_bounds[1], tempo)

        self.assertGreater(final_stave_bounds[1], first_stave_bounds[1])
        self.assertEqual(marker_x_mm, final_stave_bounds[1] + tempo.x_offset_mm)
        self.assertIs(self.canvas.tempo_target_at(QPointF(marker_x_mm, marker_y_mm)), tempo)

    def test_marker_ducks_past_note_and_beam_geometry(self) -> None:
        self.stave.events.extend([
            NoteEvent(time=512, duration=256, pitch=96, hand="right"),
            NoteEvent(time=640, duration=128, pitch=94, hand="right"),
            BeamEvent(time=512, duration=256, hand="right"),
        ])
        tempo = TempoEvent(start_tick=512, duration_ticks=256, tempo=90)
        self.document.timeline_events.append(tempo)
        right_outer_stave_x_mm = StaveDrawer(None, self.canvas.INK_COLOR).bounds(
            self.stave,
            self.document.layout,
            self.canvas.stave_left_mm(self.system, self.stave),
        )[1]
        render_data = self.canvas._stave_render_data(self.system, self.stave, self.canvas.stave_left_mm(self.system, self.stave))

        marker_x_mm, _ = self.canvas._tempo_marker_position(
            self.system,
            right_outer_stave_x_mm,
            tempo,
            render_data.collision_index,
            self.stave.scale,
        )

        self.assertGreater(
            marker_x_mm,
            render_data.collision_index.right_extent_mm(512, 768, right_outer_stave_x_mm),
        )


if __name__ == "__main__":
    unittest.main()