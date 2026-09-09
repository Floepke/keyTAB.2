"""Cached beam drawing."""

from __future__ import annotations

import math

from ui.drawers.base import DrawerBase
from ui.render_cache import BeamGeometry


class BeamDrawer(DrawerBase):
    def draw(self, beam: BeamGeometry, stem_thickness_mm: float, corner_radius_mm: float) -> None:
        points_mm = self._rounded_polygon(beam.polygon_mm, corner_radius_mm)
        self.draw_polygon(points_mm, width_mm=0.0, fill_color=self.ink_color, tags=("beam",))
        for segment in beam.segments_mm:
            self.draw_line(*segment, width_mm=stem_thickness_mm, tags=("beam_connector",))

    @staticmethod
    def _rounded_polygon(points_mm: tuple[tuple[float, float], ...], radius_mm: float, steps: int = 16) -> tuple[tuple[float, float], ...]:
        """Return a closed polygon with circular corner arcs, clamped to its edges."""
        if len(points_mm) < 3 or radius_mm <= 1e-6:
            return points_mm

        area = sum(
            x1 * y2 - x2 * y1
            for (x1, y1), (x2, y2) in zip(points_mm, (*points_mm[1:], points_mm[0]), strict=True)
        )
        counter_clockwise = area >= 0.0
        rounded: list[tuple[float, float]] = []
        for index, point in enumerate(points_mm):
            previous = points_mm[index - 1]
            following = points_mm[(index + 1) % len(points_mm)]
            previous_vector = (previous[0] - point[0], previous[1] - point[1])
            following_vector = (following[0] - point[0], following[1] - point[1])
            previous_length = math.hypot(*previous_vector)
            following_length = math.hypot(*following_vector)
            if previous_length <= 1e-9 or following_length <= 1e-9:
                rounded.append(point)
                continue

            previous_unit = (previous_vector[0] / previous_length, previous_vector[1] / previous_length)
            following_unit = (following_vector[0] / following_length, following_vector[1] / following_length)
            angle = math.acos(max(-1.0, min(1.0, previous_unit[0] * following_unit[0] + previous_unit[1] * following_unit[1])))
            tangent_half_angle = math.tan(angle * 0.5)
            if angle <= 1e-4 or abs(math.pi - angle) <= 1e-4 or abs(tangent_half_angle) <= 1e-9:
                rounded.append(point)
                continue

            cut = min(radius_mm / tangent_half_angle, previous_length * 0.49, following_length * 0.49)
            first_arc_point = (point[0] + previous_unit[0] * cut, point[1] + previous_unit[1] * cut)
            second_arc_point = (point[0] + following_unit[0] * cut, point[1] + following_unit[1] * cut)
            bisector = (previous_unit[0] + following_unit[0], previous_unit[1] + following_unit[1])
            bisector_length = math.hypot(*bisector)
            sine_half_angle = math.sin(angle * 0.5)
            if bisector_length <= 1e-9 or abs(sine_half_angle) <= 1e-9:
                rounded.extend((first_arc_point, second_arc_point))
                continue

            center = (
                point[0] + bisector[0] / bisector_length * radius_mm / sine_half_angle,
                point[1] + bisector[1] / bisector_length * radius_mm / sine_half_angle,
            )
            start_angle = math.atan2(first_arc_point[1] - center[1], first_arc_point[0] - center[0])
            end_angle = math.atan2(second_arc_point[1] - center[1], second_arc_point[0] - center[0])
            arc_angle = (end_angle - start_angle) % (2.0 * math.pi) if counter_clockwise else -((start_angle - end_angle) % (2.0 * math.pi))
            rounded.append(first_arc_point)
            for step in range(1, max(1, steps)):
                angle_at_step = start_angle + arc_angle * step / max(1, steps)
                rounded.append((center[0] + radius_mm * math.cos(angle_at_step), center[1] + radius_mm * math.sin(angle_at_step)))
            rounded.append(second_arc_point)
        return tuple(rounded)