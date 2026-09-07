#!/usr/bin/env python3
"""Generate an Edwin-font 4/4 time-signature toolbar icon.

This standalone asset experiment intentionally lives outside the tracked app
sources. Run from the repository root with:

    .venv/bin/python excluding/generate_time_signature_icon.py

The output is a transparent 567 x 567 PNG beside this script.
"""

from __future__ import annotations

from pathlib import Path

import cairocffi as cairo
import pangocairocffi
import pangocffi


ICON_SIZE_PX = 567
FONT_FAMILY = "Edwin"
FONT_SIZE_PX = 300
DIVIDER_THICKNESS_PX = 24
DIVIDER_Y_PX = ICON_SIZE_PX // 2
GLYPH_GAP_PX = 22
OUTPUT_PATH = Path(__file__).with_name("time_signature_edwin.png")


def text_layout(context: cairo.Context, text: str):
    layout = pangocairocffi.create_layout(context)
    font = pangocffi.FontDescription()
    font.family = FONT_FAMILY
    font.weight = pangocffi.Weight.BOLD
    font.set_absolute_size(pangocffi.units_from_double(FONT_SIZE_PX))
    layout.font_description = font
    layout.text = text
    return layout


def draw_centered(context: cairo.Context, layout, centre_y_px: float) -> None:
    ink_rect, _ = layout.get_extents()
    x_px = (ICON_SIZE_PX - pangocffi.units_to_double(ink_rect.width)) * 0.5 - pangocffi.units_to_double(ink_rect.x)
    y_px = centre_y_px - pangocffi.units_to_double(ink_rect.height) * 0.5 - pangocffi.units_to_double(ink_rect.y)
    context.move_to(x_px, y_px)
    pangocairocffi.show_layout(context, layout)


def main() -> None:
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, ICON_SIZE_PX, ICON_SIZE_PX)
    context = cairo.Context(surface)
    context.set_operator(cairo.OPERATOR_SOURCE)
    context.set_source_rgba(0.0, 0.0, 0.0, 0.0)
    context.paint()
    context.set_operator(cairo.OPERATOR_OVER)
    context.set_source_rgb(0.0, 0.0, 0.0)

    layout = text_layout(context, "4")
    ink_rect, _ = layout.get_extents()
    glyph_height_px = pangocffi.units_to_double(ink_rect.height)
    top_centre_y_px = DIVIDER_Y_PX - DIVIDER_THICKNESS_PX * 0.5 - GLYPH_GAP_PX - glyph_height_px * 0.5
    bottom_centre_y_px = DIVIDER_Y_PX + DIVIDER_THICKNESS_PX * 0.5 + GLYPH_GAP_PX + glyph_height_px * 0.5
    draw_centered(context, layout, top_centre_y_px)

    context.set_line_width(DIVIDER_THICKNESS_PX)
    context.move_to(ICON_SIZE_PX * 0.18, DIVIDER_Y_PX)
    context.line_to(ICON_SIZE_PX * 0.82, DIVIDER_Y_PX)
    context.stroke()

    draw_centered(context, layout, bottom_centre_y_px)
    surface.write_to_png(str(OUTPUT_PATH))
    print(f"Wrote {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
