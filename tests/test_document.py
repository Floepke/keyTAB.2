from __future__ import annotations

import tempfile
import unittest
from dataclasses import asdict
from pathlib import Path

from keytab2_model import BaseGrid, BeamEvent, KeyTab2Document, LineBreakEvent, NoteEvent, SlurEvent, TempoEvent, TextEvent
from keytab2_model.base_grid import apply_beam_overrides, beam_windows, grid_boundaries, grid_line_boundaries
from keytab2_model.layout import Layout
from keytab2_model.events import EVENT_TYPES


class KeyTab2DocumentTests(unittest.TestCase):
    def test_new_document_has_one_page_system_and_stave(self) -> None:
        document = KeyTab2Document.new()

        self.assertEqual(len(document.pages), 1)
        self.assertEqual(len(document.pages[0].systems), 1)
        self.assertEqual(len(document.pages[0].systems[0].staves), 1)
        self.assertEqual(document.base_grid, [BaseGrid(numerator=4, denominator=4, beat_grouping=[1, 2, 3, 4], measure_amount=8)])
        self.assertEqual(document.pages[0].systems[0].end_tick, 8 * 4 * 256)

    def test_enabled_beat_markers_resolve_grid_lines(self) -> None:
        grid = [BaseGrid(numerator=7, denominator=8, beat_grouping=[1, 4, 9], measure_amount=2)]

        measures, groups = grid_boundaries(grid, 256)

        self.assertEqual(measures, (0, 896, 1792))
        self.assertEqual(groups, (384, 1280))

    def test_grid_lines_define_default_beam_windows_and_markers_replace_them(self) -> None:
        grid = [BaseGrid(numerator=7, denominator=8, beat_grouping=[1, 4], measure_amount=1)]

        self.assertEqual(beam_windows(grid, 256), ((0, 384), (384, 896)))
        self.assertEqual(apply_beam_overrides(beam_windows(grid, 256), [(256, 768)]), ((256, 768),))

    def test_enabled_grid_lines_split_automatic_beam_windows(self) -> None:
        grid = [BaseGrid(numerator=4, denominator=4, beat_grouping=[1, 2, 4, 8], measure_amount=1)]

        self.assertEqual(grid_line_boundaries(grid, 256), (256, 768))
        self.assertEqual(beam_windows(grid, 256), ((0, 256), (256, 768), (768, 1024)))

    def test_time_signature_change_preserves_remaining_measures(self) -> None:
        document = KeyTab2Document.new()

        document.set_time_signature(2048, 3, 4, False)

        self.assertEqual(
            [(segment.numerator, segment.denominator, segment.measure_amount, segment.indicator_enabled) for segment in document.base_grid],
            [(4, 4, 2, True), (3, 4, 6, False)],
        )
        self.assertEqual(document.pages[-1].systems[-1].end_tick, 2 * 1024 + 6 * 768)

    def test_time_signature_grid_line_changes_only_the_change_measure_pattern(self) -> None:
        document = KeyTab2Document.new()
        document.set_time_signature(2048, 3, 4, True)

        document.set_time_signature_grid_line(2304, False)

        self.assertEqual(document.base_grid[1].beat_grouping, [1, 3])

    def test_add_measure_extends_the_final_time_signature_segment(self) -> None:
        document = KeyTab2Document.new()
        document.set_time_signature(2048, 3, 4, True)

        document.add_measure()

        self.assertEqual(document.base_grid[-1].measure_amount, 7)

    def test_removing_a_time_signature_change_restores_the_prior_segment(self) -> None:
        document = KeyTab2Document.new()
        document.set_time_signature(2048, 3, 4, True)

        document.remove_time_signature(2048)

        self.assertEqual([(segment.numerator, segment.denominator, segment.measure_amount) for segment in document.base_grid], [(4, 4, 8)])

    def test_time_signature_change_normalizes_existing_system_breaks_to_whole_measures(self) -> None:
        document = KeyTab2Document.new()
        first_system = document.pages[0].systems[0]
        document.split_system_at(document.pages[0].id, first_system.id, 4096)

        document.set_time_signature(2048, 7, 8, True)

        measure_starts, _ = grid_boundaries(document.base_grid, document.time_per_quarter)
        systems = [system for page in document.pages for system in page.systems]
        self.assertTrue(all(system.start_tick in measure_starts and system.end_tick in measure_starts for system in systems))
        self.assertEqual(systems[-1].end_tick, measure_starts[-1])

    def test_remove_measure_removes_only_the_final_measure(self) -> None:
        document = KeyTab2Document.new()

        document.remove_measure()

        self.assertEqual(document.base_grid[-1].measure_amount, 7)

    def test_base_grid_rejects_non_beat_values(self) -> None:
        with self.assertRaises(ValueError):
            BaseGrid(beat_grouping=[1, 2, 3, 4.0]).validate()

    def test_test_score_contains_notes_and_a_beam(self) -> None:
        document = KeyTab2Document.with_test_notes()
        events = document.pages[0].systems[0].staves[0].events

        self.assertGreaterEqual(sum(isinstance(event, NoteEvent) for event in events), 6)
        self.assertEqual(sum(isinstance(event, BeamEvent) for event in events), 1)

    def test_split_system_at_moves_following_events_to_a_new_system(self) -> None:
        document = KeyTab2Document.new()
        page = document.pages[0]
        system = page.systems[0]
        system.staves[0].events.extend([
            NoteEvent(time=1024, duration=256, pitch=60),
            NoteEvent(time=4096, duration=256, pitch=64),
        ])

        following = document.split_system_at(page.id, system.id, 4096)

        self.assertEqual((system.end_tick, following.start_tick), (4096, 4096))
        self.assertEqual([event.time for event in system.staves[0].events], [1024])
        self.assertEqual([event.time for event in following.staves[0].events], [4096])
        self.assertNotEqual(system.staves[0].id, following.staves[0].id)
        self.assertEqual(following.first_measure_number, 5)
        self.assertEqual(system.top_mm, following.top_mm)
        self.assertEqual(system.height_mm, following.height_mm)

    def test_repeated_system_splits_keep_measure_numbers_sequential(self) -> None:
        document = KeyTab2Document.new()
        page = document.pages[0]
        first = page.systems[0]
        second = document.split_system_at(page.id, first.id, 2048)
        third = document.split_system_at(page.id, second.id, 4096)
        fourth = document.split_system_at(page.id, third.id, 6144)

        systems = [system for document_page in document.pages for system in document_page.systems]
        self.assertEqual([system.first_measure_number for system in systems], [1, 3, 5, 7])
        self.assertEqual(fourth.first_measure_number, 7)

    def test_split_system_at_creates_linked_note_continuations(self) -> None:
        document = KeyTab2Document.new()
        page = document.pages[0]
        system = page.systems[0]
        system.staves[0].events.append(NoteEvent(time=4000, duration=256, pitch=60))

        following = document.split_system_at(page.id, system.id, 4096)

        leading_note = system.staves[0].events[0]
        following_note = following.staves[0].events[0]
        self.assertEqual((leading_note.time, leading_note.duration), (4000, 96))
        self.assertEqual((following_note.time, following_note.duration), (4096, 160))
        self.assertTrue(leading_note.continues_to_next)
        self.assertTrue(following_note.continues_from_previous)
        self.assertEqual(leading_note.continuation_id, following_note.continuation_id)

    def test_remove_system_break_merges_the_adjacent_systems(self) -> None:
        document = KeyTab2Document.new()
        page = document.pages[0]
        system = page.systems[0]
        system.staves[0].events.extend([
            NoteEvent(time=256, duration=128, pitch=60),
            NoteEvent(time=4096, duration=128, pitch=64),
        ])
        following = document.split_system_at(page.id, system.id, 4096)

        merged = document.remove_system_break(following.id, "top")

        self.assertEqual(len(document.pages), 1)
        self.assertEqual(document.pages[0].systems, [merged])
        self.assertEqual((merged.start_tick, merged.end_tick), (0, 8192))
        self.assertEqual([event.time for event in merged.staves[0].events], [256, 4096])

    def test_system_time_spans_the_page_printable_height(self) -> None:
        document = KeyTab2Document.new()
        document.layout.page_top_margin_mm = 18.0
        document.layout.page_bottom_margin_mm = 22.0
        page = document.pages[0]
        document._reflow_page_systems(page, document.layout)

        system = page.systems[0]

        self.assertEqual(system.top_mm, 18.0)
        self.assertEqual(system.height_mm, page.height_mm - 40.0 - document.layout.footer_height_mm)

    def test_first_page_reserves_its_header_while_later_pages_do_not(self) -> None:
        document = KeyTab2Document.new()
        document.layout.page_top_margin_mm = 12.0
        document.layout.page_bottom_margin_mm = 8.0
        document.layout.header_height_mm = 25.0
        document.layout.footer_height_mm = 11.0
        first_page = document.pages[0]
        later_page = type(first_page)(systems=[type(first_page.systems[0])()])

        document._reflow_page_systems(first_page, document.layout, is_first_page=True)
        document._reflow_page_systems(later_page, document.layout, is_first_page=False)

        self.assertEqual(first_page.systems[0].top_mm, 37.0)
        self.assertEqual(later_page.systems[0].top_mm, 12.0)
        self.assertEqual(first_page.systems[0].height_mm, later_page.systems[0].height_mm - 25.0)

    def test_paginate_page_moves_overflow_systems_to_a_new_page(self) -> None:
        document = KeyTab2Document.new()
        document.layout.page_width_mm = 55.0
        page = document.pages[0]
        page.width_mm = 55.0
        first_system = page.systems[0]
        document.split_system_at(page.id, first_system.id, 1024)

        self.assertEqual(len(document.pages), 2)
        self.assertEqual([system.start_tick for system in document.pages[0].systems], [0])
        self.assertEqual([system.start_tick for system in document.pages[1].systems], [1024])
        self.assertEqual(document.pages[1].width_mm, page.width_mm)
        self.assertEqual(document.pages[1].height_mm, page.height_mm)

    def test_split_repackages_later_pages_compactly(self) -> None:
        document = KeyTab2Document.new()
        document.layout.page_width_mm = 120.0
        document.pages[0].width_mm = 120.0
        document._system_required_width_mm = lambda _system: 50.0
        for split_tick in (1024, 2048, 3072, 4096, 5120):
            system = next(
                system
                for page in document.pages
                for system in page.systems
                if system.start_tick < split_tick < system.end_tick
            )
            document.split_system_at(document.pages[0].id, system.id, split_tick)

        self.assertEqual([len(page.systems) for page in document.pages], [2, 2, 2])

        first_system = document.pages[0].systems[0]
        document.split_system_at(document.pages[0].id, first_system.id, 512)

        self.assertEqual([len(page.systems) for page in document.pages], [2, 2, 2, 1])

    def test_forced_page_break_starts_a_new_page_and_round_trips(self) -> None:
        document = KeyTab2Document.new()
        first_system = document.pages[0].systems[0]
        following = document.split_system_at(document.pages[0].id, first_system.id, 1024)

        document.set_forced_page_break_before(following.id, True)

        self.assertEqual([len(page.systems) for page in document.pages], [1, 1])
        self.assertTrue(document.pages[1].systems[0].force_page_break_before)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "page-break.keytab2"
            document.save(path)
            restored = KeyTab2Document.load(path)
        self.assertTrue(restored.pages[1].systems[0].force_page_break_before)
        self.assertEqual([len(page.systems) for page in restored.pages], [1, 1])

    def test_repaginate_document_reclaims_pages_after_a_stave_scale_reduces(self) -> None:
        document = KeyTab2Document.new()
        document.layout.page_width_mm = 170.0
        page = document.pages[0]
        page.width_mm = 170.0
        first_system = page.systems[0]
        second_system = document.split_system_at(page.id, first_system.id, 1024)
        document.split_system_at(document.pages[-1].id, second_system.id, 2048)
        all_systems = [system for current_page in document.pages for system in current_page.systems]
        all_systems[1].staves[0].scale = 4.0
        document.repaginate_document()

        self.assertGreater(len(document.pages), 1)
        all_systems[1].staves[0].scale = 1.0
        document.repaginate_document()

        self.assertEqual(len(document.pages), 1)
        self.assertEqual(len(document.pages[0].systems), 3)

    def test_ledger_lines_increase_the_system_required_width(self) -> None:
        document = KeyTab2Document.new()
        system = document.pages[0].systems[0]
        natural_width = document._system_required_width_mm(system)
        system.staves[0].events.append(NoteEvent(time=256, duration=128, pitch=22))

        self.assertGreater(document._system_required_width_mm(system), natural_width)

    def test_note_round_trips_through_native_json(self) -> None:
        document = KeyTab2Document.new()
        document.pages[0].systems[0].staves[0].scale = 0.75
        note = NoteEvent(time=256, duration=128, pitch=60)
        document.pages[0].systems[0].staves[0].events.append(note)

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "document.keytab2"
            document.save(path)
            restored = KeyTab2Document.load(path)

        restored_note = restored.pages[0].systems[0].staves[0].events[0]
        self.assertEqual(restored_note.id, note.id)
        self.assertEqual(restored_note.time, 256)
        self.assertEqual(restored_note.duration, 128)
        self.assertEqual(restored_note.pitch, 60)
        self.assertEqual(restored.pages[0].systems[0].staves[0].scale, 0.75)

    def test_document_serializes_systems_not_lines(self) -> None:
        page_data = KeyTab2Document.new().to_dict()["pages"][0]

        self.assertIn("systems", page_data)
        self.assertNotIn("lines", page_data)

    def test_layout_unit_helpers_keep_paper_and_engraving_scales_distinct(self) -> None:
        layout = Layout(scale=0.5, page_width_mm=100.0, page_height_mm=200.0)
        document = KeyTab2Document.new()
        document.pages[0].width_mm = 120.0
        document.pages[0].height_mm = 240.0

        self.assertEqual(layout.engraving_mm(1.0, stave_scale=0.5), 0.25)
        self.assertEqual(layout.engraving_pt_to_mm(72.0, stave_scale=0.5), 6.35)
        self.assertEqual(document.pages[0].width_mm, 120.0)
        self.assertEqual(document.pages[0].height_mm, 240.0)

    def test_layout_round_trips_with_the_document(self) -> None:
        document = KeyTab2Document.new()
        document.layout.stave_two_line_thickness_mm = 0.8
        document.layout.stave_clef_line_dash_pattern_mm = [2.0, 1.0]
        document.layout.measure_numbering_font.size_pt = 28.0
        document.layout.measure_numbering_font.italic = True

        restored = KeyTab2Document.from_dict(document.to_dict())

        self.assertEqual(restored.layout.stave_two_line_thickness_mm, 0.8)
        self.assertEqual(restored.layout.stave_clef_line_dash_pattern_mm, [2.0, 1.0])
        self.assertEqual(restored.layout.measure_numbering_font.size_pt, 28.0)
        self.assertTrue(restored.layout.measure_numbering_font.italic)

    def test_rejects_non_native_extension(self) -> None:
        with self.assertRaises(ValueError):
            KeyTab2Document.new().save("document.keytab")

    def test_mixed_events_round_trip_in_their_owning_containers(self) -> None:
        document = KeyTab2Document.new()
        page = document.pages[0]
        system = page.systems[0]
        system.staves[0].events.extend([
            NoteEvent(time=256, duration=128, pitch=60),
            SlurEvent(x1_rpitch=0, y1_tick=256, x4_rpitch=7, y4_tick=512),
        ])
        system.events.append(TextEvent(text="dolce", start_tick=256))
        page.events.append(LineBreakEvent(start_tick=4096))
        document.timeline_events.append(TempoEvent(start_tick=1024, tempo=96))

        restored = KeyTab2Document.from_dict(document.to_dict())

        self.assertIsInstance(restored.pages[0].systems[0].staves[0].events[0], NoteEvent)
        self.assertIsInstance(restored.pages[0].systems[0].staves[0].events[1], SlurEvent)
        self.assertIsInstance(restored.pages[0].systems[0].events[0], TextEvent)
        self.assertIsInstance(restored.pages[0].events[0], LineBreakEvent)
        self.assertEqual(restored.timeline_events[-1].tempo, 96)

    def test_system_split_assigns_slurs_using_the_first_handle_tick(self) -> None:
        document = KeyTab2Document.new()
        page = document.pages[0]
        system = page.systems[0]
        slur = SlurEvent(x1_rpitch=0, y1_tick=1280, x4_rpitch=7, y4_tick=1536)
        system.staves[0].events.append(slur)

        following = document.split_system_at(page.id, system.id, 1024)

        self.assertEqual(system.staves[0].events, [])
        self.assertEqual(following.staves[0].events, [slur])

    def test_every_registered_event_type_loads_from_json_data(self) -> None:
        for event_type, event_class in EVENT_TYPES.items():
            with self.subTest(event_type=event_type):
                event_data = asdict(event_class())
                restored = KeyTab2Document._event_from_dict(event_data)
                self.assertIsInstance(restored, event_class)

    def test_old_note_and_beam_timing_fields_load_as_time_and_duration(self) -> None:
        old_note = KeyTab2Document._event_from_dict({"type": "note", "start_tick": 32, "duration_ticks": 64})
        old_beam = KeyTab2Document._event_from_dict({"type": "beam", "start_tick": 32, "duration_ticks": 64})

        self.assertEqual((old_note.time, old_note.duration), (32, 64))
        self.assertEqual((old_beam.time, old_beam.duration), (32, 64))
        self.assertNotIn("start_tick", KeyTab2Document.with_test_notes().to_dict()["pages"][0]["systems"][0]["staves"][0]["events"][0])


if __name__ == "__main__":
    unittest.main()