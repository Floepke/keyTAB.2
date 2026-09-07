"""Cached note, continuation-dot, and stop-sign drawing."""

from __future__ import annotations

from ui.drawers.base import DrawerBase
from ui.render_cache import NoteGeometry


class NoteDrawer(DrawerBase):
    def draw(self, note: NoteGeometry, dot_diameter_mm: float, *, show_body: bool, show_head: bool, show_stem: bool, show_stop: bool, show_continuation_dots: bool) -> None:
        if show_body:
            self.draw_poly_line(note.body_points_mm, width_mm=0.0, fill_color=note.body_color, closed=True, tags=("midi_body",))
        if show_head and not note.continues_from_previous:
            if note.head.form == "cross":
                self.draw_line(*note.head.points_mm[0], *note.head.points_mm[1], width_mm=note.head_outline_width_mm, tags=("note_head",))
                self.draw_line(*note.head.points_mm[3], *note.head.points_mm[4], width_mm=note.head_outline_width_mm, tags=("note_head",))
            else:
                self.draw_poly_line(note.head.points_mm, width_mm=note.head_outline_width_mm, fill_color=self.ink_color if note.head.filled else (0.99, 0.98, 0.95), closed=True, tags=("note_head",))
        if show_stem and note.stem[0] != note.stem[2]:
            self.draw_line(*note.stem, width_mm=note.stem_width_mm, tags=("note_stem",))
        if show_stem and note.chord_connector is not None:
            self.draw_line(*note.chord_connector, width_mm=note.stem_width_mm, tags=("chord_connector",))
        if show_stop and note.stop_points_mm is not None:
            self.draw_poly_line(note.stop_points_mm, width_mm=note.stop_width_mm, tags=("note_stop",))
        if show_continuation_dots:
            for x_mm, y_mm in note.continuation_dot_centres_mm:
                self.draw_oval(x_mm - dot_diameter_mm * 0.5, y_mm - dot_diameter_mm * 0.5, dot_diameter_mm, dot_diameter_mm, fill_color=self.ink_color, tags=("continuation_dot",))