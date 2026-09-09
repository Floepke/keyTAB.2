"""Direct manipulation of notes on the paper."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from PySide6.QtCore import QPointF

from keytab2_model import NoteEvent
from ui.render_cache import NoteGeometry
from ui.tools.base_tool import BaseTool
from utils.CONSTANT import SHORTEST_DURATION
from utils.operator import Operator

if TYPE_CHECKING:
    from keytab2_model.document import Stave, System


@dataclass
class _NoteEdit:
    system: System
    stave: Stave
    note: NoteEvent
    move_notehead: bool
    ledger_layout_before: tuple[tuple[str, str, tuple[int, ...]], ...]
    source_left_mm: float | None = None
    pending_duration_target: tuple[System, float] | None = None
    preview_geometry: NoteGeometry | None = None
    original_event_index: int | None = None
    original_time: int | None = None
    original_pitch: int | None = None
    preview_time: int | None = None
    preview_pitch: int | None = None


class NoteTool(BaseTool):
    """Create, resize, reposition, and delete notes for one selected hand."""

    TOOL_NAME = "note"
    SNAP_TICKS = 64.0

    def __init__(self, hand: str = "left") -> None:
        super().__init__()
        self.hand = hand
        self._edit: _NoteEdit | None = None

    def set_hand(self, hand: str) -> None:
        if hand not in ("left", "right"):
            raise ValueError("Note hand must be 'left' or 'right'")
        self.hand = hand

    @property
    def is_editing(self) -> bool:
        return self._edit is not None

    @property
    def drag_preview(self) -> _NoteEdit | None:
        """Return a deferred notehead edit drawn by the canvas overlay."""
        return self._edit if self._edit is not None and self._edit.preview_geometry is not None else None

    @property
    def duration_preview(self) -> _NoteEdit | None:
        """Return a pending duration endpoint for the lightweight drag overlay."""
        return self._edit if self._edit is not None and self._edit.pending_duration_target is not None else None

    def on_left_press(self, position_mm: QPointF) -> bool:
        if self.canvas is None:
            return False
        self.canvas.update_mouse_cursor(position_mm)
        existing = self.canvas.note_at(position_mm)
        if existing is not None:
            existing_system, existing_stave, note, geometry, part = existing
            system, stave = existing_system, existing_stave
            self.canvas.select_note_hand(note.hand)
            deferred_preview = part == "head" and note.continuation_id is None
            source_left_mm = self.canvas.stave_left_mm(system, stave) if deferred_preview else None
            event_index = stave.events.index(note) if deferred_preview else None
            if deferred_preview:
                stave.events.pop(event_index)
                stave.touch()
                self.canvas.invalidate_system_render_cache(system.id, stave.id)
            self._edit = _NoteEdit(
                system,
                stave,
                note,
                part == "head",
                self.canvas.ledger_layout_signature(),
                source_left_mm,
                None,
                geometry if deferred_preview else None,
                event_index,
                note.time if deferred_preview else None,
                note.pitch if deferred_preview else None,
                note.time if deferred_preview else None,
                note.pitch if deferred_preview else None,
            )
            return True

        target = self.canvas.stave_at(position_mm, include_ledger_bounds=False)
        if target is None:
            return False
        system, stave, left_mm = target

        time = self.canvas.mouse_time
        pitch = self.canvas.mouse_pitch
        if time is None or pitch is None:
            return False
        ledger_layout_before = self.canvas.ledger_layout_signature()
        note = NoteEvent(time=time, duration=self.canvas.input_snap_ticks, pitch=pitch, hand=self.hand)
        if not self._can_place(stave, note):
            return True
        stave.events.append(note)
        stave.touch()
        self.canvas.invalidate_system_render_cache(system.id, stave.id)
        self._edit = _NoteEdit(system, stave, note, False, ledger_layout_before)
        return True

    def on_left_drag(self, position_mm: QPointF) -> bool:
        if self.canvas is None or self._edit is None:
            return False
        self.canvas.update_mouse_cursor(position_mm)
        edit = self._edit
        if edit.move_notehead:
            left_mm = edit.source_left_mm if edit.source_left_mm is not None else self.canvas.stave_left_mm(edit.system, edit.stave)
            time = self.canvas.snap_time(edit.system, position_mm.y(), self.canvas.input_snap_ticks, edit.note.duration)
            pitch = self.canvas.pitch_at(edit.stave, left_mm, position_mm.x(), allow_outside_range=True)
            time = min(time, edit.system.end_tick - edit.note.duration)
            candidate = NoteEvent(time=time, duration=edit.note.duration, pitch=pitch, hand=edit.note.hand, id=edit.note.id)
            if not self._can_place(edit.stave, candidate, ignored_id=edit.note.id):
                return True
            if edit.preview_geometry is not None:
                if (edit.preview_time, edit.preview_pitch) == (time, pitch):
                    return True
                edit.preview_time = time
                edit.preview_pitch = pitch
                self.canvas.update()
                return True
            if (edit.note.time, edit.note.pitch) == (time, pitch):
                return True
            edit.note.time = time
            edit.note.pitch = pitch
        else:
            duration_target = self._duration_target_at(edit, position_mm)
            if duration_target is None:
                return True
            edit.pending_duration_target = duration_target
            self.canvas.update()
            return True
        edit.stave.touch()
        self.canvas.invalidate_system_render_cache(edit.system.id, edit.stave.id)
        return True

    def on_left_release(self, position_mm: QPointF) -> bool:
        handled = self._edit is not None
        edit = self._edit
        ledger_layout_before = edit.ledger_layout_before if edit is not None else ()
        if edit is not None and edit.preview_geometry is not None:
            edit.note.time = edit.preview_time if edit.preview_time is not None else edit.note.time
            edit.note.pitch = edit.preview_pitch if edit.preview_pitch is not None else edit.note.pitch
            edit.stave.events.insert(edit.original_event_index if edit.original_event_index is not None else len(edit.stave.events), edit.note)
            edit.stave.touch()
            self.canvas.invalidate_system_render_cache(edit.system.id, edit.stave.id)
        elif edit is not None and edit.pending_duration_target is not None:
            duration_target = self._duration_target_at(edit, position_mm)
            if duration_target is not None:
                target_system, end_time = duration_target
                self._set_spanning_duration(edit, target_system, end_time)
                self.canvas.invalidate_render_cache()
        self._edit = None
        if handled and self.canvas is not None:
            self.canvas.repaginate_if_ledger_layout_changed(ledger_layout_before)
            self.canvas.commit_document_change()
        return handled

    def _duration_target_at(self, edit: _NoteEdit, position_mm: QPointF) -> tuple[System, float] | None:
        if self.canvas is None:
            return None
        target = self.canvas.stave_at(position_mm, allow_outside_range=True)
        if target is None:
            return None
        target_system, target_stave, _ = target
        if target_stave is not self._matching_stave(edit.system, edit.stave, target_system):
            return None
        end_time = max(
            self.canvas.snap_time(target_system, position_mm.y(), self.canvas.input_snap_ticks),
            target_system.start_tick + self.canvas.input_snap_ticks,
        )
        if end_time <= edit.note.time:
            return None
        return target_system, end_time

    def on_right_click(self, position_mm: QPointF) -> bool:
        if self.canvas is None:
            return False
        self.canvas.update_mouse_cursor(position_mm)
        hit = self.canvas.note_at(position_mm)
        existing = (hit[0], hit[1], hit[2]) if hit is not None else self.canvas.note_at_mouse_cursor()
        if existing is None:
            return False
        _, _, note = existing
        ledger_layout_before = self.canvas.ledger_layout_signature()
        continuation_id = note.continuation_id
        changed_staves: list[tuple[str, str]] = []
        for page in self.canvas.document.pages:
            for system in page.systems:
                for stave in system.staves:
                    original_count = len(stave.events)
                    stave.events[:] = [
                        event for event in stave.events
                        if not (
                            event is note
                            or (
                                continuation_id is not None
                                and isinstance(event, NoteEvent)
                                and event.continuation_id == continuation_id
                            )
                        )
                    ]
                    if len(stave.events) != original_count:
                        stave.touch()
                        changed_staves.append((system.id, stave.id))
        if not self.canvas.repaginate_if_ledger_layout_changed(ledger_layout_before):
            for system_id, stave_id in changed_staves:
                self.canvas.invalidate_system_render_cache(system_id, stave_id)
        self.canvas.commit_document_change()
        return True

    @staticmethod
    def _can_place(stave: Stave, candidate: NoteEvent, ignored_id: str | None = None) -> bool:
        candidate_end = candidate.time + candidate.duration
        comparison = Operator(SHORTEST_DURATION)
        for event in stave.events:
            if not isinstance(event, NoteEvent) or event.id == ignored_id:
                continue
            if event.hand != candidate.hand or event.pitch != candidate.pitch:
                continue
            if comparison.lt(candidate.time, event.time + event.duration) and comparison.lt(event.time, candidate_end):
                return False
        return True

    def _set_spanning_duration(self, edit: _NoteEdit, final_system: System, end_time: float) -> None:
        """Distribute a resized note across all systems it crosses."""
        if self.canvas is None:
            return
        systems = [system for page in self.canvas.document.pages for system in page.systems]
        first_index = systems.index(edit.system)
        final_index = systems.index(final_system)
        if final_index < first_index:
            return
        root_id = edit.note.continuation_id or edit.note.id
        stave_index = edit.system.staves.index(edit.stave)
        for system in systems:
            stave = system.staves[stave_index]
            stave.events[:] = [
                event for event in stave.events
                if not (isinstance(event, NoteEvent) and event is not edit.note and event.continuation_id == root_id)
            ]

        for index, system in enumerate(systems[first_index:final_index + 1], start=first_index):
            segment_start = edit.note.time if index == first_index else system.start_tick
            segment_end = min(end_time, system.end_tick)
            if segment_end <= segment_start:
                continue
            stave = system.staves[stave_index]
            if index == first_index:
                segment = edit.note
            else:
                segment = NoteEvent(
                    time=segment_start,
                    duration=segment_end - segment_start,
                    pitch=edit.note.pitch,
                    velocity=edit.note.velocity,
                    hand=edit.note.hand,
                    notehead=edit.note.notehead,
                    color=edit.note.color,
                    acc=edit.note.acc,
                )
                stave.events.append(segment)
            segment.time = segment_start
            segment.duration = segment_end - segment_start
            segment.continuation_id = root_id
            segment.continues_from_previous = index > first_index
            segment.continues_to_next = index < final_index
            stave.touch()

    @staticmethod
    def _matching_stave(source_system: System, source_stave: Stave, target_system: System) -> Stave:
        return target_system.staves[source_system.staves.index(source_stave)]
