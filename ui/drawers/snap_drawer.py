"""Alternating mouse-input snap bands."""

from __future__ import annotations

from keytab2_model.document import System
from ui.drawers.base import DrawerBase


class SnapDrawer(DrawerBase):
    BAND_COLOR = (0.88, 0.93, 0.97)

    def draw(self, system: System, left_mm: float, right_mm: float, snap_ticks: float, measure_starts: tuple[int, ...]) -> None:
        if snap_ticks <= 0:
            return
        tick_height = system.height_mm / (system.end_tick - system.start_tick)
        starts = [tick for tick in measure_starts if system.start_tick <= tick < system.end_tick]
        for measure_start, measure_end in zip(starts, starts[1:] + [system.end_tick], strict=True):
            tick = measure_start
            band_index = 0
            while tick < measure_end:
                next_tick = min(measure_end, tick + snap_ticks)
                if band_index % 2 == 0:
                    self.draw_rectangle(
                        left_mm,
                        system.top_mm + (tick - system.start_tick) * tick_height,
                        right_mm - left_mm,
                        (next_tick - tick) * tick_height,
                        fill_color=self.BAND_COLOR,
                        tags=("snap_band",),
                    )
                tick = next_tick
                band_index += 1