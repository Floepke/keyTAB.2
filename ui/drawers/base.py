"""Shared coordinate helpers for paper drawers."""

from __future__ import annotations

import cairocffi as cairo
import pangocairocffi
import pangocffi
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from keytab2_model.font import Font


DRAW_LAYERS = {
    "snap_band": 0,
    "midi_body": 5,
    "grid_barline": 10,
    "stave_connector": 10,
    "grid_line": 10,
    "stave_line": 20,
    "time_signature": 30,
    "note_head": 40,
    "note_stem": 40,
    "chord_connector": 40,
    "note_stop": 40,
    "continuation_dot": 40,
    "beam": 50,
    "beam_connector": 50,
    "slur": 55,
    "measure_number": 60,
    "editor_control": 70,
}


@dataclass(frozen=True)
class DrawCommand:
    tags: tuple[str, ...]
    paint: object


class DrawCommandBuffer:
    """Collect Cairo primitives and paint them in stable tag-layer order."""

    def __init__(self) -> None:
        self.commands: list[DrawCommand] = []

    def add(self, tags: Sequence[str], paint) -> None:
        self.commands.append(DrawCommand(tuple(tags), paint))

    def flush(self) -> None:
        for command in sorted(self.commands, key=lambda item: min((DRAW_LAYERS.get(tag, 100) for tag in item.tags), default=100)):
            command.paint()
        self.commands.clear()


