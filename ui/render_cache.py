"""Cached final-mm geometry and tick indexes for the direct paper editor."""

from __future__ import annotations

from bisect import bisect_left, bisect_right
from dataclasses import dataclass, replace

from keytab2_model.base_grid import BaseGrid, apply_beam_overrides, beam_windows, grid_boundaries
from keytab2_model.document import Stave, System
from keytab2_model.events import ArpeggioEvent, BeamEvent, NoteEvent
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
    center_tick: float
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
        midpoints = sorted((geometry.start_tick + geometry.end_tick) / 2 for geometry in geometries)
        center_tick = midpoints[len(midpoints) // 2]
        left: list[NoteGeometry | BeamGeometry] = []
        overlaps: list[NoteGeometry | BeamGeometry] = []
        right: list[NoteGeometry | BeamGeometry] = []
        for geometry in geometries:
            if geometry.end_tick < center_tick:
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

    def intersecting(self, start_tick: float, end_tick: float) -> tuple[NoteGeometry | BeamGeometry, ...]:
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

    def beam_right_extent_in_rect(self, left_mm: float, top_mm: float, right_mm: float, bottom_mm: float) -> float | None:
        """Return the right edge of beams that overlap an annotation rectangle."""
        overlapping = [
            beam.right_extent_mm
            for beam in self._geometries.geometries
            if isinstance(beam, BeamGeometry)
            and beam.bounds_mm[0] <= right_mm
            and beam.bounds_mm[2] >= left_mm
            and beam.bounds_mm[1] <= bottom_mm
            and beam.bounds_mm[3] >= top_mm
            and _beam_overlaps_rect(beam, left_mm, top_mm, right_mm, bottom_mm)
        ]
        return max(overlapping, default=None)

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


def build_stave_render_data(
    system: System,
    stave: Stave,
    layout: Layout,
    left_mm: float,
    measure_ticks: int,
    base_grid: list[BaseGrid] | None = None,
    following_starts_by_hand: dict[str, tuple[int, ...]] | None = None,
) -> StaveRenderData:
    """Build immutable stave geometry once after a stave revision changes."""
    notes = tuple(sorted((event for event in stave.events if isinstance(event, NoteEvent)), key=lambda event: (event.time, event.pitch, event.id)))
    resolved_base_grid = base_grid or [BaseGrid()]
    measure_starts, _ = grid_boundaries(resolved_base_grid, measure_ticks // 4)
    semitone_mm = layout.engraving_mm(2.0, stave.scale)
    stem_length_mm = semitone_mm * layout.note_stem_length_semitone
    tick_height = system.height_mm / (system.end_tick - system.start_tick)

    def y_for_tick(tick: int) -> float:
        return system.top_mm + (tick - system.start_tick) * tick_height

    def notehead_parameters(note: NoteEvent) -> tuple[str, bool, bool, float]:
        hand = "left" if note.hand == "left" else "right"
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
        return form, is_up, filled, layout.note_width_scaling * (0.7 if narrow_black else 1.0)

    arpeggio_start_offsets: dict[str, float] = {}
    arpeggio_member_ids: set[str] = set()
    notes_by_id = {note.id: note for note in notes}
    for arpeggio in (event for event in stave.events if isinstance(event, ArpeggioEvent)):
        if arpeggio.rtime1_ticks == arpeggio.rtime2_ticks == 0:
            continue
        members = [notes_by_id[note_id] for note_id in arpeggio.note_ids if note_id in notes_by_id]
        members = sorted(
            (note for note in members if note.time == arpeggio.start_tick and note.hand == arpeggio.hand),
            key=lambda note: note.pitch,
        )
        if len(members) < 2:
            continue
        arpeggio_member_ids.update(member.id for member in members)
        low, high = members[0], members[-1]
        low_x_mm = StaveDrawer.pitch_to_x_mm(low.pitch, stave.pitch_range[0], left_mm, semitone_mm)
        high_x_mm = StaveDrawer.pitch_to_x_mm(high.pitch, stave.pitch_range[0], left_mm, semitone_mm)
        low_y_mm = y_for_tick(arpeggio.start_tick + arpeggio.rtime1_ticks)
        high_y_mm = y_for_tick(arpeggio.start_tick + arpeggio.rtime2_ticks)
        if abs(high_x_mm - low_x_mm) <= 1e-9:
            continue
        slope = (high_y_mm - low_y_mm) / (high_x_mm - low_x_mm)
        anchor = high if arpeggio.hand == "left" else low
        anchor_x_mm = high_x_mm if arpeggio.hand == "left" else low_x_mm
        anchor_y_mm = high_y_mm if arpeggio.hand == "left" else low_y_mm
        form, is_up, filled, width_scale = notehead_parameters(anchor)
        anchor_head = build_notehead_outline(
            anchor_x_mm, anchor_y_mm, anchor.hand, form, is_up, filled, semitone_mm,
            width_scale, layout.notehead_height_scaling, layout.notehead_tilt,
        )
        residuals = [point_y - slope * point_x for point_x, point_y in anchor_head.points_mm]
        line_intercept = max(residuals) if is_up else min(residuals)
        for member in members:
            member_x_mm = StaveDrawer.pitch_to_x_mm(member.pitch, stave.pitch_range[0], left_mm, semitone_mm)
            form, is_up, filled, width_scale = notehead_parameters(member)
            member_head = build_notehead_outline(
                member_x_mm, 0.0, member.hand, form, is_up, filled, semitone_mm,
                width_scale, layout.notehead_height_scaling, layout.notehead_tilt,
            )
            residuals = [point_y - slope * point_x for point_x, point_y in member_head.points_mm]
            support_residual = max(residuals) if is_up else min(residuals)
            original_y_mm = y_for_tick(member.time)
            arpeggio_start_offsets[member.id] = (line_intercept - support_residual - original_y_mm) / tick_height

    starts_by_hand: dict[str, list[int]] = {"left": [], "right": []}
    ends_by_hand: dict[str, list[int]] = {"left": [], "right": []}
    for note in notes:
        hand = "left" if note.hand == "left" else "right"
        starts_by_hand[hand].append(note.time)
        ends_by_hand[hand].append(note.time + note.duration)
    for hand in starts_by_hand:
        ends_by_hand[hand].sort()

    following_starts_by_hand = following_starts_by_hand or {}

    geometries: list[NoteGeometry] = []
    for note in notes:
        hand = "left" if note.hand == "left" else "right"
        start_tick = max(system.start_tick, note.time)
        end_tick = min(system.end_tick, note.time + note.duration)
        if end_tick <= start_tick:
            continue
        x_mm = StaveDrawer.pitch_to_x_mm(note.pitch, stave.pitch_range[0], left_mm, semitone_mm)
        visual_offset_ticks = arpeggio_start_offsets.get(note.id, 0)
        visual_start_tick = start_tick + visual_offset_ticks
        visual_end_tick = max(end_tick, visual_start_tick + 1)
        y_start_mm = y_for_tick(visual_start_tick)
        y_end_mm = y_for_tick(end_tick)
        stem_tip_mm = x_mm - stem_length_mm if hand == "left" else x_mm + stem_length_mm
        body_points = ((x_mm, y_start_mm), (x_mm - semitone_mm, y_start_mm + semitone_mm), (x_mm - semitone_mm, y_end_mm), (x_mm + semitone_mm, y_end_mm), (x_mm + semitone_mm, y_start_mm + semitone_mm))
        form, is_up, filled, width_scale = notehead_parameters(note)
        head = build_notehead_outline(x_mm, y_start_mm, hand, form, is_up, filled, semitone_mm, width_scale, layout.notehead_height_scaling, layout.notehead_tilt)
        next_start_index = bisect_left(starts_by_hand[hand], end_tick)
        has_following_note = (
            next_start_index != len(starts_by_hand[hand])
            and starts_by_hand[hand][next_start_index] == end_tick
        ) or any(start_tick == end_tick for start_tick in following_starts_by_hand.get(hand, ()))
        stop_points = None
        if not note.continues_to_next and not has_following_note:
            head_width_mm = max(point[0] for point in head.points_mm) - min(point[0] for point in head.points_mm)
            stop_points = ((x_mm - head_width_mm * 0.5, y_end_mm - head_width_mm), (x_mm, y_end_mm), (x_mm + head_width_mm * 0.5, y_end_mm - head_width_mm))
        dot_ticks = set()
        for tick_list in (starts_by_hand[hand], ends_by_hand[hand]):
            first = bisect_right(tick_list, start_tick)
            last = bisect_left(tick_list, end_tick)
            dot_ticks.update(tick_list[first:last])
        dot_ticks.update(tick for tick in measure_starts if start_tick < tick < end_tick)
        dot_centres = tuple(
            (x_mm, y_for_tick(tick) + semitone_mm)
            for tick in sorted(dot_ticks)
            if visual_start_tick < tick < end_tick
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
            visual_start_tick,
            visual_end_tick,
            hand,
            note.continues_from_previous,
            note.continues_to_next,
            body_points,
            head,
            color,
            layout.engraving_mm(layout.note_stem_thickness_mm, stave.scale),
            layout.engraving_mm(layout.note_stem_thickness_mm, stave.scale),
            layout.engraving_mm(layout.note_stopsign_thickness_mm, stave.scale),
            (x_mm, y_start_mm, x_mm, y_start_mm) if note.id in arpeggio_member_ids else (x_mm, y_start_mm, stem_tip_mm, y_start_mm),
            None,
            stop_points,
            dot_centres,
            (left_bound, top_bound, right_bound, bottom_bound),
            right_bound,
        ))

    chord_interior_ids: set[str] = set()
    chord_comparison = Operator(SHORTEST_DURATION)
    for hand in ("left", "right"):
        hand_notes = [note for note in geometries if note.hand == hand and note.event_id not in arpeggio_member_ids]
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
    notes_by_id = {note.id: note for note in notes}
    for hand in ("left", "right"):
        overrides = [(start, end) for start, end, _ in markers_by_hand[hand]]
        marker_ids = {(start, end): event_id for start, end, event_id in markers_by_hand[hand]}
        for window_start, window_end in apply_beam_overrides(default_windows, overrides):
            members = [
                note for note in geometries
                if note.hand == hand
                and note.event_id not in chord_interior_ids
                and note.event_id not in arpeggio_member_ids
                and window_start <= note.start_tick < window_end
            ]
            if len(members) < 2:
                continue
            continuation_members = [
                geometry
                for geometry in geometries
                for note in (notes_by_id[geometry.event_id],)
                if geometry.hand == hand
                and geometry.event_id not in chord_interior_ids
                and note.time < window_start < note.time + note.duration
                and any(
                    note.time < tick < note.time + note.duration
                    and window_start <= tick < window_end
                    for tick in (*starts_by_hand[hand], *ends_by_hand[hand], *measure_starts)
                )
            ]
            first, last = members[0], members[-1]
            pitch_anchor = min((*members, *continuation_members), key=lambda note: note.stem[0]) if hand == "left" else max((*members, *continuation_members), key=lambda note: note.stem[0])
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


def _beam_overlaps_rect(beam: BeamGeometry, left_mm: float, top_mm: float, right_mm: float, bottom_mm: float) -> bool:
    rectangle = ((left_mm, top_mm), (right_mm, top_mm), (right_mm, bottom_mm), (left_mm, bottom_mm))
    if any(_point_in_rect(point, left_mm, top_mm, right_mm, bottom_mm) for point in beam.polygon_mm):
        return True
    if any(_point_in_polygon(x_mm, y_mm, beam.polygon_mm) for x_mm, y_mm in rectangle):
        return True
    polygon_edges = zip(beam.polygon_mm, (*beam.polygon_mm[1:], beam.polygon_mm[0]), strict=True)
    rectangle_edges = zip(rectangle, (*rectangle[1:], rectangle[0]), strict=True)
    if any(_segments_intersect(first, second, third, fourth) for first, second in polygon_edges for third, fourth in rectangle_edges):
        return True
    half_width_mm = beam.connector_width_mm * 0.5
    return any(
        _segment_intersects_rect(
            (x1_mm, y1_mm, x2_mm, y2_mm),
            left_mm - half_width_mm,
            top_mm - half_width_mm,
            right_mm + half_width_mm,
            bottom_mm + half_width_mm,
        )
        for x1_mm, y1_mm, x2_mm, y2_mm in beam.segments_mm
    )


def _point_in_rect(point: tuple[float, float], left_mm: float, top_mm: float, right_mm: float, bottom_mm: float) -> bool:
    x_mm, y_mm = point
    return left_mm <= x_mm <= right_mm and top_mm <= y_mm <= bottom_mm


def _segment_intersects_rect(line: tuple[float, float, float, float], left_mm: float, top_mm: float, right_mm: float, bottom_mm: float) -> bool:
    x1_mm, y1_mm, x2_mm, y2_mm = line
    if _point_in_rect((x1_mm, y1_mm), left_mm, top_mm, right_mm, bottom_mm) or _point_in_rect((x2_mm, y2_mm), left_mm, top_mm, right_mm, bottom_mm):
        return True
    rectangle = ((left_mm, top_mm), (right_mm, top_mm), (right_mm, bottom_mm), (left_mm, bottom_mm))
    return any(
        _segments_intersect((x1_mm, y1_mm), (x2_mm, y2_mm), start, end)
        for start, end in zip(rectangle, (*rectangle[1:], rectangle[0]), strict=True)
    )


def _segments_intersect(first_start: tuple[float, float], first_end: tuple[float, float], second_start: tuple[float, float], second_end: tuple[float, float]) -> bool:
    def orientation(start: tuple[float, float], end: tuple[float, float], point: tuple[float, float]) -> float:
        return (end[0] - start[0]) * (point[1] - start[1]) - (end[1] - start[1]) * (point[0] - start[0])

    first_start_side = orientation(second_start, second_end, first_start)
    first_end_side = orientation(second_start, second_end, first_end)
    second_start_side = orientation(first_start, first_end, second_start)
    second_end_side = orientation(first_start, first_end, second_end)
    return first_start_side * first_end_side <= 0.0 and second_start_side * second_end_side <= 0.0


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