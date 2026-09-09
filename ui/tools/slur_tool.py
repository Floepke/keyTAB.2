"""Direct four-handle editing for cubic slurs."""

from __future__ import annotations

import math
from copy import deepcopy
from dataclasses import dataclass

from PySide6.QtCore import QPointF

from keytab2_model import SlurEvent
from ui.drawers.stave_drawer import StaveDrawer
from ui.tools.base_tool import BaseTool


@dataclass
class _SlurEdit:
    system: object
    stave: object
    slur: SlurEvent
    handle: int
    preview: SlurEvent | None = None


class SlurTool(BaseTool):
    """Create, reshape, and delete slurs using MIDI-60 relative handles."""

    TOOL_NAME = "slur"
    HANDLE_HIT_RADIUS_MM = 4.0
    ENDPOINT_CONTROL_OFFSET = 6

    def __init__(self, hand: str = "left") -> None:
        super().__init__()
        self.hand = hand
        self._edit: _SlurEdit | None = None

    def set_hand(self, hand: str) -> None:
        if hand not in ("left", "right"):
            raise ValueError("Slur hand must be 'left' or 'right'")
        self.hand = hand

    def on_left_press(self, position_mm: QPointF) -> bool:
        if self.canvas is None:
            return False
        hit = self._handle_at(position_mm)
        if hit is not None:
            system, stave, slur, handle = hit
            self.canvas.select_slur(slur)
            self._edit = _SlurEdit(system, stave, slur, handle)
            return True
        target = self.canvas.stave_at(position_mm, allow_outside_range=True)
        if target is None:
            return False
        system, stave, left_mm = target
        pitch, tick = self._handle_values(position_mm, system, stave, left_mm)
        slur = SlurEvent(
            x1_rpitch=pitch - 60,
            y1_tick=tick,
            x2_rpitch=pitch - 60,
            y2_tick=tick,
            x3_rpitch=pitch - 60,
            y3_tick=tick,
            x4_rpitch=pitch - 60,
            y4_tick=tick,
        )
        self._apply_handle(slur, 1, pitch, tick)
        self._apply_handle(slur, 4, pitch, tick)
        self._constrain_to_page(slur, system, stave, left_mm)
        stave.events.append(slur)
        stave.touch()
        self.canvas.invalidate_system_render_cache(system.id, stave.id)
        self.canvas.select_slur(slur)
        self._edit = _SlurEdit(system, stave, slur, 4)
        return True

    def on_left_drag(self, position_mm: QPointF) -> bool:
        if self.canvas is None or self._edit is None:
            return False
        edit = self._edit
        left_mm = self.canvas.stave_left_mm(edit.system, edit.stave)
        pitch, tick = self._handle_values(position_mm, edit.system, edit.stave, left_mm)
        preview = deepcopy(edit.slur)
        self._apply_handle(preview, edit.handle, pitch, tick)
        self._constrain_to_page(preview, edit.system, edit.stave, left_mm)
        if edit.preview == preview:
            return True
        edit.preview = preview
        self.canvas.update()
        return True

    def on_left_release(self, position_mm: QPointF) -> bool:
        if self._edit is None or self.canvas is None:
            return False
        edit = self._edit
        self._edit = None
        if edit.preview is not None:
            for attribute in (
                "x1_rpitch", "y1_tick", "x2_rpitch", "y2_tick",
                "x3_rpitch", "y3_tick", "x4_rpitch", "y4_tick",
            ):
                setattr(edit.slur, attribute, getattr(edit.preview, attribute))
            edit.stave.touch()
            self.canvas.invalidate_system_render_cache(edit.system.id, edit.stave.id)
        self.canvas.commit_document_change()
        return True

    def on_right_click(self, position_mm: QPointF) -> bool:
        if self.canvas is None:
            return False
        hit = self._handle_at(position_mm)
        if hit is None:
            return False
        system, stave, slur, _ = hit
        stave.events.remove(slur)
        stave.touch()
        self.canvas.invalidate_system_render_cache(system.id, stave.id)
        self.canvas.commit_document_change()
        return True

    def visible_handles(self):
        """Return every editable handle in document millimetres."""
        if self.canvas is None:
            return ()
        handles = []
        for system in self.canvas.current_page.systems:
            for stave in system.staves:
                left_mm = self.canvas.stave_left_mm(system, stave)
                for slur in (event for event in stave.events if isinstance(event, SlurEvent)):
                    rendered_slur = self._edit.preview if self._edit is not None and slur is self._edit.slur and self._edit.preview is not None else slur
                    handles.append((self._points_mm(system, stave, left_mm, rendered_slur),))
        return tuple(handles)

    @property
    def drag_preview_points(self):
        """Return the active overlay-only cubic Bezier control points."""
        if self.canvas is None or self._edit is None or self._edit.preview is None:
            return None
        left_mm = self.canvas.stave_left_mm(self._edit.system, self._edit.stave)
        return self._points_mm(self._edit.system, self._edit.stave, left_mm, self._edit.preview)

    def _handle_at(self, position_mm: QPointF):
        if self.canvas is None:
            return None
        page = self.canvas.current_page
        for system in page.systems:
            for stave in system.staves:
                left_mm = self.canvas.stave_left_mm(system, stave)
                for slur in (event for event in stave.events if isinstance(event, SlurEvent)):
                    for handle, point in enumerate(self._points_mm(system, stave, left_mm, slur), start=1):
                        if math.hypot(point[0] - position_mm.x(), point[1] - position_mm.y()) <= self.HANDLE_HIT_RADIUS_MM:
                            return system, stave, slur, handle
        return None

    def _points_mm(self, system, stave, left_mm: float, slur: SlurEvent):
        semitone_mm = self.canvas.document.layout.engraving_mm(2.0, stave.scale)
        return tuple(
            (
                StaveDrawer.pitch_to_x_mm(60 + rpitch, stave.pitch_range[0], left_mm, semitone_mm),
                self.canvas._time_to_y_mm(system, tick),
            )
            for rpitch, tick in (
                (slur.x1_rpitch, slur.y1_tick),
                (slur.x2_rpitch, slur.y2_tick),
                (slur.x3_rpitch, slur.y3_tick),
                (slur.x4_rpitch, slur.y4_tick),
            )
        )

    def _apply_handle(self, slur: SlurEvent, handle: int, pitch: int, tick: int) -> None:
        rpitch = pitch - 60
        offset = self.ENDPOINT_CONTROL_OFFSET if self.hand == "right" else -self.ENDPOINT_CONTROL_OFFSET
        if handle == 1:
            slur.x1_rpitch, slur.y1_tick = rpitch, tick
            slur.x2_rpitch, slur.y2_tick = rpitch + offset, tick
        elif handle == 2:
            slur.x2_rpitch, slur.y2_tick = rpitch, tick
        elif handle == 3:
            slur.x3_rpitch, slur.y3_tick = rpitch, tick
        else:
            slur.x4_rpitch, slur.y4_tick = rpitch, tick
            slur.x3_rpitch, slur.y3_tick = rpitch + offset, tick

    def _handle_values(self, position_mm: QPointF, system, stave, left_mm: float) -> tuple[int, int]:
        """Convert a page-clamped pointer position to unrestricted handle coordinates."""
        page = self.canvas.current_page
        x_mm = min(page.width_mm, max(0.0, position_mm.x()))
        y_mm = min(page.height_mm, max(0.0, position_mm.y()))
        semitone_mm = self.canvas.document.layout.engraving_mm(2.0, stave.scale)
        centre_x_mm = StaveDrawer.pitch_to_x_mm(60, stave.pitch_range[0], left_mm, semitone_mm)
        estimate = 60 + round((x_mm - centre_x_mm) / semitone_mm)
        pitch = min(
            range(estimate - 16, estimate + 17),
            key=lambda candidate: abs(StaveDrawer.pitch_to_x_mm(candidate, stave.pitch_range[0], left_mm, semitone_mm) - x_mm),
        )
        raw_tick = system.start_tick + (y_mm - system.top_mm) * (system.end_tick - system.start_tick) / system.height_mm
        return pitch, int(round(raw_tick / self.canvas.input_snap_ticks) * self.canvas.input_snap_ticks)

    def _constrain_to_page(self, slur: SlurEvent, system, stave, left_mm: float) -> None:
        """Clamp all four visual handles to the current page after linked edits."""
        page = self.canvas.current_page
        semitone_mm = self.canvas.document.layout.engraving_mm(2.0, stave.scale)
        min_tick = system.start_tick + (0.0 - system.top_mm) * (system.end_tick - system.start_tick) / system.height_mm
        max_tick = system.start_tick + (page.height_mm - system.top_mm) * (system.end_tick - system.start_tick) / system.height_mm
        for pitch_attribute, tick_attribute in (
            ("x1_rpitch", "y1_tick"), ("x2_rpitch", "y2_tick"),
            ("x3_rpitch", "y3_tick"), ("x4_rpitch", "y4_tick"),
        ):
            rpitch = getattr(slur, pitch_attribute)
            while StaveDrawer.pitch_to_x_mm(60 + rpitch, stave.pitch_range[0], left_mm, semitone_mm) < 0.0:
                rpitch += 1
            while StaveDrawer.pitch_to_x_mm(60 + rpitch, stave.pitch_range[0], left_mm, semitone_mm) > page.width_mm:
                rpitch -= 1
            setattr(slur, pitch_attribute, rpitch)
            setattr(slur, tick_attribute, int(min(max_tick, max(min_tick, getattr(slur, tick_attribute)))))