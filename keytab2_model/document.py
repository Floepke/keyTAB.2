"""Persistent, page-oriented document data for keyTAB2."""

from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from keytab2_model.base_grid import BaseGrid, grid_boundaries, total_duration
from keytab2_model.events import BeamEvent, EVENT_TYPES, Event, LineOwnedEvent, NoteEvent, PageEvent, StaveEvent, TempoEvent, TimelineEvent
from keytab2_model.font import Font
from keytab2_model.layout import Layout

FORMAT_NAME = "keytab2"
FORMAT_VERSION = 1
TIME_PER_QUARTER = 256
BLACK_PITCH_CLASSES = {1, 3, 6, 8, 10}
EXTRA_GAP_AFTER_PITCH_CLASSES = {4, 11}
PIANO_LOW_MIDI_PITCH = 21
PIANO_HIGH_MIDI_PITCH = 108


def _ledger_line_groups() -> tuple[tuple[int, ...], ...]:
    """Return the two- and three-line Klavarskribo black-key groups."""
    groups: list[tuple[int, ...]] = []
    for pitch in range(128):
        if pitch % 12 == 1:
            groups.append(tuple(candidate for candidate in (pitch, pitch + 2) if candidate < 128))
        elif pitch % 12 == 6:
            groups.append(tuple(candidate for candidate in (pitch, pitch + 2, pitch + 4) if candidate < 128))
    return tuple(groups)


LEDGER_LINE_GROUPS = _ledger_line_groups()


def _ledger_group_index(pitch: int) -> int:
    """Return the nearest ledger-line group for a MIDI pitch."""
    for index, group in enumerate(LEDGER_LINE_GROUPS):
        if pitch <= group[-1]:
            if index and pitch <= (LEDGER_LINE_GROUPS[index - 1][-1] + group[0]) // 2:
                return index - 1
            return index
    return len(LEDGER_LINE_GROUPS) - 1


def _new_id() -> str:
    return str(uuid4())


def _timestamp() -> str:
    return datetime.now(UTC).isoformat()


@dataclass
class ScoreInfo:
    title: str = "Untitled"
    composer: str = ""
    copyright: str = ""


@dataclass
class Stave:
    name: str = "Piano"
    pitch_range: list[int] = field(default_factory=lambda: [36, 84])
    scale: float = 1.0
    events: list[StaveEvent] = field(default_factory=list)
    id: str = field(default_factory=_new_id)
    revision: int = field(default=0, repr=False, compare=False)

    def touch(self) -> None:
        """Invalidate derived geometry after an edit to this stave or its events."""
        self.revision += 1

    @staticmethod
    def pitch_offset_units(midi_pitch: int, range_low: int) -> float:
        """Return a Klavarskribo pitch offset in semitone-width units."""
        if midi_pitch >= range_low:
            pitches = range(range_low, midi_pitch)
            direction = 1.0
        else:
            pitches = range(midi_pitch, range_low)
            direction = -1.0
        return direction * sum(2.0 if pitch % 12 in EXTRA_GAP_AFTER_PITCH_CLASSES else 1.0 for pitch in pitches)

    def ledger_line_pitches_for_pitch(self, pitch: int) -> tuple[int, ...]:
        """Return omitted black-key groups needed to show one pitch as a ledger."""
        natural_pitches = self.natural_line_pitches()
        if not natural_pitches:
            return ()
        low_pitch, high_pitch = self.pitch_range
        first_group = _ledger_group_index(low_pitch)
        if pitch < low_pitch and PIANO_LOW_MIDI_PITCH <= pitch <= PIANO_LOW_MIDI_PITCH + 2:
            low_group = _ledger_group_index(pitch)
            return tuple(
                group_pitch
                for group in LEDGER_LINE_GROUPS[low_group:first_group]
                for group_pitch in group
            )
        last_group = _ledger_group_index(high_pitch)
        event_group = _ledger_group_index(pitch)
        if event_group < first_group:
            return tuple(pitch for group in LEDGER_LINE_GROUPS[event_group:first_group] for pitch in group)
        if event_group > last_group:
            return tuple(pitch for group in LEDGER_LINE_GROUPS[last_group + 1:event_group + 1] for pitch in group)
        return ()

    def ledger_line_pitches(self, system: "System | None" = None) -> tuple[int, ...]:
        """Return black-key groups needed as ledger lines outside this stave range."""
        if system is None:
            return ()
        ledger_pitches: set[int] = set()
        for event in self.events:
            if not isinstance(event, NoteEvent) or event.time >= system.end_tick or event.time + event.duration <= system.start_tick:
                continue
            ledger_pitches.update(self.ledger_line_pitches_for_pitch(event.pitch))
        return tuple(sorted(ledger_pitches))

    def line_pitches(self, system: "System | None" = None) -> tuple[int, ...]:
        """Return all system-local positions required for stave allocation."""
        positions = set(self.natural_line_pitches()).union(self.ledger_line_pitches(system))
        if system is not None:
            low_pitch, high_pitch = self.pitch_range
            positions.update(
                event.pitch
                for event in self.events
                if isinstance(event, NoteEvent)
                and event.time < system.end_tick
                and event.time + event.duration > system.start_tick
                and not low_pitch <= event.pitch <= high_pitch
            )
        return tuple(sorted(positions))

    def natural_line_pitches(self) -> tuple[int, ...]:
        """Return complete Klavarskribo groups selected by the configured range."""
        low_pitch, high_pitch = self.pitch_range
        first_group = _ledger_group_index(low_pitch)
        last_group = _ledger_group_index(high_pitch)
        return tuple(
            pitch
            for group in LEDGER_LINE_GROUPS[first_group:last_group + 1]
            for pitch in group
            if PIANO_LOW_MIDI_PITCH <= pitch <= PIANO_HIGH_MIDI_PITCH
        )


