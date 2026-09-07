"""Base protocol for direct-paper editing tools."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from PySide6.QtCore import QPointF
    from ui.paper_canvas import PaperCanvas


class BaseTool:
    """A focused editor mode that receives document-space pointer input."""

    TOOL_NAME = "base"

    def __init__(self) -> None:
        self.canvas: PaperCanvas | None = None
        self.active = False

    def set_canvas(self, canvas: PaperCanvas) -> None:
        self.canvas = canvas

    def on_activate(self) -> None:
        self.active = True

    def on_deactivate(self) -> None:
        self.active = False

    def on_left_press(self, position_mm: QPointF) -> bool:
        return False

    def on_left_drag(self, position_mm: QPointF) -> bool:
        return False

    def on_left_release(self, position_mm: QPointF) -> bool:
        return False

    def on_right_click(self, position_mm: QPointF) -> bool:
        return False
