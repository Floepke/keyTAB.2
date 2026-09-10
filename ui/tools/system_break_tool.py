"""Direct insertion and removal of system breaks."""

from __future__ import annotations

from PySide6.QtCore import QPointF
from PySide6.QtCore import Qt

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

    def on_right_click(self, position_mm: QPointF) -> bool:
        if self.canvas is None:
            return False
        target = self.canvas.system_break_target_at(position_mm)
        if target is None:
            return False
        kind, system, boundary = target
        if kind != "remove":
            return False
        try:
            self.canvas.document.remove_system_break(system.id, boundary)
        except ValueError:
            return False
        self.canvas.finish_system_break_edit()
        self.canvas.commit_document_change()
        return True

    def on_key_press(self, event) -> bool:
        if self.canvas is None or event.modifiers() != Qt.KeyboardModifier.NoModifier:
            return False
        target = self.canvas.hovered_system_break_target()
        if target is None:
            return False
        kind, system, value = target
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            try:
                if kind == "split":
                    system = self.canvas.document.split_system_at(
                        self.canvas.current_page.id,
                        system.id,
                        value,
                    )
                elif value == "bottom":
                    system = self.canvas.following_system(system)
                    if system is None:
                        return False
                self.canvas.document.set_forced_page_break_before(
                    system.id,
                    not system.force_page_break_before,
                )
            except ValueError:
                return False
        else:
            return False
        self.canvas.finish_system_break_edit()
        self.canvas.show_system_page(system)
        self.canvas.commit_document_change()
        return True