class DrawerBase:
    """Draw final document-millimetre geometry onto the active Cairo context.

    The canvas establishes the sole document-mm-to-raster-pixel transform.
    Callers must convert scale-relative engraving values before invoking these
    methods; values passed here are never implicitly scaled.
    """
    LINE_CAPS = {
        "butt": cairo.LINE_CAP_BUTT,
        "round": cairo.LINE_CAP_ROUND,
        "square": cairo.LINE_CAP_SQUARE,
    }
    LINE_JOINS = {
        "miter": cairo.LINE_JOIN_MITER,
        "round": cairo.LINE_JOIN_ROUND,
        "bevel": cairo.LINE_JOIN_BEVEL,
    }

    def __init__(self, context: cairo.Context, ink_color: tuple[float, float, float], command_buffer: DrawCommandBuffer | None = None) -> None:
        self.context = context
        self.ink_color = ink_color
        self.command_buffer = command_buffer

    def _draw(self, tags: Sequence[str], paint) -> None:
        if self.command_buffer is None:
            paint()
        else:
            self.command_buffer.add(tags, paint)

    def draw_line(
        self,
        x1_mm: float,
        y1_mm: float,
        x2_mm: float,
        y2_mm: float,
        width_mm: float = 1.0,
        color: tuple[float, float, float] | None = None,
        dash_pattern_mm: Sequence[float] | None = None,
        cap: Literal["butt", "round", "square"] = "round",
        tags: Sequence[str] = ("default",),
    ) -> None:
        def paint() -> None:
            self.context.set_line_width(width_mm)
            self.context.set_line_cap(self.LINE_CAPS[cap])
            self.context.set_dash(list(dash_pattern_mm or []))
            self.context.set_source_rgb(*(color or self.ink_color))
            self.context.move_to(x1_mm, y1_mm)
            self.context.line_to(x2_mm, y2_mm)
            self.context.stroke()
            self.context.set_dash([])
        self._draw(tags, paint)

    def draw_rectangle(
        self,
        x_mm: float,
        y_mm: float,
        width_mm: float,
        height_mm: float,
        fill_color: tuple[float, float, float] | None = None,
        stroke_color: tuple[float, float, float] | None = None,
        stroke_width_mm: float = 1.0,
        tags: Sequence[str] = ("default",),
    ) -> None:
        def paint() -> None:
            self.context.rectangle(x_mm, y_mm, width_mm, height_mm)
            if fill_color is not None:
                self.context.set_source_rgb(*fill_color)
                self.context.fill_preserve() if stroke_color is not None else self.context.fill()
            if stroke_color is not None:
                self.context.set_line_width(stroke_width_mm)
                self.context.set_source_rgb(*stroke_color)
                self.context.stroke()
        self._draw(tags, paint)

    def draw_oval(
        self,
        x_mm: float,
        y_mm: float,
        width_mm: float,
        height_mm: float,
        fill_color: tuple[float, float, float] | None = None,
        stroke_color: tuple[float, float, float] | None = None,
        stroke_width_mm: float = 1.0,
        tags: Sequence[str] = ("default",),
    ) -> None:
        def paint() -> None:
            self.context.save()
            self.context.translate(x_mm + width_mm * 0.5, y_mm + height_mm * 0.5)
            self.context.scale(width_mm * 0.5, height_mm * 0.5)
            self.context.arc(0.0, 0.0, 1.0, 0.0, 2.0 * 3.141592653589793)
            self.context.restore()
            if fill_color is not None:
                self.context.set_source_rgb(*fill_color)
                self.context.fill_preserve() if stroke_color is not None else self.context.fill()
            if stroke_color is not None:
                self.context.set_line_width(stroke_width_mm)
                self.context.set_source_rgb(*stroke_color)
                self.context.stroke()
        self._draw(tags, paint)

    def draw_poly_line(
        self,
        points_mm: Sequence[tuple[float, float]],
        width_mm: float = 1.0,
        color: tuple[float, float, float] | None = None,
        closed: bool = False,
        fill_color: tuple[float, float, float] | None = None,
        join_style: Literal["miter", "round", "bevel"] = "round",
        cap: Literal["butt", "round", "square"] = "round",
        tags: Sequence[str] = ("default",),
    ) -> None:
        if len(points_mm) < 2:
            return
        def paint() -> None:
            self.context.move_to(*points_mm[0])
            for point in points_mm[1:]:
                self.context.line_to(*point)
            if closed:
                self.context.close_path()
            if fill_color is not None:
                self.context.set_source_rgb(*fill_color)
                self.context.fill_preserve()
            self.context.set_line_width(width_mm)
            self.context.set_line_join(self.LINE_JOINS[join_style])
            self.context.set_line_cap(self.LINE_CAPS[cap])
            self.context.set_source_rgb(*(color or self.ink_color))
            self.context.stroke()
        self._draw(tags, paint)

    def draw_polyline(
        self,
        points_mm: Sequence[tuple[float, float]],
        width_mm: float = 1.0,
        color: tuple[float, float, float] | None = None,
        closed: bool = False,
        fill_color: tuple[float, float, float] | None = None,
        join_style: Literal["miter", "round", "bevel"] = "round",
        cap: Literal["butt", "round", "square"] = "round",
        tags: Sequence[str] = ("default",),
    ) -> None:
        self.draw_poly_line(points_mm, width_mm, color, closed, fill_color, join_style, cap, tags)

    def draw_polygon(
        self,
        points_mm: Sequence[tuple[float, float]],
        width_mm: float = 1.0,
        color: tuple[float, float, float] | None = None,
        fill_color: tuple[float, float, float] | None = None,
        tags: Sequence[str] = ("default",),
    ) -> None:
        self.draw_poly_line(points_mm, width_mm, color, closed=True, fill_color=fill_color, tags=tags)

    def _pango_layout(self, text: str, size_mm: float, font: Font | None):
        family = font.resolve_family() if font is not None else "Sans"
        description = pangocffi.FontDescription()
        description.family = family
        description.set_absolute_size(pangocffi.units_from_double(size_mm))
        description.style = pangocffi.Style.ITALIC if font is not None and font.italic else pangocffi.Style.NORMAL
        description.weight = pangocffi.Weight.BOLD if font is not None and font.bold else pangocffi.Weight.NORMAL
        layout = pangocairocffi.create_layout(self.context)
        layout.font_description = description
        layout.text = text
        return layout

    def text_extents(self, text: str, size_mm: float, font: Font | None = None) -> tuple[float, float, float, float]:
        """Return Pango logical glyph bounds in final document millimetres."""
        if not isinstance(self.context, cairo.Context):
            x_bearing, y_bearing, width_mm, height_mm, _, _ = self.context.text_extents(text)
            return float(x_bearing), float(y_bearing), float(width_mm), float(height_mm)
        layout = self._pango_layout(text, size_mm, font)
        ink, _ = layout.get_extents()
        baseline_mm = pangocffi.units_to_double(layout.get_baseline())
        return (
            pangocffi.units_to_double(ink.x),
            pangocffi.units_to_double(ink.y) - baseline_mm,
            pangocffi.units_to_double(ink.width),
            pangocffi.units_to_double(ink.height),
        )

    def draw_text(self, text: str, x_mm: float, y_mm: float, size_mm: float, font: Font | None = None, tags: Sequence[str] = ("default",)) -> None:
        def paint() -> None:
            x_offset = font.x_offset if font is not None else 0.0
            y_offset = font.y_offset if font is not None else 0.0
            if not isinstance(self.context, cairo.Context):
                self.context.move_to(x_mm + x_offset, y_mm + y_offset)
                self.context.show_text(text)
                return
            layout = self._pango_layout(text, size_mm, font)
            baseline_mm = pangocffi.units_to_double(layout.get_baseline())
            self.context.set_source_rgb(*self.ink_color)
            self.context.move_to(x_mm + x_offset, y_mm + y_offset - baseline_mm)
            pangocairocffi.show_layout(self.context, layout)
        self._draw(tags, paint)