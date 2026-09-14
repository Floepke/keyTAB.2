"""Create and reshape arpeggios attached to chord note UUIDs."""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QPointF

from keytab2_model import ArpeggioEvent, NoteEvent
from ui.drawers.stave_drawer import StaveDrawer
from ui.tools.base_tool import BaseTool
from utils.CONSTANT import SHORTEST_DURATION
from utils.operator import Operator


@dataclass
class _ArpeggioEdit:
    system: object
    stave: object
    arpeggio: ArpeggioEvent
    handle: str


class ArpeggioTool(BaseTool):
    TOOL_NAME = "arpeggio"
    HANDLE_HIT_RADIUS_MM = 4.0

    def __init__(self) -> None:
        super().__init__()
        self._edit: _ArpeggioEdit | None = None

    def on_left_press(self, position_mm: QPointF) -> bool:
        if self.canvas is None:
            return False
        self.canvas.update_mouse_cursor(position_mm)
        hit = self._handle_at(position_mm)
        if hit is not None:
            self._edit = _ArpeggioEdit(*hit)
            return True
        note_hit = self.canvas.note_at(position_mm)
        if note_hit is not None:
            system, stave, note, _, _ = note_hit
        else:
            cursor_note = self.canvas.note_at_mouse_cursor()
            if cursor_note is None:
                return False
            system, stave, note = cursor_note
        timing_comparison = Operator(SHORTEST_DURATION)
        members = sorted(
            (
                event for event in stave.events
                if isinstance(event, NoteEvent) and timing_comparison.eq(event.time, note.time) and event.hand == note.hand
            ),
            key=lambda event: event.pitch,
        )
        if len(members) < 2:
            return False
        arpeggio = next(
            (
                event for event in stave.events
                if isinstance(event, ArpeggioEvent) and event.note_ids == [member.id for member in members]
            ),
            None,
        )
        if arpeggio is None:
            arpeggio = ArpeggioEvent(
                start_tick=note.time,
                rtime1_ticks=0,
                rtime2_ticks=int(self.canvas.input_snap_ticks),
                note_ids=[member.id for member in members],
                note_pitches=[member.pitch for member in members],
                hand=note.hand,
            )
            stave.events.append(arpeggio)
            stave.touch()
            system.touch()
            self.canvas.invalidate_system_render_cache(system.id, stave.id)
            self.canvas.commit_document_change()
        return True

    def on_left_drag(self, position_mm: QPointF) -> bool:
        if self.canvas is None or self._edit is None:
            return False
        edit = self._edit
        tick = self.canvas.snap_time(edit.system, position_mm.y(), self.canvas.input_snap_ticks)
        offset = int(tick - edit.arpeggio.start_tick)
        if edit.handle == "low":
            edit.arpeggio.rtime1_ticks = (
                0
                if offset and edit.arpeggio.rtime2_ticks and offset * edit.arpeggio.rtime2_ticks > 0
                else offset
            )
        else:
            edit.arpeggio.rtime2_ticks = (
                0
                if offset and edit.arpeggio.rtime1_ticks and offset * edit.arpeggio.rtime1_ticks > 0
                else offset
            )
        edit.stave.touch()
        edit.system.touch()
        self.canvas.invalidate_system_render_cache(edit.system.id, edit.stave.id)
        return True

    def on_left_release(self, position_mm: QPointF) -> bool:
        del position_mm
        if self.canvas is None or self._edit is None:
            return False
        edit = self._edit
        self._edit = None
        self.canvas.commit_document_change()
        return True

    def on_right_click(self, position_mm: QPointF) -> bool:
        if self.canvas is None:
            return False
        hit = self._handle_at(position_mm)
        if hit is None:
            return False
        system, stave, arpeggio, _ = hit
        stave.events.remove(arpeggio)
        stave.touch()
        system.touch()
        self.canvas.invalidate_system_render_cache(system.id, stave.id)
        self.canvas.commit_document_change()
        return True

    def visible_handles(self):
        if self.canvas is None:
            return ()
        for page in self.canvas.document.pages:
            for system in page.systems:
                for stave in system.staves:
                    for arpeggio in (event for event in stave.events if isinstance(event, ArpeggioEvent)):
                        points = self._handle_points(system, stave, arpeggio)
                        if points is not None:
                            yield arpeggio, points

    def _handle_at(self, position_mm: QPointF):
        if self.canvas is None:
            return None
        candidates = []
        for arpeggio, ((low_x, low_y), (high_x, high_y)) in self.visible_handles():
            for handle, (x_mm, y_mm) in (("low", (low_x, low_y)), ("high", (high_x, high_y))):
                distance_squared = (x_mm - position_mm.x()) ** 2 + (y_mm - position_mm.y()) ** 2
                if distance_squared <= self.HANDLE_HIT_RADIUS_MM ** 2:
                    for page in self.canvas.document.pages:
                        for system in page.systems:
                            for stave in system.staves:
                                if arpeggio in stave.events:
                                    candidates.append((distance_squared, system, stave, arpeggio, handle))
        if not candidates:
            return None
        _, system, stave, arpeggio, handle = min(candidates, key=lambda candidate: candidate[0])
        return system, stave, arpeggio, handle

    def _handle_points(self, system, stave, arpeggio: ArpeggioEvent):
        if self.canvas is None or not (system.start_tick <= arpeggio.start_tick < system.end_tick):
            return None
        members = self.canvas.document.arpeggio_members(stave, arpeggio)
        if len(members) < 2:
            return None
        left_mm = self.canvas.stave_left_mm(system, stave)
        semitone_mm = self.canvas.document.layout.engraving_mm(2.0, stave.scale)
        low = members[0]
        high = members[-1]
        return (
            (StaveDrawer.pitch_to_x_mm(low.pitch, stave.pitch_range[0], left_mm, semitone_mm), self.canvas._time_to_y_mm(system, arpeggio.start_tick + arpeggio.rtime1_ticks)),
            (StaveDrawer.pitch_to_x_mm(high.pitch, stave.pitch_range[0], left_mm, semitone_mm), self.canvas._time_to_y_mm(system, arpeggio.start_tick + arpeggio.rtime2_ticks)),
        )
