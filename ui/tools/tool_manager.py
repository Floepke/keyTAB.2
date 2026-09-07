"""Registry and lifecycle owner for direct-paper editing tools."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ui.tools.base_tool import BaseTool

if TYPE_CHECKING:
    from ui.paper_canvas import PaperCanvas


class ToolManager:
    """Select one registered tool without coupling the canvas to tool types."""

    def __init__(self, canvas: PaperCanvas) -> None:
        self._canvas = canvas
        self._tools: dict[str, BaseTool] = {}
        self._active_tool: BaseTool | None = None

    @property
    def active_tool(self) -> BaseTool | None:
        return self._active_tool

    def register(self, tool: BaseTool) -> None:
        if tool.TOOL_NAME in self._tools:
            raise ValueError(f"Tool already registered: {tool.TOOL_NAME}")
        tool.set_canvas(self._canvas)
        self._tools[tool.TOOL_NAME] = tool

    def activate(self, name: str) -> BaseTool:
        tool = self._tools.get(name)
        if tool is None:
            raise ValueError(f"Unknown tool: {name}")
        if self._active_tool is tool:
            return tool
        if self._active_tool is not None:
            self._active_tool.on_deactivate()
        self._active_tool = tool
        tool.on_activate()
        return tool
