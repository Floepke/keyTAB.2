"""Cached beam drawing."""

from __future__ import annotations

from ui.drawers.base import DrawerBase
from ui.render_cache import BeamGeometry


class BeamDrawer(DrawerBase):
    def draw(self, beam: BeamGeometry, stem_thickness_mm: float) -> None:
        self.draw_polygon(beam.polygon_mm, width_mm=0.0, fill_color=self.ink_color, tags=("beam",))
        for segment in beam.segments_mm:
            self.draw_line(*segment, width_mm=stem_thickness_mm, tags=("beam_connector",))