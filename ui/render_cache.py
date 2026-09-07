"""Cached final-mm geometry and tick indexes for the direct paper editor."""

from __future__ import annotations

from bisect import bisect_left, bisect_right
from dataclasses import dataclass, replace

from keytab2_model.base_grid import BaseGrid, apply_beam_overrides, beam_windows, grid_boundaries
from keytab2_model.document import Stave, System
from keytab2_model.events import BeamEvent, NoteEvent
from keytab2_model.layout import Layout
from ui.drawers.stave_drawer import StaveDrawer
from ui.notehead_geometry import NoteheadGeometry, build_notehead_outline, resolve_notehead
from utils.CONSTANT import SHORTEST_DURATION
from utils.operator import Operator


Bounds = tuple[float, float, float, float]


@dataclass(frozen=True)
class NoteGeometry:
    event_id: str
    start_tick: int
    end_tick: int
    hand: str
    continues_from_previous: bool
    continues_to_next: bool
    body_points_mm: tuple[tuple[float, float], ...]
    head: NoteheadGeometry
    body_color: tuple[float, float, float]
    head_outline_width_mm: float
    stem_width_mm: float
    stop_width_mm: float
    stem: tuple[float, float, float, float]
    chord_connector: tuple[float, float, float, float] | None
    stop_points_mm: tuple[tuple[float, float], ...] | None
    continuation_dot_centres_mm: tuple[tuple[float, float], ...]
    bounds_mm: Bounds
    right_extent_mm: float

    def hit_part(self, x_mm: float, y_mm: float) -> str | None:
        """Return the precise editable note region containing one paper point."""
        if _point_in_polygon(x_mm, y_mm, self.head.points_mm):
            return "head"
        if _point_in_polygon(x_mm, y_mm, self.body_points_mm):
            return "body"
        return None


@dataclass(frozen=True)
class BeamGeometry:
    event_id: str
    start_tick: int
    end_tick: int
    polygon_mm: tuple[tuple[float, float], ...]
    segments_mm: tuple[tuple[float, float, float, float], ...]
    connector_width_mm: float
    bounds_mm: Bounds
    right_extent_mm: float


@dataclass(frozen=True)
class _IntervalNode:
    center_tick: int
    overlaps: tuple[NoteGeometry | BeamGeometry, ...]
    left: "_IntervalNode | None"
    right: "_IntervalNode | None"


