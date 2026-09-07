"""Scale-aware geometry for the paper editor's Klavarskribo system."""

from __future__ import annotations

from dataclasses import dataclass

from keytab2_model.layout import Layout


@dataclass(frozen=True)
class SystemMetrics:
    scale: float
    page_inset_mm: float
    measure_number_offset_mm: float
    measure_number_size_mm: float
    barline_width_mm: float
    control_width_mm: float
    control_height_mm: float
    control_top_gap_mm: float
    control_text_inset_mm: float
    control_text_baseline_mm: float
    control_text_size_mm: float
    control_dot_x_inset_mm: float
    control_dot_radius_mm: float
    control_dot_y_offsets_mm: tuple[float, float, float]

    @classmethod
    def from_layout(cls, layout: Layout, stave_scale: float = 1.0) -> "SystemMetrics":
        scale = layout.engraving_scale(stave_scale)
        return cls(
            scale=scale,
            page_inset_mm=9.0 * scale,
            measure_number_offset_mm=6.5 * scale,
            measure_number_size_mm=3.4 * scale,
            barline_width_mm=float(layout.grid_barline_thickness_mm) * scale,
            control_width_mm=23.0 * scale,
            control_height_mm=6.5 * scale,
            control_top_gap_mm=2.5 * scale,
            control_text_inset_mm=1.0 * scale,
            control_text_baseline_mm=4.3 * scale,
            control_text_size_mm=2.8 * scale,
            control_dot_x_inset_mm=2.4 * scale,
            control_dot_radius_mm=0.38 * scale,
            control_dot_y_offsets_mm=(1.8 * scale, 3.25 * scale, 4.7 * scale),
        )