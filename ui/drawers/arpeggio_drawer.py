"""Arpeggio stem drawing for the direct paper editor."""

from __future__ import annotations

import math

from ui.drawers.base import DrawerBase


class ArpeggioDrawer(DrawerBase):
    def draw(
        self,
        anchor_point_mm: tuple[float, float],
        opposite_point_mm: tuple[float, float],
        width_mm: float,
        stem_length_mm: float,
    ) -> None:
        anchor_x_mm, anchor_y_mm = anchor_point_mm
        opposite_x_mm, opposite_y_mm = opposite_point_mm
        direction_x_mm = opposite_x_mm - anchor_x_mm
        direction_y_mm = opposite_y_mm - anchor_y_mm
        length_mm = math.hypot(direction_x_mm, direction_y_mm)
        if length_mm <= 1e-9:
            return
        tip_x_mm = opposite_x_mm + direction_x_mm * stem_length_mm / length_mm
        tip_y_mm = opposite_y_mm + direction_y_mm * stem_length_mm / length_mm
        self.draw_line(
            anchor_x_mm,
            anchor_y_mm,
            tip_x_mm,
            tip_y_mm,
            width_mm=width_mm,
            tags=("arpeggio",),
        )
