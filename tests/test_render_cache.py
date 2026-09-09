from __future__ import annotations

import unittest
from tempfile import TemporaryDirectory
from unittest.mock import patch

from PySide6.QtCore import QPoint, QPointF, QRect
from PySide6.QtWidgets import QApplication

from keytab2_model import BaseGrid, BeamEvent, KeyTab2Document, NoteEvent, SlurEvent, Stave
from ui.drawers.stave_drawer import StaveDrawer
from ui.drawers.note_drawer import NoteDrawer
from ui.drawers.base import DrawCommandBuffer, DrawerBase
from ui.paper_canvas import PaperCanvas
from ui.render_cache import build_stave_render_data


class RenderCacheTests(unittest.TestCase):
    def test_continuation_geometry_omits_the_second_head_and_first_stop(self) -> None:
        document = KeyTab2Document.new()
        page = document.pages[0]
        system = page.systems[0]
        system.staves[0].events.append(NoteEvent(time=1000, duration=128, pitch=60))
        following_system = document.split_system_at(page.id, system.id, 1024)
        leading_data = build_stave_render_data(system, system.staves[0], document.layout, 10.0, document.time_per_quarter * 4)
        following_data = build_stave_render_data(following_system, following_system.staves[0], document.layout, 10.0, document.time_per_quarter * 4)
        context = unittest.mock.Mock()
        drawer = NoteDrawer(context, (0.0, 0.0, 0.0))

        drawer.draw(leading_data.notes.geometries[0], 1.0, show_body=False, show_head=False, show_stem=False, show_stop=True, show_continuation_dots=False)
        drawer.draw(following_data.notes.geometries[0], 1.0, show_body=False, show_head=True, show_stem=False, show_stop=False, show_continuation_dots=False)

        self.assertEqual(context.stroke.call_count, 0)

    def test_page_metadata_draws_title_only_on_first_page_and_footer_on_every_page(self) -> None:
        document = KeyTab2Document.new()
        document.score_info.title = "Prelude"
        document.score_info.composer = "J. S. Bach"
        document.score_info.copyright = "Public domain"
        page = document.pages[0]
        document.layout.page_width_mm = 55.0
        page.width_mm = 55.0
        following = document.split_system_at(page.id, page.systems[0].id, 1024)
        later_page = next(candidate for candidate in document.pages if following in candidate.systems)
        canvas = PaperCanvas(document)

        first_context = unittest.mock.Mock()
        first_context.text_extents.return_value = (0.0, -3.0, 10.0, 5.0, 0.0, 0.0)
        first_commands = DrawCommandBuffer()
        canvas._draw_page_metadata(
            DrawerBase(first_context, canvas.INK_COLOR, first_commands),
            page,
            0,
            0.0,
            page.width_mm,
            0.0,
            page.height_mm,
        )
        first_commands.flush()

        later_context = unittest.mock.Mock()
        later_commands = DrawCommandBuffer()
        canvas._draw_page_metadata(
            DrawerBase(later_context, canvas.INK_COLOR, later_commands),
            later_page,
            1,
            0.0,
            later_page.width_mm,
            0.0,
            later_page.height_mm,
        )
        later_commands.flush()

        self.assertEqual(first_context.show_text.call_args_list[0].args[0], "Prelude")
        self.assertEqual(first_context.show_text.call_args_list[1].args[0], "J. S. Bach")
        self.assertIn("Page 1 of 2 - Prelude - Public domain", first_context.show_text.call_args_list[2].args[0])
        self.assertIn(unittest.mock.call(10.0, 13.0), first_context.move_to.call_args_list)
        self.assertIn(unittest.mock.call(35.0, 13.0), first_context.move_to.call_args_list)
        self.assertEqual(later_context.show_text.call_count, 1)
        self.assertEqual(later_context.show_text.call_args.args[0], "Page 2 of 2 - Prelude - Public domain")
    @classmethod
    def setUpClass(cls) -> None:
        cls.application = QApplication.instance() or QApplication([])

    def test_pdf_export_includes_all_pages_without_snap_bands(self) -> None:
        document = KeyTab2Document.new()
        document.layout.page_width_mm = 55.0
        page = document.pages[0]
        page.width_mm = 55.0
        document.split_system_at(page.id, page.systems[0].id, 1024)
        canvas = PaperCanvas(document)

        with TemporaryDirectory() as directory, patch("ui.paper_canvas.SnapDrawer.draw") as draw_snap:
            output_path = f"{directory}/score.pdf"
            canvas.export_pdf(output_path)
            with open(output_path, "rb") as output:
                self.assertTrue(output.read(5).startswith(b"%PDF-"))

        self.assertEqual(len(document.pages), 2)
        draw_snap.assert_not_called()

    def test_pdf_export_excludes_midi_only_ledger_lines(self) -> None:
        document = KeyTab2Document.new()
        document.pages[0].systems[0].staves[0].events.append(NoteEvent(time=256, duration=64, pitch=110))
        canvas = PaperCanvas(document)

        with TemporaryDirectory() as directory, patch("ui.paper_canvas.StaveDrawer.draw") as draw_stave:
            canvas.export_pdf(f"{directory}/score.pdf")

        self.assertTrue(draw_stave.called)
        self.assertTrue(all(call.kwargs["include_midi_only_ledgers"] is False for call in draw_stave.call_args_list))

    def test_note_geometry_includes_stop_and_barline_continuation_dot(self) -> None:
        document = KeyTab2Document.new()
        system = document.pages[0].systems[0]
        stave = system.staves[0]
        stave.events.append(NoteEvent(time=0, duration=2048, pitch=60))

        data = build_stave_render_data(system, stave, document.layout, 10.0, document.time_per_quarter * 4)
        note = data.notes.geometries[0]

        self.assertIsNotNone(note.stop_points_mm)
        self.assertEqual(len(note.continuation_dot_centres_mm), 1)

    def test_midi_body_does_not_occlude_a_grid_line(self) -> None:
        document = KeyTab2Document.new()
        system = document.pages[0].systems[0]
        stave = system.staves[0]
        stave.events.append(NoteEvent(time=0, duration=256, pitch=60))

        data = build_stave_render_data(system, stave, document.layout, 10.0, document.time_per_quarter * 4)

        self.assertTrue(data.collision_index.horizontal_occlusion_intervals(system.top_mm))
        self.assertEqual(data.collision_index.horizontal_occlusion_intervals(system.top_mm + system.height_mm / 8), ())

    def test_continuation_dots_include_same_hand_note_crossings(self) -> None:
        document = KeyTab2Document.new()
        system = document.pages[0].systems[0]
        stave = system.staves[0]
        stave.events.extend([
            NoteEvent(time=0, duration=1024, pitch=60, hand="left"),
            NoteEvent(time=256, duration=256, pitch=64, hand="left"),
        ])

        data = build_stave_render_data(system, stave, document.layout, 10.0, document.time_per_quarter * 4)

        self.assertEqual(len(data.notes.geometries[0].continuation_dot_centres_mm), 2)

    def test_following_note_removes_stop_and_beam_reuses_stems(self) -> None:
        document = KeyTab2Document.new()
        system = document.pages[0].systems[0]
        stave = system.staves[0]
        stave.events.extend([
            NoteEvent(time=0, duration=256, pitch=60, hand="left"),
            NoteEvent(time=256, duration=256, pitch=64, hand="left"),
            BeamEvent(time=0, duration=512, hand="left"),
        ])

        data = build_stave_render_data(system, stave, document.layout, 10.0, document.time_per_quarter * 4)

        self.assertIsNone(data.notes.geometries[0].stop_points_mm)
        self.assertEqual(len(data.beams.geometries), 1)
        self.assertEqual(len(data.beams.geometries[0].polygon_mm), 4)
        self.assertEqual(len(data.beams.geometries[0].segments_mm), 2)

    def test_notes_beam_automatically_inside_a_base_grid_beat_group(self) -> None:
        document = KeyTab2Document.new()
        system = document.pages[0].systems[0]
        stave = system.staves[0]
        stave.events.extend([
            NoteEvent(time=0, duration=128, pitch=60, hand="left"),
            NoteEvent(time=128, duration=128, pitch=64, hand="left"),
        ])

        data = build_stave_render_data(system, stave, document.layout, 10.0, document.time_per_quarter * 4, document.base_grid)

        self.assertEqual(len(data.beams.geometries), 1)
        self.assertTrue(data.beams.geometries[0].event_id.startswith("automatic-beam:"))

    def test_automatic_beams_follow_enabled_base_grid_lines(self) -> None:
        document = KeyTab2Document.new()
        document.base_grid = [BaseGrid(numerator=4, denominator=4, beat_grouping=[1, 2, 4], measure_amount=8)]
        system = document.pages[0].systems[0]
        stave = system.staves[0]
        stave.events.extend([
            NoteEvent(time=256, duration=128, pitch=60, hand="left"),
            NoteEvent(time=384, duration=128, pitch=64, hand="left"),
            NoteEvent(time=768, duration=128, pitch=67, hand="left"),
            NoteEvent(time=896, duration=128, pitch=71, hand="left"),
        ])

        data = build_stave_render_data(system, stave, document.layout, 10.0, document.time_per_quarter * 4, document.base_grid)

        self.assertEqual(
            [(beam.start_tick, beam.end_tick) for beam in data.beams.geometries],
            [(256, 768), (768, 1024)],
        )

    def test_same_hand_chord_uses_connected_outer_stem_for_beams(self) -> None:
        document = KeyTab2Document.new()
        system = document.pages[0].systems[0]
        stave = system.staves[0]
        stave.events.extend([
            NoteEvent(time=0.0, duration=128, pitch=60, hand="left"),
            NoteEvent(time=0.5, duration=128, pitch=64, hand="left"),
            NoteEvent(time=128.0, duration=128, pitch=62, hand="left"),
            NoteEvent(time=128.5, duration=128, pitch=67, hand="left"),
        ])

        data = build_stave_render_data(system, stave, document.layout, 10.0, document.time_per_quarter * 4, document.base_grid)

        chords = [note for note in data.notes.geometries if note.chord_connector is not None]
        interior_stems = [note for note in data.notes.geometries if note.chord_connector is None and note.stem[0] == note.stem[2]]
        beam = data.beams.geometries[0]

        self.assertEqual(len(chords), 2)
        self.assertEqual(len(interior_stems), 2)
        self.assertEqual(len(beam.polygon_mm), 4)
        self.assertEqual(len(beam.segments_mm), 2)
        self.assertTrue(all(chord.stem[2] < chord.stem[0] for chord in chords))

    def test_middle_note_stem_connects_to_the_outer_beam_rail(self) -> None:
        document = KeyTab2Document.new()
        system = document.pages[0].systems[0]
        stave = system.staves[0]
        stave.events.extend([
            NoteEvent(time=0, duration=64, pitch=60, hand="right"),
            NoteEvent(time=64, duration=64, pitch=67, hand="right"),
            NoteEvent(time=128, duration=64, pitch=62, hand="right"),
        ])

        beam = build_stave_render_data(system, stave, document.layout, 10.0, document.time_per_quarter * 4, document.base_grid).beams.geometries[0]

        middle_connector = beam.segments_mm[1]
        rail_start_x = (beam.polygon_mm[0][0] + beam.polygon_mm[3][0]) * 0.5
        rail_end_x = (beam.polygon_mm[1][0] + beam.polygon_mm[2][0]) * 0.5
        highest_note_stem_tip_x = max(note.stem[2] for note in build_stave_render_data(system, stave, document.layout, 10.0, document.time_per_quarter * 4, document.base_grid).notes.geometries)
        self.assertEqual(len(beam.polygon_mm), 4)
        self.assertNotEqual(middle_connector[0], middle_connector[2])
        self.assertAlmostEqual(rail_start_x, highest_note_stem_tip_x)
        self.assertAlmostEqual(middle_connector[2], (rail_start_x + rail_end_x) * 0.5)

    def test_notehead_attaches_to_time_line_and_uses_hand_aware_tilt(self) -> None:
        document = KeyTab2Document.new()
        system = document.pages[0].systems[0]
        stave = system.staves[0]
        stave.events.extend([
            NoteEvent(time=0, duration=256, pitch=60, hand="left"),
            NoteEvent(time=0, duration=256, pitch=62, hand="right"),
        ])

        data = build_stave_render_data(system, stave, document.layout, 10.0, document.time_per_quarter * 4)
        left, right = data.notes.geometries

        self.assertAlmostEqual(min(point[1] for point in left.head.points_mm), system.top_mm)
        self.assertNotAlmostEqual(left.head.points_mm[0][1] - system.top_mm, right.head.points_mm[0][1] - system.top_mm)

    def test_note_input_preview_uses_the_black_note_rule_geometry(self) -> None:
        document = KeyTab2Document.new()
        document.layout.black_note_rule = "above_stem"
        canvas = PaperCanvas(document)
        system = document.pages[0].systems[0]
        stave = system.staves[0]
        left_mm = canvas.stave_left_mm(system, stave)
        canvas._mouse_stave_target = (system, stave, left_mm)
        canvas.mouse_time = 256
        canvas.mouse_pitch = 61

        preview = canvas._preview_note_geometry(system, stave, left_mm)

        self.assertIsNotNone(preview)
        self.assertLess(min(y_mm for _, y_mm in preview.head.points_mm), canvas._time_to_y_mm(system, 256))

    def test_black_note_rule_raises_black_note_for_a_same_hand_white_chord_note(self) -> None:
        document = KeyTab2Document.new()
        document.layout.black_note_rule = "above_stem_if_chord_and_white_note_same_hand"
        system = document.pages[0].systems[0]
        stave = system.staves[0]
        stave.events.extend([
            NoteEvent(time=256, duration=64, pitch=60, hand="left"),
            NoteEvent(time=256, duration=64, pitch=61, hand="left"),
        ])

        data = build_stave_render_data(system, stave, document.layout, 10.0, document.time_per_quarter * 4)
        black_note = next(note for note in data.notes.geometries if note.event_id == stave.events[1].id)

        self.assertLess(min(y_mm for _, y_mm in black_note.head.points_mm), system.top_mm + 256 * system.height_mm / (system.end_tick - system.start_tick))

    def test_interval_index_queries_only_visible_notes_in_dense_stave(self) -> None:
        document = KeyTab2Document.new()
        system = document.pages[0].systems[0]
        system.end_tick = 200_000
        system.height_mm = 10_000.0
        stave = system.staves[0]
        stave.events.extend(
            NoteEvent(time=index * 10, duration=20, pitch=60 + index % 12)
            for index in range(20_000)
        )

        data = build_stave_render_data(system, stave, document.layout, 10.0, document.time_per_quarter * 4)
        visible_notes = data.notes_in_tick_range(100_000, 100_010)

        self.assertEqual(len(data.notes.geometries), 20_000)
        self.assertEqual(len(visible_notes), 2)

    def test_paper_tiles_are_reused_until_invalidated(self) -> None:
        app = QApplication.instance() or QApplication([])
        del app
        canvas = PaperCanvas(KeyTab2Document.new())
        tile = QRect(0, 0, canvas.TILE_SIZE_PX, canvas.TILE_SIZE_PX)

        first = canvas._tile_image(tile, 0, 0)
        second = canvas._tile_image(tile, 0, 0)

        self.assertIs(first, second)
        canvas.invalidate_render_cache()
        self.assertEqual(len(canvas._tile_cache), 0)

    def test_system_invalidation_keeps_neighboring_system_tiles(self) -> None:
        document = KeyTab2Document.new()
        leading = document.pages[0].systems[0]
        following = document.split_system_at(document.pages[0].id, leading.id, 1024)
        trailing = document.split_system_at(document.pages[0].id, following.id, 2048)
        canvas = PaperCanvas(document)
        page = document.pages[0]
        leading_rect = canvas._system_pixel_rect(page, leading)
        trailing_rect = canvas._system_pixel_rect(page, trailing)
        leading_key = (canvas.zoom, leading_rect.center().x() // canvas.TILE_SIZE_PX, leading_rect.center().y() // canvas.TILE_SIZE_PX)
        trailing_key = (canvas.zoom, trailing_rect.center().x() // canvas.TILE_SIZE_PX, trailing_rect.center().y() // canvas.TILE_SIZE_PX)
        canvas._tile_cache[leading_key] = object()
        canvas._tile_cache[trailing_key] = object()

        canvas.invalidate_system_render_cache(leading.id, leading.staves[0].id)

        self.assertNotIn(leading_key, canvas._tile_cache)
        self.assertIn(trailing_key, canvas._tile_cache)

    def test_page_rendering_culls_systems_outside_the_tile_column(self) -> None:
        document = KeyTab2Document.new()
        leading = document.pages[0].systems[0]
        following = document.split_system_at(document.pages[0].id, leading.id, 1024)
        canvas = PaperCanvas(document)
        page = document.pages[0]
        leading_left_mm, leading_right_mm = canvas._system_column_bounds(page, leading)
        drawn_system_ids: list[str] = []
        original_draw_system = canvas._draw_system

        def capture_draw_system(*arguments, **keyword_arguments):
            drawn_system_ids.append(arguments[8].id)
            return original_draw_system(*arguments, **keyword_arguments)

        canvas._draw_system = capture_draw_system
        canvas._render_region(QRect(
            round(leading_left_mm * canvas.pixels_per_mm),
            0,
            round((leading_right_mm - leading_left_mm) * canvas.pixels_per_mm),
            canvas.TILE_SIZE_PX,
        ))

        self.assertEqual(drawn_system_ids, [leading.id])

    def test_time_signature_lane_is_included_in_system_tile_culling(self) -> None:
        document = KeyTab2Document.new()
        canvas = PaperCanvas(document)
        page = document.pages[0]
        system = page.systems[0]
        left_mm, _, top_mm, _ = canvas._system_render_bounds(page, system, include_editor_controls=True)
        column_left_mm, _ = canvas._system_column_bounds(page, system)

        self.assertLess(left_mm, column_left_mm)
        self.assertTrue(canvas._system_intersects_render_region(
            page,
            system,
            left_mm,
            column_left_mm - 0.1,
            top_mm,
            system.top_mm,
            include_editor_controls=True,
        ))

    def test_system_tile_culling_includes_slurs_outside_the_stave(self) -> None:
        document = KeyTab2Document.new()
        page = document.pages[0]
        system = page.systems[0]
        stave = system.staves[0]
        tick_at_page_bottom = round(
            system.start_tick + (page.height_mm - system.top_mm) * (system.end_tick - system.start_tick) / system.height_mm
        )
        stave.events.append(SlurEvent(x1_rpitch=0, y1_tick=system.start_tick, x4_rpitch=0, y4_tick=tick_at_page_bottom))
        stave.touch()
        canvas = PaperCanvas(document)

        left_mm, right_mm, top_mm, bottom_mm = canvas._system_render_bounds(page, system, include_editor_controls=False)

        self.assertLessEqual(top_mm, system.top_mm)
        self.assertAlmostEqual(bottom_mm, page.height_mm, places=2)
        self.assertTrue(canvas._system_intersects_render_region(
            page,
            system,
            left_mm,
            right_mm,
            page.height_mm - 1.0,
            page.height_mm,
            include_editor_controls=False,
        ))

    def test_system_render_bounds_include_notation_and_measure_number_overhang(self) -> None:
        document = KeyTab2Document.new()
        page = document.pages[0]
        system = page.systems[0]
        stave = system.staves[0]
        stave.events.extend([
            NoteEvent(time=0, duration=256, pitch=84, hand="right"),
            NoteEvent(time=256, duration=256, pitch=84, hand="right"),
        ])
        canvas = PaperCanvas(document)
        _, column_right_mm = canvas._system_column_bounds(page, system)
        _, render_right_mm, _, _ = canvas._system_render_bounds(page, system, include_editor_controls=True)

        self.assertGreater(render_right_mm, column_right_mm)
        self.assertTrue(canvas._system_intersects_render_region(
            page,
            system,
            column_right_mm + 0.1,
            render_right_mm,
            system.top_mm,
            system.top_mm + 1.0,
            include_editor_controls=True,
        ))

    def test_tile_rendering_uses_a_bleed_region_around_internal_edges(self) -> None:
        canvas = PaperCanvas(KeyTab2Document.new())
        tile = QRect(canvas.TILE_SIZE_PX, canvas.TILE_SIZE_PX, canvas.TILE_SIZE_PX, canvas.TILE_SIZE_PX)
        visible_ranges: list[tuple[float, float]] = []
        original_draw = canvas._draw_page_to_cairo

        def capture_draw(context, page, visible_left_mm, visible_right_mm, visible_top_mm, visible_bottom_mm, include_snap_bands, **keyword_arguments):
            visible_ranges.append((visible_top_mm, visible_bottom_mm))
            original_draw(context, page, visible_left_mm, visible_right_mm, visible_top_mm, visible_bottom_mm, include_snap_bands, **keyword_arguments)

        canvas._draw_page_to_cairo = capture_draw
        image = canvas._render_region(tile)

        self.assertEqual(image.size(), tile.size())
        self.assertEqual(visible_ranges[0][0], (tile.top() - canvas.TILE_BLEED_PX) / canvas.pixels_per_mm)

    def test_visible_tick_range_includes_a_black_notehead_above_its_anchor(self) -> None:
        document = KeyTab2Document.new()
        canvas = PaperCanvas(document)
        system = document.pages[0].systems[0]
        stave = system.staves[0]
        black_note = NoteEvent(time=1000, duration=64, pitch=61)
        stave.events.append(black_note)
        top_mm = canvas._time_to_y_mm(system, 1024)
        notehead_bleed_mm = document.layout.engraving_mm(
            4.0 * document.layout.notehead_height_scaling + document.layout.note_stem_thickness_mm,
            stave.scale,
        )

        start_tick, end_tick = canvas._visible_tick_range(system, top_mm, top_mm + 1.0, notehead_bleed_mm)
        render_data = canvas._stave_render_data(system, stave, canvas.stave_left_mm(system, stave))

        self.assertLessEqual(start_tick, black_note.time)
        self.assertIn(black_note.id, [note.event_id for note in render_data.notes_in_tick_range(start_tick, end_tick)])

    def test_system_break_tool_resolves_internal_measure_boundary(self) -> None:
        app = QApplication.instance() or QApplication([])
        del app
        document = KeyTab2Document.new()
        canvas = PaperCanvas(document)
        system = document.pages[0].systems[0]
        y_mm = canvas._time_to_y_mm(system, 1024)
        left_mm, right_mm = canvas._system_column_bounds(document.pages[0], system)

        selected = canvas.system_break_target_at(QPointF((left_mm + right_mm) / 2.0, y_mm))

        self.assertEqual(selected, ("split", system, 1024))

    def test_system_break_highlight_spans_the_entire_multi_stave_system(self) -> None:
        document = KeyTab2Document.new()
        system = document.pages[0].systems[0]
        system.staves.append(Stave(pitch_range=[48, 96]))
        canvas = PaperCanvas(document)
        left_mm, right_mm = canvas._system_column_bounds(document.pages[0], system)
        canvas.select_system_break_mode()
        canvas.update_mouse_cursor(QPointF((left_mm + right_mm) / 2.0, canvas._time_to_y_mm(system, 1024)))

        highlight = canvas._system_break_highlight_geometry()

        self.assertEqual(highlight, (left_mm, right_mm, canvas._time_to_y_mm(system, 1024)))

    def test_system_break_tool_does_not_select_a_different_system_column(self) -> None:
        document = KeyTab2Document.new()
        page = document.pages[0]
        first_system = page.systems[0]
        second_system = document.split_system_at(page.id, first_system.id, 1024)
        third_system = document.split_system_at(page.id, second_system.id, 2048)
        canvas = PaperCanvas(document)
        first_barline_y_mm = canvas._time_to_y_mm(first_system, 512)
        third_left_mm, third_right_mm = canvas._system_column_bounds(page, third_system)

        target = canvas.system_break_target_at(QPointF((third_left_mm + third_right_mm) / 2.0, first_barline_y_mm))

        self.assertEqual(target, ("split", third_system, 5120))

    def test_system_break_tool_inserts_and_removes_a_break_by_clicking_barlines(self) -> None:
        document = KeyTab2Document.new()
        canvas = PaperCanvas(document)
        system = document.pages[0].systems[0]
        canvas.select_system_break_mode()
        tool = canvas._tool_manager.active_tool

        self.assertIsNotNone(tool)
        split_y_mm = canvas._time_to_y_mm(system, 1024)
        left_mm, right_mm = canvas._system_column_bounds(document.pages[0], system)
        self.assertTrue(tool.on_left_press(QPointF((left_mm + right_mm) / 2.0, split_y_mm)))
        self.assertEqual(len(document.pages[0].systems), 2)

        leading = document.pages[0].systems[0]
        bottom_y_mm = canvas._time_to_y_mm(leading, leading.end_tick)
        left_mm, right_mm = canvas._system_column_bounds(document.pages[0], leading)
        self.assertTrue(tool.on_left_press(QPointF((left_mm + right_mm) / 2.0, bottom_y_mm)))
        self.assertEqual(len(document.pages), 1)
        self.assertEqual(len(document.pages[0].systems), 1)

    def test_permanent_stave_control_is_centred_on_stave_width(self) -> None:
        app = QApplication.instance() or QApplication([])
        del app
        document = KeyTab2Document.new()
        canvas = PaperCanvas(document)
        system = document.pages[0].systems[0]
        drawer = StaveDrawer(None, canvas.INK_COLOR)
        left_mm, right_mm = canvas._system_column_bounds(document.pages[0], system)
        stave = system.staves[0]
        stave_left_mm = canvas._centered_stave_left_positions(system, drawer, document.layout, left_mm, right_mm)[0]
        centre_x_mm, centre_y_mm = canvas._stave_control_centre(system, stave, stave_left_mm)
        stave_bounds = drawer.bounds(stave, document.layout, stave_left_mm)

        target = canvas._stave_control_at(QPointF(centre_x_mm, centre_y_mm))

        self.assertIsNotNone(stave_bounds)
        self.assertEqual(centre_x_mm, (stave_bounds[0] + stave_bounds[1]) * 0.5)
        self.assertIsNotNone(target)
        self.assertEqual(target[0].id, system.id)
        self.assertEqual(target[1].id, stave.id)

    def test_pdf_export_excludes_permanent_stave_controls(self) -> None:
        document = KeyTab2Document.new()
        canvas = PaperCanvas(document)

        with TemporaryDirectory() as directory, patch.object(canvas, "_draw_stave_control") as draw_control:
            canvas.export_pdf(f"{directory}/score.pdf")

        draw_control.assert_not_called()


if __name__ == "__main__":
    unittest.main()