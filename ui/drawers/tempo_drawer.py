"""Tempo-marking drawing."""

from __future__ import annotations

from keytab2_model.events import TempoEvent
from keytab2_model.font import Font
from ui.drawers.base import DrawerBase


class TempoDrawer(DrawerBase):
    """Draw a tempo value in an open-left duration hook."""

    def draw(self, tempo: TempoEvent, top_start_x_mm: float, text_left_x_mm: float, start_y_mm: float, end_y_mm: float, size_mm: float, font: Font) -> None:
        if tempo.invisible:
            return
        tempo_text = str(tempo.tempo)
        x_bearing_mm, y_bearing_mm, text_width_mm, text_height_mm = self.text_extents(tempo_text, size_mm, font)
        text_width_mm = max(1.0, text_width_mm)
        text_height_mm = max(0.5, text_height_mm)
        right_padding_mm = max(0.6, size_mm * 0.7)
        hook_right_x_mm = text_left_x_mm + text_width_mm + right_padding_mm
        text_center_x_mm = text_left_x_mm + text_width_mm * 0.5
        text_center_y_mm = (start_y_mm + end_y_mm) * 0.5
        stroke_width_mm = max(0.2, size_mm * 0.04)
        dash_pattern_mm = (0.5, 1.0)

        self.draw_line(top_start_x_mm, start_y_mm, hook_right_x_mm, start_y_mm, stroke_width_mm, dash_pattern_mm=dash_pattern_mm, tags=("tempo",))
        self.draw_line(hook_right_x_mm, start_y_mm, hook_right_x_mm, end_y_mm, stroke_width_mm, dash_pattern_mm=dash_pattern_mm, tags=("tempo",))
        self.draw_line(text_left_x_mm, end_y_mm, hook_right_x_mm, end_y_mm, stroke_width_mm, dash_pattern_mm=dash_pattern_mm, tags=("tempo",))
        self.draw_text(
            tempo_text,
            text_center_x_mm - text_width_mm * 0.5 - x_bearing_mm,
            text_center_y_mm - text_height_mm * 0.5 - y_bearing_mm,
            size_mm,
            font,
            tags=("tempo",),
        )