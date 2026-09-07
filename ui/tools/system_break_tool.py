"""Direct insertion and removal of system breaks."""

from __future__ import annotations

from PySide6.QtCore import QPointF

from ui.tools.base_tool import BaseTool


class SystemBreakTool(BaseTool):
    """Split at an internal barline or merge systems at an existing edge."""

    TOOL_NAME = "system_break"

    def on_left_press(self, position_mm: QPointF) -> bool:
        if self.canvas is None:
            return False
        target = self.canvas.system_break_target_at(position_mm)
        if target is None:
            return False
        kind, system, value = target
        try:
            if kind == "split":
                self.canvas.document.split_system_at(self.canvas.current_page.id, system.id, value)
            else:
                self.canvas.document.remove_system_break(system.id, value)
        except ValueError:
            return False
        self.canvas.finish_system_break_edit()
        self.canvas.commit_document_change()
        return True