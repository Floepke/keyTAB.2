"""Barline connectors joining adjacent staves in a vertical score system."""

from __future__ import annotations

from keytab2_model.document import System
from ui.drawers.base import DrawerBase


class StaveConnectorDrawer(DrawerBase):
    """Bridge the horizontal gaps between stave barlines at each measure edge."""

    def draw(
        self,
        system: System,
        stave_bounds: list[tuple[float, float]],
        measure_starts: tuple[int, ...],
        line_width_mm: float,
        closing_line_width_mm: float,
    ) -> None:
        if len(stave_bounds) < 2:
            return
        tick_height = system.height_mm / (system.end_tick - system.start_tick)
        visible_starts = [tick for tick in measure_starts if system.start_tick <= tick < system.end_tick]
        for tick in (*visible_starts, system.end_tick):
            y_mm = system.top_mm + (tick - system.start_tick) * tick_height
            width_mm = closing_line_width_mm if tick == system.end_tick else line_width_mm
            for left_bounds, right_bounds in zip(stave_bounds, stave_bounds[1:]):
                self.draw_line(left_bounds[1], y_mm, right_bounds[0], y_mm, width_mm, tags=("stave_connector",))