class TickIndex:
    """Immutable interval tree for $O(log n + k)$ visible-tick queries."""

    def __init__(self, geometries: tuple[NoteGeometry | BeamGeometry, ...]) -> None:
        self.geometries = tuple(sorted(geometries, key=lambda geometry: geometry.start_tick))
        self._root = self._build_tree(self.geometries)

    @classmethod
    def _build_tree(cls, geometries: tuple[NoteGeometry | BeamGeometry, ...]) -> _IntervalNode | None:
        if not geometries:
            return None
        midpoints = sorted((geometry.start_tick + geometry.end_tick) // 2 for geometry in geometries)
        center_tick = midpoints[len(midpoints) // 2]
        left: list[NoteGeometry | BeamGeometry] = []
        overlaps: list[NoteGeometry | BeamGeometry] = []
        right: list[NoteGeometry | BeamGeometry] = []
        for geometry in geometries:
            if geometry.end_tick <= center_tick:
                left.append(geometry)
            elif geometry.start_tick > center_tick:
                right.append(geometry)
            else:
                overlaps.append(geometry)
        return _IntervalNode(
            center_tick,
            tuple(overlaps),
            cls._build_tree(tuple(left)),
            cls._build_tree(tuple(right)),
        )

    def intersecting(self, start_tick: int, end_tick: int) -> tuple[NoteGeometry | BeamGeometry, ...]:
        result: list[NoteGeometry | BeamGeometry] = []

        def visit(node: _IntervalNode | None) -> None:
            if node is None:
                return
            if end_tick <= node.center_tick:
                result.extend(geometry for geometry in node.overlaps if geometry.start_tick < end_tick)
                visit(node.left)
            elif start_tick > node.center_tick:
                result.extend(geometry for geometry in node.overlaps if geometry.end_tick > start_tick)
                visit(node.right)
            else:
                result.extend(node.overlaps)
                visit(node.left)
                visit(node.right)

        visit(self._root)
        return tuple(sorted(result, key=lambda geometry: (geometry.start_tick, geometry.event_id)))


class MeasureCollisionIndex:
    """Note/beam extents by measure for surrounding annotation placement."""

    def __init__(self, notes: tuple[NoteGeometry, ...], beams: tuple[BeamGeometry, ...]) -> None:
        self._geometries = TickIndex(notes + beams)

    def right_extent_mm(self, start_tick: int, end_tick: int, default_mm: float) -> float:
        return max((geometry.right_extent_mm for geometry in self._geometries.intersecting(start_tick, end_tick)), default=default_mm)

    def left_extent_mm(self, start_tick: int, end_tick: int, default_mm: float) -> float:
        return min((geometry.bounds_mm[0] for geometry in self._geometries.intersecting(start_tick, end_tick)), default=default_mm)

    def horizontal_occlusion_intervals(self, y_mm: float, padding_mm: float = 0.0) -> tuple[tuple[float, float], ...]:
        """Return merged x intervals occupied by rendered notation at one y."""
        intervals: list[tuple[float, float]] = []
        for geometry in self._geometries.geometries:
            if geometry.bounds_mm[1] > y_mm or geometry.bounds_mm[3] < y_mm:
                continue
            if isinstance(geometry, NoteGeometry):
                for polygon in (geometry.head.points_mm, geometry.stop_points_mm):
                    if polygon is not None:
                        interval = _polygon_interval_at_y(polygon, y_mm)
                        if interval is not None:
                            intervals.append(interval)
                intervals.extend(interval for line in (geometry.stem, geometry.chord_connector) if line is not None if (interval := _line_interval_at_y(line, y_mm, geometry.stem_width_mm)) is not None)
                intervals.extend((x_mm - geometry.stem_width_mm * 0.5, x_mm + geometry.stem_width_mm * 0.5) for x_mm, dot_y_mm in geometry.continuation_dot_centres_mm if abs(dot_y_mm - y_mm) <= geometry.stem_width_mm * 0.5)
            else:
                interval = _polygon_interval_at_y(geometry.polygon_mm, y_mm)
                if interval is not None:
                    intervals.append(interval)
                intervals.extend(interval for line in geometry.segments_mm if (interval := _line_interval_at_y(line, y_mm, geometry.connector_width_mm)) is not None)
        padded = sorted((start - padding_mm, end + padding_mm) for start, end in intervals)
        merged: list[tuple[float, float]] = []
        for start, end in padded:
            if merged and start <= merged[-1][1]:
                merged[-1] = (merged[-1][0], max(merged[-1][1], end))
            else:
                merged.append((start, end))
        return tuple(merged)


@dataclass(frozen=True)
class StaveRenderData:
    stave_id: str
    revision: int
    notes: TickIndex
    beams: TickIndex
    collision_index: MeasureCollisionIndex

    def notes_in_tick_range(self, start_tick: int, end_tick: int) -> tuple[NoteGeometry, ...]:
        return tuple(self.notes.intersecting(start_tick, end_tick))

    def beams_in_tick_range(self, start_tick: int, end_tick: int) -> tuple[BeamGeometry, ...]:
        return tuple(self.beams.intersecting(start_tick, end_tick))

    def hit_test(self, x_mm: float, y_mm: float) -> tuple[str, str] | None:
        for note in reversed(self.notes.geometries):
            part = note.hit_part(x_mm, y_mm)
            if part is not None:
                return note.event_id, part
        return None


def build_stave_render_data(system: System, stave: Stave, layout: Layout, left_mm: float, measure_ticks: int, base_grid: list[BaseGrid] | None = None) -> StaveRenderData:
    """Build immutable stave geometry once after a stave revision changes."""
    notes = tuple(sorted((event for event in stave.events if isinstance(event, NoteEvent)), key=lambda event: (event.time, event.pitch, event.id)))
    resolved_base_grid = base_grid or [BaseGrid()]
    measure_starts, _ = grid_boundaries(resolved_base_grid, measure_ticks // 4)
    semitone_mm = layout.engraving_mm(2.0, stave.scale)
    stem_length_mm = semitone_mm * layout.note_stem_length_semitone
    tick_height = system.height_mm / (system.end_tick - system.start_tick)

    def y_for_tick(tick: int) -> float:
        return system.top_mm + (tick - system.start_tick) * tick_height

    starts_by_hand: dict[str, list[int]] = {"left": [], "right": []}
    ends_by_hand: dict[str, list[int]] = {"left": [], "right": []}
    for note in notes:
        hand = "left" if note.hand == "left" else "right"
        starts_by_hand[hand].append(note.time)
        ends_by_hand[hand].append(note.time + note.duration)
    for hand in starts_by_hand:
        ends_by_hand[hand].sort()

    geometries: list[NoteGeometry] = []
    for note in notes:
        hand = "left" if note.hand == "left" else "right"
        start_tick = max(system.start_tick, note.time)
        end_tick = min(system.end_tick, note.time + note.duration)
        if end_tick <= start_tick:
            continue
        x_mm = StaveDrawer.pitch_to_x_mm(note.pitch, stave.pitch_range[0], left_mm, semitone_mm)
        y_start_mm = y_for_tick(start_tick)
        y_end_mm = y_for_tick(end_tick)
        stem_tip_mm = x_mm - stem_length_mm if hand == "left" else x_mm + stem_length_mm
        body_points = ((x_mm, y_start_mm), (x_mm - semitone_mm, y_start_mm + semitone_mm), (x_mm - semitone_mm, y_end_mm), (x_mm + semitone_mm, y_end_mm), (x_mm + semitone_mm, y_start_mm + semitone_mm))
        simultaneous = [other for other in notes if other.time == note.time and other.id != note.id]
        has_adjacent_note = any(abs(other.pitch - note.pitch) == 1 for other in simultaneous)
        has_white_chord_note_same_hand = any(
            other.hand == hand and other.pitch % 12 not in {1, 3, 6, 8, 10}
            for other in simultaneous
        )
        black_above = (
            layout.black_note_rule == "above_stem"
            or (layout.black_note_rule == "above_stem_if_collision" and has_adjacent_note)
            or (
                layout.black_note_rule == "above_stem_if_chord_and_white_note_same_hand"
                and has_white_chord_note_same_hand
            )
        )
        form, is_up, filled = resolve_notehead(note.notehead, note.pitch, black_above)
        narrow_black = note.pitch % 12 in {1, 3, 6, 8, 10} and layout.black_note_rule == "below_stem" and has_adjacent_note
        head = build_notehead_outline(x_mm, y_start_mm, hand, form, is_up, filled, semitone_mm, layout.note_width_scaling * (0.7 if narrow_black else 1.0), layout.notehead_height_scaling, layout.notehead_tilt)
        next_start_index = bisect_left(starts_by_hand[hand], end_tick)
        stop_points = None
        if not note.continues_to_next and (next_start_index == len(starts_by_hand[hand]) or starts_by_hand[hand][next_start_index] > end_tick):
            stop_size_mm = layout.engraving_mm(layout.note_stopsign_thickness_mm, stave.scale) * 2.0
            stop_points = ((x_mm - stop_size_mm * 0.5, y_end_mm - stop_size_mm), (x_mm, y_end_mm), (x_mm + stop_size_mm * 0.5, y_end_mm - stop_size_mm))
        dot_ticks = set()
        for tick_list in (starts_by_hand[hand], ends_by_hand[hand]):
            first = bisect_right(tick_list, start_tick)
            last = bisect_left(tick_list, end_tick)
            dot_ticks.update(tick_list[first:last])
        dot_ticks.update(tick for tick in measure_starts if start_tick < tick < end_tick)
        dot_centres = tuple(
            (x_mm, y_for_tick(tick) + semitone_mm)
            for tick in sorted(dot_ticks)
        )
        head_xs = [point[0] for point in head.points_mm]
        head_ys = [point[1] for point in head.points_mm]
        left_bound = min(*head_xs, stem_tip_mm, *(point[0] for point in body_points))
        right_bound = max(*head_xs, stem_tip_mm, *(point[0] for point in body_points))
        top_bound = min(*head_ys, y_start_mm)
        bottom_bound = max(*head_ys, y_end_mm)
        color = _color_from_string(note.color, layout.note_midinote_left_color if hand == "left" else layout.note_midinote_right_color)
        geometries.append(NoteGeometry(
            note.id,
            start_tick,
            end_tick,
            hand,
            note.continues_from_previous,
            note.continues_to_next,
            body_points,
            head,
            color,
            layout.engraving_mm(layout.note_stem_thickness_mm, stave.scale),
            layout.engraving_mm(layout.note_stem_thickness_mm, stave.scale),
            layout.engraving_mm(layout.note_stopsign_thickness_mm, stave.scale),
            (x_mm, y_start_mm, stem_tip_mm, y_start_mm),
            None,
            stop_points,
            dot_centres,
            (left_bound, top_bound, right_bound, bottom_bound),
            right_bound,
        ))

    chord_interior_ids: set[str] = set()
    chord_comparison = Operator(SHORTEST_DURATION)
    for hand in ("left", "right"):
        hand_notes = [note for note in geometries if note.hand == hand]
        chord_groups: list[list[NoteGeometry]] = []
        for note in hand_notes:
            if chord_groups and chord_comparison.eq(note.start_tick, chord_groups[-1][0].start_tick):
                chord_groups[-1].append(note)
            else:
                chord_groups.append([note])
        for chord in chord_groups:
            if len(chord) < 2:
                continue
            ordered = sorted(chord, key=lambda note: note.stem[0])
            anchor = ordered[0] if hand == "left" else ordered[-1]
            connector = (ordered[0].stem[0], anchor.stem[1], ordered[-1].stem[0], anchor.stem[1])
            for note in chord:
                index = geometries.index(note)
                if note.event_id == anchor.event_id:
                    geometries[index] = replace(note, chord_connector=connector)
                else:
                    chord_interior_ids.add(note.event_id)
                    geometries[index] = replace(note, stem=(note.stem[0], note.stem[1], note.stem[0], note.stem[1]))

    default_windows = beam_windows(resolved_base_grid, measure_ticks // 4)
    markers_by_hand = {"left": [], "right": []}
    for beam in (event for event in stave.events if isinstance(event, BeamEvent)):
        hand = "left" if beam.hand == "left" else "right"
        markers_by_hand[hand].append((beam.time, beam.time + beam.duration, beam.id))

    beam_geometries: list[BeamGeometry] = []
    for hand in ("left", "right"):
        overrides = [(start, end) for start, end, _ in markers_by_hand[hand]]
        marker_ids = {(start, end): event_id for start, end, event_id in markers_by_hand[hand]}
        for window_start, window_end in apply_beam_overrides(default_windows, overrides):
            members = [
                note for note in geometries
                if note.hand == hand
                and note.event_id not in chord_interior_ids
                and window_start <= note.start_tick < window_end
            ]
            if len(members) < 2:
                continue
            first, last = members[0], members[-1]
            pitch_anchor = min(members, key=lambda note: note.stem[0]) if hand == "left" else max(members, key=lambda note: note.stem[0])
            beam_x1 = pitch_anchor.stem[2]
            beam_x2 = beam_x1 - semitone_mm if hand == "left" else beam_x1 + semitone_mm
            beam_y1 = first.stem[1]
            beam_y2 = last.stem[1]
            beam_width_mm = layout.engraving_mm(layout.beam_thickness_mm, stave.scale)
            beam_half_width_mm = beam_width_mm * 0.5
            stem_half_width_mm = layout.engraving_mm(layout.note_stem_thickness_mm, stave.scale) * 0.5
            polygon = (
                (beam_x1 - beam_half_width_mm, beam_y1 - stem_half_width_mm),
                (beam_x2 - beam_half_width_mm, beam_y2 + stem_half_width_mm),
                (beam_x2 + beam_half_width_mm, beam_y2 + stem_half_width_mm),
                (beam_x1 + beam_half_width_mm, beam_y1 - stem_half_width_mm),
            )
            segments = []
            for member in members:
                fraction = (member.start_tick - first.start_tick) / max(1, last.start_tick - first.start_tick)
                beam_x = beam_x1 + (beam_x2 - beam_x1) * fraction
                segments.append((member.stem[2], member.stem[1], beam_x, member.stem[1]))
            xs = [point[0] for point in polygon] + [coordinate for segment in segments for coordinate in (segment[0], segment[2])]
            ys = [point[1] for point in polygon] + [coordinate for segment in segments for coordinate in (segment[1], segment[3])]
            event_id = marker_ids.get((window_start, window_end), f"automatic-beam:{hand}:{window_start}:{window_end}")
            beam_geometries.append(BeamGeometry(event_id, window_start, window_end, polygon, tuple(segments), stem_half_width_mm * 2.0, (min(xs), min(ys), max(xs), max(ys)), max(xs)))

    note_tuple = tuple(geometries)
    beam_tuple = tuple(beam_geometries)
    return StaveRenderData(stave.id, stave.revision, TickIndex(note_tuple), TickIndex(beam_tuple), MeasureCollisionIndex(note_tuple, beam_tuple))


def _color_from_string(value: str, fallback: str) -> tuple[float, float, float]:
    color = fallback if str(value).strip().lower() == "auto" else str(value)
    if len(color) == 4 and color.startswith("#"):
        color = "#" + "".join(component * 2 for component in color[1:])
    if len(color) == 7 and color.startswith("#"):
        return tuple(int(color[offset:offset + 2], 16) / 255.0 for offset in (1, 3, 5))
    return (0.8, 0.8, 0.8)


def _polygon_interval_at_y(points: tuple[tuple[float, float], ...], y_mm: float) -> tuple[float, float] | None:
    intersections: list[float] = []
    previous_x, previous_y = points[-1]
    for current_x, current_y in points:
        if previous_y == current_y == y_mm:
            intersections.extend((previous_x, current_x))
        elif (previous_y <= y_mm < current_y) or (current_y <= y_mm < previous_y):
            fraction = (y_mm - previous_y) / (current_y - previous_y)
            intersections.append(previous_x + (current_x - previous_x) * fraction)
        previous_x, previous_y = current_x, current_y
    return (min(intersections), max(intersections)) if intersections else None


def _line_interval_at_y(line: tuple[float, float, float, float], y_mm: float, width_mm: float) -> tuple[float, float] | None:
    x1_mm, y1_mm, x2_mm, y2_mm = line
    half_width_mm = width_mm * 0.5
    if min(y1_mm, y2_mm) - half_width_mm <= y_mm <= max(y1_mm, y2_mm) + half_width_mm:
        return min(x1_mm, x2_mm) - half_width_mm, max(x1_mm, x2_mm) + half_width_mm
    return None


def _point_in_polygon(x_mm: float, y_mm: float, points: tuple[tuple[float, float], ...]) -> bool:
    """Test a point against an exact closed render polygon."""
    inside = False
    previous_x, previous_y = points[-1]
    for current_x, current_y in points:
        crosses = (current_y > y_mm) != (previous_y > y_mm)
        if crosses and x_mm < (previous_x - current_x) * (y_mm - current_y) / (previous_y - current_y) + current_x:
            inside = not inside
        previous_x, previous_y = current_x, current_y
    return inside