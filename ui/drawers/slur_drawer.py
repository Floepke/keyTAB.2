"""Cubic Bezier slur drawing."""

from __future__ import annotations

from ui.drawers.base import DrawerBase


class SlurDrawer(DrawerBase):
    """Draw slurs as tapered cubic Bezier strokes."""

    def draw(
        self,
        points_mm: tuple[tuple[float, float], tuple[float, float], tuple[float, float], tuple[float, float]],
        side_width_mm: float,
        middle_width_mm: float,
        segment_count: int = 24,
    ) -> None:
        start, first_control, second_control, end = points_mm

        def paint() -> None:
            self.context.set_source_rgb(*self.ink_color)
            self.context.set_line_cap(self.LINE_CAPS["round"])
            previous = start
            for index in range(1, max(1, segment_count) + 1):
                progress = index / max(1, segment_count)
                inverse = 1.0 - progress
                current = (
                    inverse ** 3 * start[0] + 3.0 * inverse ** 2 * progress * first_control[0] + 3.0 * inverse * progress ** 2 * second_control[0] + progress ** 3 * end[0],
                    inverse ** 3 * start[1] + 3.0 * inverse ** 2 * progress * first_control[1] + 3.0 * inverse * progress ** 2 * second_control[1] + progress ** 3 * end[1],
                )
                middle_weight = 1.0 - abs(2.0 * (progress - 0.5))
                self.context.set_line_width(side_width_mm + (middle_width_mm - side_width_mm) * middle_weight)
                self.context.move_to(*previous)
                self.context.line_to(*current)
                self.context.stroke()
                previous = current

        self._draw(("slur",), paint)