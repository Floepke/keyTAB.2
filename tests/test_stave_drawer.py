from __future__ import annotations

import unittest
from unittest.mock import Mock

import cairo
from PySide6.QtWidgets import QApplication

from keytab2_model.document import NoteEvent, Stave, System
from keytab2_model import KeyTab2Document
from keytab2_model.base_grid import BaseGrid, grid_boundaries
from keytab2_model.layout import Layout
from ui.drawers.base import DrawCommandBuffer, DrawerBase
from ui.drawers.grid_drawer import GridDrawer
from ui.drawers.metrics import SystemMetrics
from ui.drawers.stave_drawer import StaveDrawer
from ui.drawers.stave_connector_drawer import StaveConnectorDrawer
from ui.drawers.time_signature_drawer import TimeSignatureDrawer
from ui.paper_canvas import PaperCanvas


class StaveDrawerTests(unittest.TestCase):
    def test_time_signature_drawer_uses_layout_fields_at_base_grid_segment_starts(self) -> None:
        context = Mock()
        context.text_extents.return_value = (0.0, -2.0, 4.0, 4.0, 4.0, 0.0)
        layout = Layout(scale=0.5, time_signature_indicator_type="classical & klavarskribo")
        layout.time_signature_indicator_lane_width_mm = 30.0
        layout.time_signature_indicator_classic_font.family = "Courier New"
        layout.time_signature_indicator_klavarskribo_font.family = "DejaVu Sans"
        system = System(start_tick=0, end_tick=4096, top_mm=20.0, height_mm=80.0)
        grids = [BaseGrid(numerator=3, denominator=4, beat_grouping=[1, 3], measure_amount=1), BaseGrid(numerator=2, denominator=4, measure_amount=1)]

        TimeSignatureDrawer(context, (0.0, 0.0, 0.0)).draw(system, layout, 1.0, 40.0, grids, 256)

        self.assertEqual(context.show_text.call_count, 14)
        self.assertIn(unittest.mock.call(0.5), context.set_line_width.call_args_list)
        self.assertIn(unittest.mock.call(1.0), context.set_line_width.call_args_list)
        self.assertIn(unittest.mock.call(35.25, 20.0), context.move_to.call_args_list)

    def test_classical_time_signature_keeps_numbers_clear_of_its_divider(self) -> None:
        context = Mock()
        context.text_extents.return_value = (0.0, -3.0, 4.0, 4.0, 4.0, 0.0)
        layout = Layout(scale=0.5, time_signature_indicator_type="classical")
        system = System(start_tick=0, end_tick=1024, top_mm=20.0, height_mm=40.0)

        TimeSignatureDrawer(context, (0.0, 0.0, 0.0)).draw(
            system,
            layout,
            1.0,
            40.0,
            [BaseGrid(measure_amount=1)],
            256,
        )

        text_positions = [call.args for call in context.move_to.call_args_list if call.args[1] != 20.0]
        self.assertEqual([position[1] for position in text_positions], [17.75, 24.25])

    def test_time_signature_ducks_its_entire_lane_left_of_notation(self) -> None:
        context = Mock()
        collision_index = Mock()
        collision_index.left_extent_mm.return_value = 25.0
        layout = Layout(scale=0.5, time_signature_indicator_type="classical")
        system = System(start_tick=0, end_tick=1024, top_mm=20.0, height_mm=40.0)
        drawer = TimeSignatureDrawer(context, (0.0, 0.0, 0.0))
        drawer._draw_classical = Mock()

        drawer.draw(system, layout, 1.0, 40.0, [BaseGrid(measure_amount=1)], 256, collision_index)

        self.assertEqual(drawer._draw_classical.call_args.args[3], 21.333333333333332)
        collision_index.left_extent_mm.assert_called_once_with(0, 1024, 40.0)

    def test_time_signature_drawer_honors_visibility(self) -> None:
        context = Mock()
        layout = Layout(time_signature_visible=False)
        system = System(start_tick=0, end_tick=1024, top_mm=20.0, height_mm=40.0)

        TimeSignatureDrawer(context, (0.0, 0.0, 0.0)).draw(
            system,
            layout,
            1.0,
            40.0,
            [BaseGrid(measure_amount=1)],
            256,
        )

        context.attach_mock(Mock(), "unused")
        self.assertEqual(context.method_calls, [])
    def test_midi_bodies_are_drawn_before_stave_lines(self) -> None:
        paint_order: list[str] = []
        command_buffer = DrawCommandBuffer()
        command_buffer.add(("stave_line",), lambda: paint_order.append("stave"))
        command_buffer.add(("midi_body",), lambda: paint_order.append("midi"))

        command_buffer.flush()

        self.assertEqual(paint_order, ["midi", "stave"])

    def test_drawer_stroke_options_use_official_pycairo_constants(self) -> None:
        context = Mock()
        drawer = DrawerBase(context, (0.0, 0.0, 0.0))

        drawer.draw_line(0.0, 0.0, 5.0, 5.0, cap="square")
        drawer.draw_poly_line([(0.0, 0.0), (5.0, 5.0), (10.0, 0.0)], join_style="bevel")

        self.assertIn(unittest.mock.call(cairo.LINE_CAP_SQUARE), context.set_line_cap.call_args_list)
        self.assertIn(unittest.mock.call(cairo.LINE_JOIN_BEVEL), context.set_line_join.call_args_list)

    def test_three_line_group_contains_f_sharp_g_sharp_and_a_sharp(self) -> None:
        key_numbers = {10, 12, 14}
        key_classes = {(key_number - 1) % 12 for key_number in key_numbers}

        self.assertEqual(key_classes, StaveDrawer.THREE_LINE_KEY_CLASSES)

    def test_stave_drawer_leaves_horizontal_boundaries_to_grid_drawer(self) -> None:
        context = Mock()
        system = System(top_mm=20.0, height_mm=40.0)
        stave = Stave(pitch_range=[61, 61])

        StaveDrawer(context, (0.0, 0.0, 0.0)).draw(system, stave, Layout(), 10.0)

        self.assertEqual(
            context.move_to.call_args_list,
            [unittest.mock.call(10.0, 20.0), unittest.mock.call(11.32, 20.0)],
        )
        self.assertEqual(
            context.line_to.call_args_list,
            [unittest.mock.call(10.0, 60.0), unittest.mock.call(11.32, 60.0)],
        )

    def test_stave_drawer_draws_omitted_black_key_groups_as_ledgers(self) -> None:
        context = Mock()
        system = System(start_tick=0, end_tick=1024, top_mm=20.0, height_mm=40.0)
        stave = Stave(pitch_range=[60, 72], events=[NoteEvent(time=512, duration=128, pitch=58)])

        StaveDrawer(context, (0.0, 0.0, 0.0)).draw(system, stave, Layout(scale=0.5), 10.0)

        self.assertIn(unittest.mock.call(7.0, 38.0), context.move_to.call_args_list)
        self.assertIn(unittest.mock.call(7.0, 44.5), context.line_to.call_args_list)

    def test_stave_drawer_draws_ledger_groups_at_continuation_dots(self) -> None:
        context = Mock()
        system = System(start_tick=0, end_tick=1024, top_mm=20.0, height_mm=40.0)
        note = NoteEvent(time=512, duration=128, pitch=58)
        stave = Stave(pitch_range=[60, 72], events=[note])

        StaveDrawer(context, (0.0, 0.0, 0.0)).draw(
            system,
            stave,
            Layout(scale=0.5),
            10.0,
            {note.id: ((7.0, 50.0),)},
        )

        self.assertIn(unittest.mock.call(7.0, 47.0), context.move_to.call_args_list)
        self.assertIn(unittest.mock.call(7.0, 53.5), context.line_to.call_args_list)

    def test_ledger_lines_expand_system_stave_bounds(self) -> None:
        system = System(start_tick=0, end_tick=1024)
        stave = Stave(pitch_range=[60, 72], events=[NoteEvent(time=512, duration=128, pitch=58)])
        drawer = StaveDrawer(Mock(), (0.0, 0.0, 0.0))

        natural_bounds = drawer.bounds(stave, Layout(scale=0.5), 10.0)
        ledger_bounds = drawer.bounds(stave, Layout(scale=0.5), 10.0, system)

        self.assertIsNotNone(natural_bounds)
        self.assertIsNotNone(ledger_bounds)
        self.assertLess(ledger_bounds[0], natural_bounds[0])

    def test_piano_edge_notes_use_the_special_outer_geometry(self) -> None:
        stave = Stave(pitch_range=[36, 84])
        system = System(start_tick=0, end_tick=1024, staves=[stave])
        stave.events.append(NoteEvent(time=256, duration=64, pitch=108))

        self.assertEqual(stave.ledger_line_pitches_for_pitch(21), (18, 20, 22, 25, 27, 30, 32, 34))
        self.assertEqual(stave.ledger_line_pitches_for_pitch(108), (90, 92, 94, 97, 99, 102, 104, 106, 109, 111))
        self.assertIn(108, stave.line_pitches(system))

    def test_midi_only_ledger_lines_are_grey(self) -> None:
        context = Mock()
        system = System(start_tick=0, end_tick=1024, top_mm=20.0, height_mm=40.0)
        stave = Stave(pitch_range=[60, 72], events=[NoteEvent(time=512, duration=128, pitch=110)])

        StaveDrawer(context, (0.0, 0.0, 0.0)).draw(system, stave, Layout(scale=0.5), 10.0)

        self.assertIn(unittest.mock.call(*StaveDrawer.MIDI_ONLY_LEDGER_COLOR), context.set_source_rgb.call_args_list)

    def test_midi_only_ledger_lines_can_be_excluded_from_export(self) -> None:
        context = Mock()
        system = System(start_tick=0, end_tick=1024, top_mm=20.0, height_mm=40.0)
        stave = Stave(pitch_range=[60, 72], events=[NoteEvent(time=512, duration=128, pitch=110)])

        StaveDrawer(context, (0.0, 0.0, 0.0)).draw(
            system,
            stave,
            Layout(scale=0.5),
            10.0,
            include_midi_only_ledgers=False,
        )

        self.assertNotIn(unittest.mock.call(*StaveDrawer.MIDI_ONLY_LEDGER_COLOR), context.set_source_rgb.call_args_list)

    def test_in_range_notes_do_not_create_ledger_lines(self) -> None:
        system = System(start_tick=0, end_tick=1024)
        stave = Stave(pitch_range=[36, 84], events=[NoteEvent(time=256, duration=64, pitch=64)])

        self.assertEqual(stave.ledger_line_pitches(system), ())

    def test_stave_range_ending_at_84_includes_the_following_c_sharp_d_sharp_group(self) -> None:
        stave = Stave(pitch_range=[36, 84])

        self.assertIn(85, stave.natural_line_pitches())
        self.assertIn(87, stave.natural_line_pitches())

    def test_pitch_positions_use_fixed_spacing_with_b_and_e_gaps(self) -> None:
        semitone_mm = 2.0 * 0.5
        x_e = StaveDrawer.pitch_to_x_mm(64, 60, 10.0, semitone_mm)
        x_f = StaveDrawer.pitch_to_x_mm(65, 60, 10.0, semitone_mm)
        x_f_sharp = StaveDrawer.pitch_to_x_mm(66, 60, 10.0, semitone_mm)
        x_b = StaveDrawer.pitch_to_x_mm(71, 60, 10.0, semitone_mm)
        x_c = StaveDrawer.pitch_to_x_mm(72, 60, 10.0, semitone_mm)

        self.assertEqual(x_f - x_e, 2.0 * semitone_mm)
        self.assertEqual(x_f_sharp - x_f, semitone_mm)
        self.assertEqual(x_c - x_b, 2.0 * semitone_mm)

    def test_measure_numbers_use_layout_font_on_stave_right(self) -> None:
        context = Mock()
        layout = Layout(scale=0.5)
        layout.measure_numbering_font.family = "Courier New"
        layout.measure_numbering_font.size_pt = 24.0
        layout.measure_numbering_font.bold = True
        system = System(start_tick=0, end_tick=1024, first_measure_number=7, top_mm=20.0, height_mm=40.0)
        metrics = SystemMetrics.from_layout(layout)
        context.text_extents.return_value = (0.0, -3.0, 5.0, 4.0, 5.0, 0.0)

        GridDrawer(context, (0.0, 0.0, 0.0)).draw(system, layout, 1.0, 10.0, 30.0, (0, 1024), (), metrics)

        self.assertIn(
            unittest.mock.call(30.0 + metrics.measure_number_offset_mm, 21.0),
            context.move_to.call_args_list,
        )

    def test_grid_drawer_can_suppress_measure_numbers_for_nonfinal_staves(self) -> None:
        context = Mock()
        context.text_extents.return_value = (0.0, -3.0, 5.0, 4.0, 5.0, 0.0)
        system = System(start_tick=0, end_tick=1024, top_mm=20.0, height_mm=40.0)

        GridDrawer(context, (0.0, 0.0, 0.0)).draw(
            system, Layout(scale=0.5), 1.0, 10.0, 30.0, (0, 1024), (), SystemMetrics.from_layout(Layout(scale=0.5)), show_measure_numbers=False
        )

        context.show_text.assert_not_called()

    def test_stave_connectors_join_adjacent_stave_barlines(self) -> None:
        context = Mock()
        system = System(start_tick=0, end_tick=1024, top_mm=20.0, height_mm=40.0)

        StaveConnectorDrawer(context, (0.0, 0.0, 0.0)).draw(
            system, [(10.0, 30.0), (40.0, 60.0)], (0, 1024), 0.5, 1.0
        )

        self.assertIn(unittest.mock.call(30.0, 20.0), context.move_to.call_args_list)
        self.assertIn(unittest.mock.call(40.0, 20.0), context.line_to.call_args_list)
        self.assertIn(unittest.mock.call(30.0, 60.0), context.move_to.call_args_list)
        self.assertIn(unittest.mock.call(40.0, 60.0), context.line_to.call_args_list)

    def test_closing_system_barline_is_normal_and_not_numbered(self) -> None:
        context = Mock()
        context.text_extents.return_value = (0.0, -3.0, 5.0, 4.0, 5.0, 0.0)
        system = System(start_tick=0, end_tick=1024, top_mm=20.0, height_mm=40.0)
        layout = Layout(scale=0.5)

        GridDrawer(context, (0.0, 0.0, 0.0)).draw(
            system,
            layout,
            1.0,
            10.0,
            30.0,
            (0, 1024),
            (),
            SystemMetrics.from_layout(layout),
        )

        self.assertEqual(context.show_text.call_count, 1)
        self.assertIn(unittest.mock.call(10.0, 60.0), context.move_to.call_args_list)
        self.assertNotIn(unittest.mock.call(10.0, 59.375), context.move_to.call_args_list)

    def test_final_system_uses_a_double_thickness_end_barline(self) -> None:
        context = Mock()
        context.text_extents.return_value = (0.0, -3.0, 5.0, 4.0, 5.0, 0.0)
        layout = Layout(scale=0.5, grid_barline_thickness_mm=1.25)
        system = System(start_tick=0, end_tick=1024, top_mm=20.0, height_mm=40.0)

        GridDrawer(context, (0.0, 0.0, 0.0)).draw(
            system, layout, 1.0, 10.0, 30.0, (0, 1024), (), SystemMetrics.from_layout(layout), is_final_system=True
        )

        self.assertIn(unittest.mock.call(1.25), context.set_line_width.call_args_list)
        self.assertIn(unittest.mock.call(10.0, 60.0), context.move_to.call_args_list)

    def test_grid_drawer_uses_beat_group_boundaries(self) -> None:
        context = Mock()
        context.text_extents.return_value = (0.0, -3.0, 5.0, 4.0, 5.0, 0.0)
        layout = Layout(scale=0.5)
        system = System(start_tick=0, end_tick=896, top_mm=20.0, height_mm=56.0)
        metrics = SystemMetrics.from_layout(layout)
        measure_starts, group_starts = grid_boundaries(
            [BaseGrid(numerator=7, denominator=8, beat_grouping=[1, 2, 3, 1, 2, 3, 4], measure_amount=1)],
            256,
        )

        GridDrawer(context, (0.0, 0.0, 0.0)).draw(system, layout, 1.0, 10.0, 30.0, measure_starts, group_starts, metrics)

        self.assertIn(unittest.mock.call(10.0, 44.0), context.move_to.call_args_list)

    def test_grid_drawer_splits_lines_around_notation_geometry(self) -> None:
        context = Mock()
        context.text_extents.return_value = (0.0, -3.0, 5.0, 4.0, 5.0, 0.0)
        collision_index = Mock()
        collision_index.horizontal_occlusion_intervals.return_value = ((15.0, 20.0),)
        collision_index.right_extent_mm.return_value = 30.0
        layout = Layout(scale=0.5)
        system = System(start_tick=0, end_tick=1024, top_mm=20.0, height_mm=40.0)

        GridDrawer(context, (0.0, 0.0, 0.0)).draw(
            system, layout, 1.0, 10.0, 30.0, (0, 1024), (), SystemMetrics.from_layout(layout), collision_index
        )

        self.assertIn(unittest.mock.call(10.0, 20.0), context.move_to.call_args_list)
        self.assertIn(unittest.mock.call(20.0, 20.0), context.move_to.call_args_list)
        self.assertIn(unittest.mock.call(20.0, 1.3125), collision_index.horizontal_occlusion_intervals.call_args_list)

    def test_system_culling_includes_controls_and_excludes_distant_systems(self) -> None:
        layout = Layout(scale=0.5)
        metrics = SystemMetrics.from_layout(layout)
        system = System(top_mm=20.0, height_mm=40.0)

        self.assertFalse(PaperCanvas._system_intersects_visible_region(system, metrics, 14.0, 16.0))
        self.assertTrue(PaperCanvas._system_intersects_visible_region(system, metrics, 50.0, 55.0))
        self.assertFalse(PaperCanvas._system_intersects_visible_region(system, metrics, 70.0, 80.0))

    def test_systems_use_ledger_aware_widths_with_equal_remaining_gaps(self) -> None:
        application = QApplication.instance() or QApplication([])
        del application
        document = KeyTab2Document.new()
        page = document.pages[0]
        leading = page.systems[0]
        following = document.split_system_at(page.id, leading.id, 4096)
        leading.staves[0].events.append(NoteEvent(time=0, duration=64, pitch=108))
        leading.staves[0].touch()
        drawer = StaveDrawer(Mock(), (0.0, 0.0, 0.0))

        canvas = PaperCanvas(document)
        columns = [canvas._system_column_bounds(page, system) for system in page.systems]
        first_width = columns[0][1] - columns[0][0]
        second_width = columns[1][1] - columns[1][0]
        self.assertGreater(first_width, second_width)
        self.assertLess(columns[0][1], columns[1][0])
        outer_left = columns[0][0] - page.systems[0].left_margin_mm - document.layout.page_left_margin_mm
        inner_gap = columns[1][0] - page.systems[1].left_margin_mm - (columns[0][1] + page.systems[0].right_margin_mm)
        outer_right = page.width_mm - document.layout.page_right_margin_mm - page.systems[1].right_margin_mm - columns[1][1]
        self.assertAlmostEqual(outer_left, inner_gap)
        self.assertAlmostEqual(inner_gap, outer_right)
        for system, column in zip(page.systems, columns, strict=True):
            left_mm = PaperCanvas._centered_stave_left_positions(system, drawer, document.layout, *column)[0]
            bounds = drawer.bounds(system.staves[0], document.layout, left_mm, system)
            self.assertIsNotNone(bounds)
            self.assertAlmostEqual((bounds[0] + bounds[1]) * 0.5, sum(column) * 0.5)

    def test_one_system_is_centered_between_page_margins(self) -> None:
        application = QApplication.instance() or QApplication([])
        del application
        document = KeyTab2Document.new()
        page = document.pages[0]
        system = page.systems[0]
        canvas = PaperCanvas(document)
        left_mm, right_mm = canvas._system_column_bounds(page, system)

        left_space = left_mm - system.left_margin_mm - document.layout.page_left_margin_mm
        right_space = page.width_mm - document.layout.page_right_margin_mm - system.right_margin_mm - right_mm

        self.assertAlmostEqual(left_space, right_space)

    def test_multiple_staves_are_grouped_and_centered_at_their_own_scales(self) -> None:
        document = KeyTab2Document.new()
        system = document.pages[0].systems[0]
        system.staves.append(Stave(name="Flute", pitch_range=[60, 72], scale=0.5))
        drawer = StaveDrawer(Mock(), (0.0, 0.0, 0.0))

        canvas = PaperCanvas(document)
        column = canvas._system_column_bounds(document.pages[0], system)
        positions = PaperCanvas._centered_stave_left_positions(system, drawer, document.layout, *column)
        first_bounds = drawer.bounds(system.staves[0], document.layout, positions[0])
        second_bounds = drawer.bounds(system.staves[1], document.layout, positions[1])

        self.assertIsNotNone(first_bounds)
        self.assertIsNotNone(second_bounds)
        self.assertAlmostEqual(second_bounds[0] - first_bounds[1], PaperCanvas.STAVE_GAP_MM)
        self.assertAlmostEqual((first_bounds[0] + second_bounds[1]) * 0.5, sum(column) * 0.5)
        self.assertEqual(StaveDrawer.effective_scale(document.layout, system.staves[1]), document.layout.scale * 0.5)


if __name__ == "__main__":
    unittest.main()