"""Classical and Klavarskribo time-signature indicators."""

from __future__ import annotations

from keytab2_model.base_grid import BaseGrid
from keytab2_model.document import System
from keytab2_model.layout import Layout
from ui.drawers.base import DrawerBase
from ui.render_cache import MeasureCollisionIndex


class TimeSignatureDrawer(DrawerBase):
    """Draw keyTAB1-compatible meter indicators beside the first stave."""

    BLACK_PITCH_CLASSES = {1, 3, 6, 8, 10}

    def draw(self, system: System, layout: Layout, stave_scale: float, stave_left_mm: float, base_grid: list[BaseGrid], time_per_quarter: int, collision_index: MeasureCollisionIndex | None = None) -> None:
        if not layout.time_signature_visible:
            return
        lane_width_mm = layout.engraving_mm(layout.time_signature_indicator_lane_width_mm, stave_scale)
        if lane_width_mm <= 0.0:
            return
        scale = layout.engraving_scale(stave_scale)
        half_span_mm = 3.0 * scale
        guide_width_mm = layout.engraving_mm(layout.time_signature_indicator_guide_thickness_mm, stave_scale)
        divider_width_mm = layout.engraving_mm(layout.time_signature_indicator_divide_guide_thickness_mm, stave_scale)
        cursor_tick = 0
        for segment in base_grid:
            if segment.indicator_enabled and system.start_tick <= cursor_tick < system.end_tick:
                measure_end_tick = min(system.end_tick, cursor_tick + segment.measure_duration(time_per_quarter))
                notation_left_mm = collision_index.left_extent_mm(cursor_tick, measure_end_tick, stave_left_mm) if collision_index else stave_left_mm
                lane_right_mm = min(stave_left_mm, notation_left_mm) - 1.5 * scale
                column_width_mm = lane_width_mm / 3.0
                lane_left_mm = lane_right_mm - lane_width_mm
                x_left_mm = lane_left_mm + column_width_mm * 0.5
                x_middle_mm = lane_left_mm + column_width_mm * 1.5
                x_right_mm = lane_left_mm + column_width_mm * 2.5
                y_mm = system.top_mm + (cursor_tick - system.start_tick) * system.height_mm / (system.end_tick - system.start_tick)
                if layout.time_signature_indicator_type in ("classical", "classical & klavarskribo"):
                    self._draw_classical(
                        segment.numerator,
                        segment.denominator,
                        y_mm,
                        x_right_mm,
                        half_span_mm,
                        divider_width_mm,
                        layout,
                        stave_scale,
                    )
                if layout.time_signature_indicator_type in ("klavarskribo", "classical & klavarskribo"):
                    self._draw_klavarskribo(
                        segment,
                        y_mm,
                        x_left_mm,
                        x_middle_mm,
                        x_right_mm,
                        half_span_mm,
                        guide_width_mm,
                        layout,
                        stave_scale,
                        system.height_mm / (system.end_tick - system.start_tick),
                        time_per_quarter,
                    )
            cursor_tick += segment.measure_amount * segment.measure_duration(time_per_quarter)

    def _draw_classical(self, numerator: int, denominator: int, y_mm: float, x_mm: float, half_span_mm: float, divider_width_mm: float, layout: Layout, stave_scale: float) -> None:
        font = layout.time_signature_indicator_classic_font
        size_mm = layout.engraving_pt_to_mm(font.size_pt, stave_scale)
        gap_mm = 1.5 * layout.engraving_scale(stave_scale)
        numerator_baseline_mm = self._text_baseline_above_divider(
            str(numerator),
            x_mm,
            y_mm - divider_width_mm * 0.5 - gap_mm,
            size_mm,
            font,
        )
        denominator_baseline_mm = self._text_baseline_below_divider(
            str(denominator),
            x_mm,
            y_mm + divider_width_mm * 0.5 + gap_mm,
            size_mm,
            font,
        )
        self.draw_text(str(numerator), numerator_baseline_mm[0], numerator_baseline_mm[1], size_mm, font, tags=("time_signature",))
        self.draw_line(x_mm - half_span_mm, y_mm, x_mm + half_span_mm, y_mm, divider_width_mm, tags=("time_signature",))
        self.draw_text(str(denominator), denominator_baseline_mm[0], denominator_baseline_mm[1], size_mm, font, tags=("time_signature",))

    def _draw_klavarskribo(self, segment: BaseGrid, y_mm: float, x_left_mm: float, x_middle_mm: float, x_right_mm: float, half_span_mm: float, guide_width_mm: float, layout: Layout, stave_scale: float, mm_per_tick: float, time_per_quarter: int) -> None:
        numerator = segment.numerator
        beat_ticks = segment.beat_duration(time_per_quarter)
        font = layout.time_signature_indicator_klavarskribo_font
        size_mm = layout.engraving_pt_to_mm(font.size_pt, stave_scale)
        measure_height_mm = numerator * beat_ticks * mm_per_tick
        beat_height_mm = measure_height_mm / numerator
        reset_beats = {beat for beat in segment.beat_grouping if 1 <= beat <= numerator}
        full_group_mode = len(reset_beats) == numerator
        middle_values: list[int] = []
        group_values: list[tuple[int, int]] = []
        middle_value = 1
        group_value = 1
        for beat in range(1, numerator + 1):
            reset = beat == 1 or (not full_group_mode and beat in reset_beats)
            if reset:
                middle_value = 1
                if beat > 1:
                    group_value += 1
                group_values.append((beat, group_value))
            else:
                middle_value += 1
            middle_values.append(middle_value)
        for beat in range(numerator + 1):
            guide_y_mm = y_mm + beat * beat_height_mm
            self.draw_line(x_right_mm - half_span_mm, guide_y_mm, x_right_mm + half_span_mm, guide_y_mm, guide_width_mm, tags=("time_signature",))
            if beat < numerator:
                baseline = self._centered_text_baseline(str(middle_values[beat]), x_middle_mm, guide_y_mm, size_mm, font)
                self.draw_text(str(middle_values[beat]), baseline[0], baseline[1], size_mm, font, tags=("time_signature",))
        baseline = self._centered_text_baseline("1", x_middle_mm, y_mm + measure_height_mm, size_mm, font)
        self.draw_text("1", baseline[0], baseline[1], size_mm, font, tags=("time_signature",))
        for beat, value in group_values:
            baseline = self._centered_text_baseline(str(value), x_left_mm, y_mm + (beat - 1) * beat_height_mm, size_mm, font)
            self.draw_text(str(value), baseline[0], baseline[1], size_mm, font, tags=("time_signature",))

    def _centered_text_baseline(self, text: str, x_mm: float, center_y_mm: float, size_mm: float, font) -> tuple[float, float]:
        x_bearing_mm, y_bearing_mm, width_mm, height_mm = self.text_extents(text, size_mm, font)
        return x_mm - x_bearing_mm - width_mm * 0.5, center_y_mm - y_bearing_mm - height_mm * 0.5

    def _text_baseline_above_divider(self, text: str, x_mm: float, bottom_y_mm: float, size_mm: float, font) -> tuple[float, float]:
        x_bearing_mm, y_bearing_mm, width_mm, height_mm = self.text_extents(text, size_mm, font)
        return x_mm - x_bearing_mm - width_mm * 0.5, bottom_y_mm - y_bearing_mm - height_mm

    def _text_baseline_below_divider(self, text: str, x_mm: float, top_y_mm: float, size_mm: float, font) -> tuple[float, float]:
        x_bearing_mm, y_bearing_mm, width_mm, _ = self.text_extents(text, size_mm, font)
        return x_mm - x_bearing_mm - width_mm * 0.5, top_y_mm - y_bearing_mm