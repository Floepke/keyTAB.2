"""Direct editing of tempo markings."""

from __future__ import annotations

from PySide6.QtCore import QPointF

from keytab2_model import TempoEvent
from ui.dialogs.tempo_dialog import TempoDialog
from ui.tools.base_tool import BaseTool


class TempoTool(BaseTool):
    TOOL_NAME = "tempo"

    def __init__(self) -> None:
        super().__init__()
        self._resizing: TempoEvent | None = None
        self._minimum_duration = 1

    def on_left_press(self, position_mm: QPointF) -> bool:
        if self.canvas is None:
            return False
        existing = self.canvas.tempo_target_at(position_mm)
        if existing is not None:
            dialog = TempoDialog(existing, self.canvas)
            if dialog.exec() == dialog.DialogCode.Accepted:
                dialog.apply_to(existing)
                self.canvas.invalidate_render_cache()
                self.canvas.commit_document_change()
            return True
        target = self.canvas.stave_at(position_mm)
        if target is None:
            return False
        system, _, _ = target
        start_tick = int(self.canvas.snap_time(system, position_mm.y(), self.canvas.input_snap_ticks))
        segment_index, _ = self.canvas.document._time_signature_segment_containing(start_tick)
        segment = self.canvas.document.base_grid[segment_index]
        self._minimum_duration = segment.beat_duration(self.canvas.document.time_per_quarter)
        self._resizing = TempoEvent(start_tick=start_tick, duration_ticks=self._minimum_duration, tempo=60)
        self.canvas.document.timeline_events.append(self._resizing)
        self.canvas.invalidate_render_cache()
        return True

    def on_left_drag(self, position_mm: QPointF) -> bool:
        if self.canvas is None or self._resizing is None:
            return False
        target = self.canvas.stave_at(position_mm)
        if target is None:
            return True
        system, _, _ = target
        end_tick = int(self.canvas.snap_time(system, position_mm.y(), self.canvas.input_snap_ticks))
        self._resizing.duration_ticks = max(self._minimum_duration, end_tick - self._resizing.start_tick)
        self.canvas.invalidate_render_cache()
        return True

    def on_left_release(self, position_mm: QPointF) -> bool:
        if self._resizing is None or self.canvas is None:
            return False
        self.on_left_drag(position_mm)
        self._resizing = None
        self.canvas.commit_document_change()
        return True

    def on_right_click(self, position_mm: QPointF) -> bool:
        if self.canvas is None:
            return False
        tempo = self.canvas.tempo_target_at(position_mm)
        if tempo is None:
            return False
        earliest_tick = min(event.start_tick for event in self.canvas.document.timeline_events if isinstance(event, TempoEvent))
        if tempo.start_tick == earliest_tick:
            return False
        self.canvas.document.timeline_events.remove(tempo)
        self.canvas.invalidate_render_cache()
        self.canvas.commit_document_change()
        return True