@dataclass
class System:
    """A vertical time window placed as one column in a paper row."""

    start_tick: int = 0
    end_tick: int = TIME_PER_QUARTER * 16
    first_measure_number: int = 1
    left_margin_mm: float = 5.0
    right_margin_mm: float = 5.0
    top_mm: float = field(default=10.0, repr=False, compare=False)
    height_mm: float = field(default=277.0, repr=False, compare=False)
    staves: list[Stave] = field(default_factory=lambda: [Stave()])
    events: list[LineOwnedEvent] = field(default_factory=list)
    id: str = field(default_factory=_new_id)
    revision: int = field(default=0, repr=False, compare=False)

    def touch(self) -> None:
        """Invalidate derived system geometry after a structural edit."""
        self.revision += 1


@dataclass
class Page:
    """A physical paper page whose dimensions are authoritative document millimetres."""
    width_mm: float = 210.0
    height_mm: float = 297.0
    systems: list[System] = field(default_factory=lambda: [System()])
    events: list[PageEvent] = field(default_factory=list)
    id: str = field(default_factory=_new_id)


@dataclass
class KeyTab2Document:
    """Versioned source data for the direct paper editor.

    Pages, lines, staves, and events are persisted. Render geometry, hit-test
    indexes, and page images remain derived runtime data and are never saved.
    """

    score_info: ScoreInfo = field(default_factory=ScoreInfo)
    layout: Layout = field(default_factory=Layout)
    base_grid: list[BaseGrid] = field(default_factory=lambda: [BaseGrid()])
    timeline_events: list[TimelineEvent] = field(default_factory=lambda: [TempoEvent()])
    pages: list[Page] = field(default_factory=lambda: [Page()])
    created_at: str = field(default_factory=_timestamp)
    modified_at: str = field(default_factory=_timestamp)
    format: str = field(default=FORMAT_NAME, init=False)
    format_version: int = field(default=FORMAT_VERSION, init=False)
    time_per_quarter: int = field(default=TIME_PER_QUARTER, init=False)

    @classmethod
    def new(cls) -> "KeyTab2Document":
        document = cls()
        document.pages[0].systems[0].end_tick = total_duration(document.base_grid, TIME_PER_QUARTER)
        document._reflow_page_systems(document.pages[0], document.layout, is_first_page=True)
        return document

    @classmethod
    def with_test_notes(cls) -> "KeyTab2Document":
        """Return a disposable score exercising the current note renderer."""
        document = cls.new()
        document.score_info.title = "Test Notes"
        stave = document.pages[0].systems[0].staves[0]
        stave.events.extend([
            NoteEvent(time=0, duration=2048, pitch=48, hand="left"),
            NoteEvent(time=256, duration=256, pitch=52, hand="left"),
            NoteEvent(time=512, duration=256, pitch=55, hand="right"),
            NoteEvent(time=1280, duration=192, pitch=60, hand="left"),
            NoteEvent(time=1536, duration=192, pitch=64, hand="left"),
            NoteEvent(time=1792, duration=192, pitch=67, hand="left"),
            BeamEvent(time=1280, duration=704, hand="left"),
        ])
        stave.touch()
        return document

    def to_dict(self) -> dict:
        self.modified_at = _timestamp()
        data = asdict(self)
        for page in data["pages"]:
            for system in page["systems"]:
                system.pop("revision", None)
                system.pop("top_mm", None)
                system.pop("height_mm", None)
                for stave in system["staves"]:
                    stave.pop("revision", None)
        return data

    def split_system_at(self, page_id: str, system_id: str, time: int) -> System:
        """Split one system at a barline and return the new following system."""
        page = next((page for page in self.pages if page.id == page_id), None)
        if page is None:
            raise ValueError("Page not found")
        index = next((index for index, system in enumerate(page.systems) if system.id == system_id), None)
        if index is None:
            raise ValueError("System not found")
        system = page.systems[index]
        if not system.start_tick < time < system.end_tick:
            raise ValueError("System split time must be inside the system")

        following_staves = deepcopy(system.staves)
        for original, following in zip(system.staves, following_staves, strict=True):
            original.events, following.events = self._partition_events(original.events, time)
            self._split_crossing_notes(original, following, time)
            original.touch()
            following.id = _new_id()
            following.touch()
        system.events, following_events = self._partition_events(system.events, time)
        following_system = System(
            start_tick=time,
            end_tick=system.end_tick,
            first_measure_number=system.first_measure_number + self._measure_count_before(system.start_tick, time),
            left_margin_mm=system.left_margin_mm,
            right_margin_mm=system.right_margin_mm,
            staves=following_staves,
            events=following_events,
        )
        system.end_tick = time
        system.touch()
        page.systems.insert(index + 1, following_system)
        self.paginate_page(page.id)
        return following_system

    def time_signature_segment_at(self, time: int) -> tuple[int, int]:
        """Return the base-grid segment and its absolute start tick for a barline."""
        cursor_tick = 0
        for index, segment in enumerate(self.base_grid):
            duration = segment.measure_duration(self.time_per_quarter)
            end_tick = cursor_tick + segment.measure_amount * duration
            if cursor_tick <= time < end_tick:
                if (time - cursor_tick) % duration:
                    raise ValueError("Time-signature changes must start at a barline")
                return index, cursor_tick
            cursor_tick = end_tick
        if time == cursor_tick:
            return len(self.base_grid), cursor_tick
        raise ValueError("Time is outside the score")

    def _time_signature_segment_containing(self, time: int) -> tuple[int, int]:
        cursor_tick = 0
        for index, segment in enumerate(self.base_grid):
            end_tick = cursor_tick + segment.measure_amount * segment.measure_duration(self.time_per_quarter)
            if cursor_tick <= time < end_tick:
                return index, cursor_tick
            cursor_tick = end_tick
        raise ValueError("Time is outside the score")

    def set_time_signature(self, time: int, numerator: int, denominator: int, indicator_enabled: bool) -> None:
        """Insert or edit a meter segment at an existing measure barline."""
        if numerator < 1 or denominator < 1 or denominator & (denominator - 1):
            raise ValueError("Time signature must have a positive numerator and power-of-two denominator")
        index, segment_start = self.time_signature_segment_at(time)
        if index == len(self.base_grid):
            segment = deepcopy(self.base_grid[-1])
            segment.measure_amount = 1
            self.base_grid.append(segment)
        else:
            segment = self.base_grid[index]
            if time != segment_start:
                measure_duration = segment.measure_duration(self.time_per_quarter)
                leading_measures = (time - segment_start) // measure_duration
                trailing_measures = segment.measure_amount - leading_measures
                segment.measure_amount = leading_measures
                segment = deepcopy(segment)
                segment.measure_amount = trailing_measures
                self.base_grid.insert(index + 1, segment)
        segment.numerator = numerator
        segment.denominator = denominator
        segment.indicator_enabled = indicator_enabled
        segment.beat_grouping = list(range(1, numerator + 1))
        self._sync_score_duration()

    def set_time_signature_grid_line(self, time: int, enabled: bool) -> None:
        """Toggle one beat boundary in the first measure of its meter segment."""
        index, segment_start = self._time_signature_segment_containing(time)
        segment = self.base_grid[index]
        beat_duration = segment.beat_duration(self.time_per_quarter)
        measure_duration = segment.measure_duration(self.time_per_quarter)
        if not segment_start < time < segment_start + measure_duration or (time - segment_start) % beat_duration:
            raise ValueError("Grid lines must be internal beat boundaries in the change measure")
        beat = (time - segment_start) // beat_duration + 1
        markers = set(segment.beat_grouping)
        if enabled:
            markers.add(beat)
        else:
            markers.discard(beat)
            markers.add(1)
        segment.beat_grouping = sorted(markers)

    def remove_time_signature(self, time: int) -> None:
        """Remove a non-initial meter change and merge its measures into the prior segment."""
        index, segment_start = self.time_signature_segment_at(time)
        if index == 0 or index == len(self.base_grid) or time != segment_start:
            raise ValueError("Only non-initial time-signature changes can be removed")
        previous = self.base_grid[index - 1]
        removed = self.base_grid.pop(index)
        previous.measure_amount += removed.measure_amount
        self._sync_score_duration()

    def add_measure(self) -> None:
        """Append one measure using the final time signature."""
        self.base_grid[-1].measure_amount += 1
        self._sync_score_duration()

    def remove_measure(self) -> None:
        """Remove one final measure while retaining a non-empty score."""
        if len(self.base_grid) == 1 and self.base_grid[0].measure_amount == 1:
            raise ValueError("A score must contain at least one measure")
        final_segment = self.base_grid[-1]
        final_segment.measure_amount -= 1
        if final_segment.measure_amount == 0:
            self.base_grid.pop()
        self._sync_score_duration()

    def _sync_score_duration(self) -> None:
        """Match every system boundary to the complete base-grid measure grid."""
        end_tick = total_duration(self.base_grid, self.time_per_quarter)
        systems = [system for page in self.pages for system in page.systems]
        measure_starts, _ = grid_boundaries(self.base_grid, self.time_per_quarter)
        boundaries = [0]
        for system in systems[:-1]:
            valid = [start for start in measure_starts if boundaries[-1] < start < end_tick]
            if not valid:
                break
            boundaries.append(min(valid, key=lambda start: abs(start - system.end_tick)))
        boundaries.append(end_tick)
        retained = systems[:len(boundaries) - 1]
        stave_events = [[event for system in systems for event in system.staves[index].events] for index in range(len(retained[0].staves))]
        system_events = [event for system in systems for event in system.events]
        for system, start_tick, final_tick in zip(retained, boundaries[:-1], boundaries[1:], strict=True):
            system.start_tick = start_tick
            system.end_tick = final_tick
            system.first_measure_number = self._measure_count_before(0, start_tick) + 1
            for stave_index, stave in enumerate(system.staves):
                stave.events = [
                    event for event in stave_events[stave_index]
                    if start_tick <= self._event_start_tick(event) < final_tick
                ]
                stave.touch()
            system.events = [
                event for event in system_events
                if start_tick <= self._event_start_tick(event) < final_tick
            ]
            system.touch()
        if not retained:
            raise ValueError("Score duration must contain at least one system")
        first_page = self.pages[0]
        self.pages = [Page(width_mm=first_page.width_mm, height_mm=first_page.height_mm, systems=retained)]
        self.repaginate_document()

    def remove_system_break(self, system_id: str, boundary: str) -> System:
        """Remove the break at a system edge and return the merged system."""
        if boundary not in {"top", "bottom"}:
            raise ValueError("System break boundary must be 'top' or 'bottom'")
        located_systems = [
            (page_index, system_index, system)
            for page_index, page in enumerate(self.pages)
            for system_index, system in enumerate(page.systems)
        ]
        target_index = next((index for index, (_, _, system) in enumerate(located_systems) if system.id == system_id), None)
        if target_index is None:
            raise ValueError("System not found")
        merge_index = target_index - 1 if boundary == "top" else target_index
        if merge_index < 0 or merge_index >= len(located_systems) - 1:
            raise ValueError("No system break at document boundary")
        _, _, leading = located_systems[merge_index]
        _, _, following = located_systems[merge_index + 1]
        if len(leading.staves) != len(following.staves):
            raise ValueError("Cannot merge systems with different stave counts")

        for leading_stave, following_stave in zip(leading.staves, following.staves, strict=True):
            leading_stave.events.extend(following_stave.events)
            leading_stave.touch()
        leading.events.extend(following.events)
        leading.end_tick = following.end_tick
        leading.touch()

        following_page_index, following_system_index, _ = located_systems[merge_index + 1]
        self.pages[following_page_index].systems.pop(following_system_index)
        self.pages = [page for page in self.pages if page.systems]
        self._repaginate_all_pages()
        return leading

    def paginate_page(self, page_id: str) -> None:
        """Move systems that exceed a page's printable width onto new pages.

        A system's natural width is its stave group plus its own margins. This
        keeps staff-scale and pitch-range edits from shrinking every existing
        column until the notation is unusable.
        """
        page_index = next((index for index, page in enumerate(self.pages) if page.id == page_id), None)
        if page_index is None:
            raise ValueError("Page not found")
        page = self.pages[page_index]
        available_width_mm = page.width_mm - self.layout.page_left_margin_mm - self.layout.page_right_margin_mm
        if available_width_mm <= 0.0:
            raise ValueError("Page margins leave no system space")

        page_groups: list[list[System]] = [[]]
        current_width_mm = 0.0
        for system in page.systems:
            system_width_mm = self._system_required_width_mm(system)
            if page_groups[-1] and current_width_mm + system_width_mm > available_width_mm:
                page_groups.append([])
                current_width_mm = 0.0
            page_groups[-1].append(system)
            current_width_mm += system_width_mm

        page.systems = page_groups[0]
        self._reflow_page_systems(page, self.layout, is_first_page=page_index == 0)
        overflow_pages = [
            Page(
                width_mm=page.width_mm,
                height_mm=page.height_mm,
                systems=systems,
            )
            for systems in page_groups[1:]
        ]
        for overflow_page in overflow_pages:
            self._reflow_page_systems(overflow_page, self.layout, is_first_page=False)
        self.pages[page_index + 1:page_index + 1] = overflow_pages

    def _repaginate_all_pages(self) -> None:
        """Repack automatic pages after a system merge crosses a page boundary."""
        first_page = self.pages[0]
        systems = [system for page in self.pages for system in page.systems]
        self.pages = [Page(width_mm=first_page.width_mm, height_mm=first_page.height_mm, systems=systems)]
        self.paginate_page(self.pages[0].id)

    def repaginate_document(self) -> None:
        """Pack all systems into the fewest automatic pages their widths allow."""
        self._repaginate_all_pages()

    def _system_required_width_mm(self, system: System) -> float:
        stave_widths = [self._stave_required_width_mm(system, stave) for stave in system.staves]
        group_width_mm = sum(stave_widths) + 12.0 * max(0, len(stave_widths) - 1)
        return system.left_margin_mm + group_width_mm + system.right_margin_mm

    def _stave_required_width_mm(self, system: System, stave: Stave) -> float:
        low_pitch, _ = stave.pitch_range
        black_pitches = stave.line_pitches(system)
        if len(black_pitches) < 2:
            return 0.0
        semitone_mm = self.layout.engraving_mm(2.0, stave.scale)
        positions = [Stave.pitch_offset_units(pitch, low_pitch) * semitone_mm for pitch in black_pitches]
        return max(positions) - min(positions)

    @staticmethod
    def _reflow_page_systems(page: Page, layout: Layout, is_first_page: bool = False) -> None:
        """Give systems their page-specific printable height between metadata regions."""
        top_mm = layout.page_top_margin_mm + (layout.header_height_mm if is_first_page else 0.0)
        height_mm = page.height_mm - top_mm - layout.page_bottom_margin_mm - layout.footer_height_mm
        if height_mm <= 0.0:
            raise ValueError("Page margins and header/footer leave no system height")
        for system in page.systems:
            system.top_mm = top_mm
            system.height_mm = height_mm

    @staticmethod
    def _partition_events(events: list[Event], time: int) -> tuple[list[Event], list[Event]]:
        before: list[Event] = []
        after: list[Event] = []
        for event in events:
            event_time = KeyTab2Document._event_start_tick(event)
            (after if event_time >= time else before).append(event)
        return before, after

    @staticmethod
    def _event_start_tick(event: Event) -> int:
        """Return the timeline position that determines an event's system owner."""
        return int(getattr(event, "time", getattr(event, "start_tick", getattr(event, "y1_tick", 0))))

    @staticmethod
    def _split_crossing_notes(original: Stave, following: Stave, time: int) -> None:
        """Turn notes crossing a new system break into linked local segments."""
        for note in tuple(event for event in original.events if isinstance(event, NoteEvent)):
            note_end = note.time + note.duration
            if note_end <= time:
                continue
            continuation = deepcopy(note)
            continuation.id = _new_id()
            continuation.time = time
            continuation.duration = note_end - time
            continuation.continuation_id = note.continuation_id or note.id
            continuation.continues_from_previous = True
            note.duration = time - note.time
            note.continuation_id = continuation.continuation_id
            note.continues_to_next = True
            following.events.append(continuation)

    def _measure_count_before(self, start_tick: int, time: int) -> int:
        from keytab2_model.base_grid import grid_boundaries

        measure_starts, _ = grid_boundaries(self.base_grid, self.time_per_quarter)
        return sum(start_tick <= start < time for start in measure_starts)

    def save(self, path: str | Path) -> None:
        target = Path(path)
        if target.suffix.lower() != ".keytab2":
            raise ValueError("keyTAB2 documents must use the .keytab2 extension")
        with target.open("w", encoding="utf-8") as file:
            json.dump(self.to_dict(), file, indent=2, ensure_ascii=True)

    @classmethod
    def load(cls, path: str | Path) -> "KeyTab2Document":
        source = Path(path)
        if source.suffix.lower() != ".keytab2":
            raise ValueError("keyTAB2 documents must use the .keytab2 extension")
        with source.open(encoding="utf-8") as file:
            data = json.load(file)
        return cls.from_dict(data)

    @classmethod
    def from_dict(cls, data: dict) -> "KeyTab2Document":
        if not isinstance(data, dict):
            raise ValueError("Document root must be an object")
        if data.get("format") != FORMAT_NAME or data.get("format_version") != FORMAT_VERSION:
            raise ValueError("Unsupported keyTAB2 document format")
        time_per_quarter = data.get("time_per_quarter", data.get("ticks_per_quarter"))
        if time_per_quarter != TIME_PER_QUARTER:
            raise ValueError("Unsupported time-per-quarter value")

        info_data = data.get("score_info", {})
        info = ScoreInfo(
            title=str(info_data.get("title", "Untitled")),
            composer=str(info_data.get("composer", "")),
            copyright=str(info_data.get("copyright", "")),
        )
        layout_data = data.get("layout", {})
        if not isinstance(layout_data, dict):
            raise ValueError("Layout must be an object")
        layout_fields = dict(layout_data)
        for field_name in (
            "time_signature_indicator_classic_font",
            "time_signature_indicator_klavarskribo_font",
            "measure_numbering_font",
            "font_text",
            "font_title",
            "font_composer",
            "font_copyright",
            "font_arranger",
            "font_lyricist",
        ):
            font_data = layout_fields.get(field_name)
            if font_data is not None:
                if not isinstance(font_data, dict):
                    raise ValueError(f"Layout {field_name} must be an object")
                try:
                    layout_fields[field_name] = Font(**font_data)
                except TypeError as error:
                    raise ValueError(f"Invalid layout {field_name}") from error
        layout = Layout(**layout_fields)
        base_grid_data = data.get("base_grid", [{"measure_amount": 8}])
        if not isinstance(base_grid_data, list) or not base_grid_data:
            raise ValueError("Document must contain at least one base-grid segment")
        try:
            base_grid = [BaseGrid(**segment) for segment in base_grid_data]
            for segment in base_grid:
                segment.validate()
        except (TypeError, ValueError) as error:
            raise ValueError("Invalid base_grid") from error
        pages_data = data.get("pages")
        if not isinstance(pages_data, list) or not pages_data:
            raise ValueError("Document must contain at least one page")

        pages = [cls._page_from_dict(page_data) for page_data in pages_data]
        for page_index, page in enumerate(pages):
            cls._reflow_page_systems(page, layout, is_first_page=page_index == 0)
        timeline_data = data.get("timeline_events", [])
        if not isinstance(timeline_data, list):
            raise ValueError("Timeline events must be an array")
        timeline_events = [cls._event_from_dict(event_data) for event_data in timeline_data]
        if not all(isinstance(event, TempoEvent) for event in timeline_events):
            raise ValueError("Document timeline supports tempo events only")
        return cls(
            score_info=info,
            layout=layout,
            base_grid=base_grid,
            pages=pages,
            timeline_events=timeline_events,
            created_at=str(data.get("created_at", _timestamp())),
            modified_at=str(data.get("modified_at", _timestamp())),
        )

    @staticmethod
    def _page_from_dict(data: object) -> Page:
        if not isinstance(data, dict):
            raise ValueError("Page must be an object")
        systems_data = data.get("systems")
        if not isinstance(systems_data, list) or not systems_data:
            raise ValueError("Page must contain at least one system")
        return Page(
            width_mm=float(data.get("width_mm", 210.0)),
            height_mm=float(data.get("height_mm", 297.0)),
            systems=[KeyTab2Document._system_from_dict(system_data) for system_data in systems_data],
            events=KeyTab2Document._events_from_dict(data.get("events", [])),
            id=str(data.get("id", _new_id())),
        )

    @staticmethod
    def _system_from_dict(data: object) -> System:
        if not isinstance(data, dict):
            raise ValueError("System must be an object")
        staves_data = data.get("staves")
        if not isinstance(staves_data, list) or not staves_data:
            raise ValueError("System must contain at least one stave")
        start_tick = int(data.get("start_tick", 0))
        end_tick = int(data.get("end_tick", TIME_PER_QUARTER * 16))
        if end_tick <= start_tick:
            raise ValueError("System end_tick must be after start_tick")
        return System(
            start_tick=start_tick,
            end_tick=end_tick,
            first_measure_number=int(data.get("first_measure_number", 1)),
            left_margin_mm=float(data.get("left_margin_mm", 5.0)),
            right_margin_mm=float(data.get("right_margin_mm", 5.0)),
            staves=[KeyTab2Document._stave_from_dict(stave_data) for stave_data in staves_data],
            events=KeyTab2Document._events_from_dict(data.get("events", [])),
            id=str(data.get("id", _new_id())),
        )

    @staticmethod
    def _stave_from_dict(data: object) -> Stave:
        if not isinstance(data, dict):
            raise ValueError("Stave must be an object")
        events_data = data.get("events", [])
        if not isinstance(events_data, list):
            raise ValueError("Stave events must be an array")
        events = KeyTab2Document._events_from_dict(events_data)
        pitch_range = data.get("pitch_range", [36, 84])
        if not isinstance(pitch_range, list) or len(pitch_range) != 2:
            raise ValueError("Stave pitch_range must contain two MIDI pitches")
        low_pitch, high_pitch = (int(pitch_range[0]), int(pitch_range[1]))
        if low_pitch >= high_pitch:
            raise ValueError("Stave pitch_range must be ascending")
        scale = float(data.get("scale", 1.0))
        if scale <= 0.0:
            raise ValueError("Stave scale must be positive")
        return Stave(
            name=str(data.get("name", "Piano")),
            pitch_range=[low_pitch, high_pitch],
            scale=scale,
            events=events,
            id=str(data.get("id", _new_id())),
        )

    @staticmethod
    def _events_from_dict(data: object) -> list[Event]:
        if not isinstance(data, list):
            raise ValueError("Events must be an array")
        return [KeyTab2Document._event_from_dict(event_data) for event_data in data]

    @staticmethod
    def _event_from_dict(data: object) -> Event:
        if not isinstance(data, dict):
            raise ValueError("Event must be an object")
        event_type = data.get("type")
        event_class = EVENT_TYPES.get(event_type)
        if event_class is None:
            raise ValueError(f"Unsupported event type: {event_type!r}")
        fields = {key: value for key, value in data.items() if key != "type"}
        if event_class in (NoteEvent, BeamEvent):
            fields.setdefault("time", fields.pop("start_tick", 0))
            fields.setdefault("duration", fields.pop("duration_ticks", 0))
        try:
            return event_class(**fields)
        except TypeError as error:
            raise ValueError(f"Invalid {event_type} event") from error