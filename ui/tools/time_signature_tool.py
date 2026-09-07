"""Direct editing of time-signature segments and their grid lines."""

from __future__ import annotations

from PySide6.QtCore import QPointF

from ui.dialogs.time_signature_dialog import TimeSignatureDialog
from ui.tools.base_tool import BaseTool


class TimeSignatureTool(BaseTool):
    TOOL_NAME = "time_signature"

    def on_left_press(self, position_mm: QPointF) -> bool:
        if self.canvas is None:
            return False
        target = self.canvas.time_signature_target_at(position_mm)
        if target is None:
            return False
        kind, time = target
        if kind == "grid":
            self.canvas.document.set_time_signature_grid_line(time, True)
            self.canvas.invalidate_render_cache()
            self.canvas.commit_document_change()
            return True
        index, _ = self.canvas.document.time_signature_segment_at(time)
        segment = self.canvas.document.base_grid[min(index, len(self.canvas.document.base_grid) - 1)]
        dialog = TimeSignatureDialog(segment, self.canvas)
        if dialog.exec() != dialog.DialogCode.Accepted:
            return True
        try:
            numerator, denominator, indicator_enabled = dialog.value()
            self.canvas.document.set_time_signature(time, numerator, denominator, indicator_enabled)
        except ValueError:
            return True
        self.canvas.finish_time_signature_edit()
        self.canvas.commit_document_change()
        return True

    def on_right_click(self, position_mm: QPointF) -> bool:
        if self.canvas is None:
            return False
        target = self.canvas.time_signature_target_at(position_mm)
        if target is None:
            return False
        if target[0] == "barline":
            try:
                self.canvas.document.remove_time_signature(target[1])
            except ValueError:
                return False
            self.canvas.finish_time_signature_edit()
            self.canvas.commit_document_change()
            return True
        try:
            self.canvas.document.set_time_signature_grid_line(target[1], False)
        except ValueError:
            return False
        self.canvas.invalidate_render_cache()
        self.canvas.commit_document_change()
        return True