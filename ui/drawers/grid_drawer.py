"""Measure boundaries and labels for a vertical Klavarskribo system."""

from __future__ import annotations

import cairocffi as cairo

from keytab2_model.document import System
from keytab2_model.layout import Layout
from ui.drawers.base import DrawerBase
from ui.drawers.metrics import SystemMetrics
from ui.render_cache import MeasureCollisionIndex


class GridDrawer(DrawerBase):
    def draw(self, system: System, layout: Layout, stave_scale: float, left_mm: float, right_mm: float, measure_starts: tuple[int, ...], group_starts: tuple[int, ...], metrics: SystemMetrics, collision_index: MeasureCollisionIndex | None = None, is_final_system: bool = False, show_measure_numbers: bool = True) -> None:
        tick_height = system.height_mm / (system.end_tick - system.start_tick)
        measure_font = layout.measure_numbering_font
        measure_size_mm = layout.engraving_pt_to_mm(measure_font.size_pt, stave_scale)
        visible_measure_starts = [tick for tick in measure_starts if system.start_tick <= tick < system.end_tick]

        def draw_line_with_gaps(y_mm: float, width_mm: float, tags: tuple[str, ...], dash_pattern_mm: list[float] | None = None) -> None:
            visual_gap_mm = layout.engraving_mm(2.0, stave_scale)
            intervals = collision_index.horizontal_occlusion_intervals(y_mm, visual_gap_mm + width_mm * 0.5) if collision_index else ()
            cursor_mm = left_mm
            for gap_start_mm, gap_end_mm in intervals:
                if gap_start_mm > cursor_mm:
                    self.draw_line(cursor_mm, y_mm, min(gap_start_mm, right_mm), y_mm, width_mm, dash_pattern_mm=dash_pattern_mm, tags=tags)
                cursor_mm = max(cursor_mm, gap_end_mm)
            if cursor_mm < right_mm:
                self.draw_line(cursor_mm, y_mm, right_mm, y_mm, width_mm, dash_pattern_mm=dash_pattern_mm, tags=tags)

        for measure_offset, tick in enumerate(visible_measure_starts):
            y_mm = system.top_mm + (tick - system.start_tick) * tick_height
            measure_text = str(system.first_measure_number + measure_offset)
            _, y_bearing_mm, _, text_height_mm = self.text_extents(measure_text, measure_size_mm, measure_font)
            baseline_mm = y_mm - (y_bearing_mm + text_height_mm * 0.5) - measure_font.y_offset
            draw_line_with_gaps(y_mm, metrics.barline_width_mm, ("grid_barline",))
            next_tick = visible_measure_starts[measure_offset + 1] if measure_offset + 1 < len(visible_measure_starts) else system.end_tick
            note_right_mm = collision_index.right_extent_mm(tick, next_tick, right_mm) if collision_index else right_mm
            if show_measure_numbers and layout.measure_numbers_visible:
                self.draw_text(
                    measure_text,
                    max(right_mm, note_right_mm) + metrics.measure_number_offset_mm,
                    baseline_mm,
                    measure_size_mm,
                    measure_font,
                    tags=("measure_number",),
                )
        for tick in group_starts:
            if system.start_tick < tick < system.end_tick:
                y_mm = system.top_mm + (tick - system.start_tick) * tick_height
                draw_line_with_gaps(
                    y_mm,
                    layout.engraving_mm(layout.grid_gridline_thickness_mm, stave_scale),
                    ("grid_line",),
                    [layout.engraving_mm(value, stave_scale) for value in layout.grid_gridline_dash_pattern_mm],
                )

        closing_y_mm = system.top_mm + system.height_mm
        if is_final_system:
            self.draw_line(
                left_mm,
                closing_y_mm,
                right_mm,
                closing_y_mm,
                layout.engraving_mm(layout.grid_barline_thickness_mm * 2.0, stave_scale),
                tags=("grid_barline",),
            )
        else:
            self.draw_line(
                left_mm,
                closing_y_mm,
                right_mm,
                closing_y_mm,
                metrics.barline_width_mm,
                tags=("grid_barline",),
            )