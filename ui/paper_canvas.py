"""Cached Cairo rendering surface for the direct keyTAB2 paper editor."""

from __future__ import annotations

import cairocffi as cairo
from collections import OrderedDict
from copy import deepcopy
from dataclasses import asdict, replace
import json
import math
from pathlib import Path
from uuid import uuid4

from PySide6.QtCore import QPoint, QPointF, QRect, QRectF, Qt, Signal
from PySide6.QtGui import QAction, QColor, QCursor, QImage, QKeySequence, QPainter, QPainterPath, QPalette, QPen, QPolygonF
from PySide6.QtWidgets import QInputDialog, QMenu, QWidget

from keytab2_model import KeyTab2Document, NoteEvent, SlurEvent, Stave
from keytab2_model.base_grid import grid_boundaries, grid_line_boundaries
from ui.drawers.grid_drawer import GridDrawer
from ui.drawers.beam_drawer import BeamDrawer
from ui.drawers.note_drawer import NoteDrawer
from ui.drawers.slur_drawer import SlurDrawer
from ui.drawers.metrics import SystemMetrics
from ui.drawers.base import DrawCommandBuffer, DrawerBase
from ui.drawers.snap_drawer import SnapDrawer
from ui.drawers.stave_drawer import StaveDrawer
from ui.drawers.stave_connector_drawer import StaveConnectorDrawer
from ui.drawers.time_signature_drawer import TimeSignatureDrawer
from ui.dialogs.stave_dialogs import StaveRangeDialog, StavesDialog
from ui.render_cache import NoteGeometry, StaveRenderData, build_stave_render_data
from ui.tools import NoteTool, SlurTool, SystemBreakTool, TimeSignatureTool, ToolManager
from utils.CONSTANT import SHORTEST_DURATION, SLUR_SEGMENT_COUNT
from utils.operator import Operator


class PaperCanvas(QWidget):
    """Draw the current document's paper pages using cached Cairo images."""

    note_hand_changed = Signal(str)
    note_audition_requested = Signal(int, int)

    BASE_PIXELS_PER_MM = 3.0
    MIN_ZOOM = 0.25
    MAX_ZOOM = 4.0
    PAPER_COLOR = (0.99, 0.98, 0.95)
    INK_COLOR = (0.09, 0.12, 0.14)
    STAVE_GAP_MM = 12.0
    TILE_SIZE_PX = 256
    TILE_BLEED_PX = 3
    MAX_CACHED_TILES = 128
    BARLINE_HIT_TOLERANCE_PX = 7
    CONTROL_HOVER_TOLERANCE_PX = 30
    STAVE_CONTROL_SIZE_MM = 5.0
    STAVE_CONTROL_GAP_MM = 1.5
    ADD_MEASURE_CONTROL_SIZE_MM = 5.0
    ADD_MEASURE_CONTROL_GAP_MM = 2.0

    def __init__(self, document: KeyTab2Document, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._document = document
        self._page_index = 0
        self._zoom = 1.0
        self._tile_cache: OrderedDict[tuple[float, int, int], QImage] = OrderedDict()
        self._stave_render_cache: dict[tuple[str, str], tuple[tuple, StaveRenderData]] = {}
        self._page_system_bounds_cache: dict[str, tuple[tuple[str, ...], dict[str, tuple[float, float]]]] = {}
        self._selected_barline: tuple[str, int] | None = None
        self._selected_note_ids: set[str] = set()
        self._selected_slur_ids: set[str] = set()
        self._clipboard_notes: list[NoteEvent] = []
        self._clipboard_slurs: list[SlurEvent] = []
        self._selection_anchor_mm: QPointF | None = None
        self._selection_current_mm: QPointF | None = None
        self._document_change_callback = None
        self._undo_callback = None
        self._redo_callback = None
        self._control_target: tuple[str, str] | None = None
        self._tool_manager = ToolManager(self)
        self._note_tool = NoteTool()
        self._slur_tool = SlurTool()
        self._system_break_tool = SystemBreakTool()
        self._time_signature_tool = TimeSignatureTool()
        self._tool_manager.register(self._note_tool)
        self._tool_manager.register(self._slur_tool)
        self._tool_manager.register(self._system_break_tool)
        self._tool_manager.register(self._time_signature_tool)
        self._tool_manager.activate(self._note_tool.TOOL_NAME)
        self._left_tool_active = False
        self.input_snap_ticks = float(NoteTool.SNAP_TICKS)
        self.mouse_time: float | None = None
        self.mouse_pitch: int | None = None
        self._last_mouse_position_mm: QPointF | None = None
        self._mouse_stave_target = None
        self.setAutoFillBackground(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self._update_size()

    def set_document(self, document: KeyTab2Document) -> None:
        self._document = document
        self._page_index = 0
        self._left_tool_active = False
        self._selected_note_ids.clear()
        self._selected_slur_ids.clear()
        self._selection_anchor_mm = None
        self._selection_current_mm = None
        self.invalidate_render_cache()
        self._update_size()
        self.update()

    def set_document_change_callback(self, callback) -> None:
        self._document_change_callback = callback

    def set_history_callbacks(self, undo_callback, redo_callback) -> None:
        self._undo_callback = undo_callback
        self._redo_callback = redo_callback

    def commit_document_change(self) -> None:
        if self._document_change_callback is not None:
            self._document_change_callback()

    @property
    def page_index(self) -> int:
        return self._page_index

    @property
    def page_count(self) -> int:
        return len(self._document.pages)

    @property
    def document(self) -> KeyTab2Document:
        return self._document

    @property
    def current_page(self):
        return self._current_page()

    def set_page_index(self, page_index: int) -> None:
        clamped_index = max(0, min(int(page_index), self.page_count - 1))
        if clamped_index == self._page_index:
            return
        self._page_index = clamped_index
        self._tile_cache.clear()
        self._stave_render_cache.clear()
        self._selected_barline = None
        self._selected_note_ids.clear()
        self._selected_slur_ids.clear()
        self._selection_anchor_mm = None
        self._selection_current_mm = None
        self._mouse_stave_target = None
        self._last_mouse_position_mm = None
        self._update_size()
        self.update()

    @property
    def zoom(self) -> float:
        return self._zoom

    @property
    def pixels_per_mm(self) -> float:
        return self.BASE_PIXELS_PER_MM * self._zoom

    def set_zoom(self, zoom: float) -> None:
        clamped_zoom = max(self.MIN_ZOOM, min(self.MAX_ZOOM, float(zoom)))
        if abs(clamped_zoom - self._zoom) < 1e-6:
            return
        self._zoom = clamped_zoom
        self._tile_cache.clear()
        self._update_size()
        self.update()

    def _update_size(self) -> None:
        page = self._current_page()
        self.setFixedSize(
            round(page.width_mm * self.pixels_per_mm),
            round(page.height_mm * self.pixels_per_mm),
        )

    def paintEvent(self, event) -> None:
        exposed_rect = event.rect().intersected(self.rect())
        if exposed_rect.isEmpty():
            return
        painter = QPainter(self)
        first_tile_x = exposed_rect.left() // self.TILE_SIZE_PX
        last_tile_x = exposed_rect.right() // self.TILE_SIZE_PX
        first_tile_y = exposed_rect.top() // self.TILE_SIZE_PX
        last_tile_y = exposed_rect.bottom() // self.TILE_SIZE_PX
        for tile_y in range(first_tile_y, last_tile_y + 1):
            for tile_x in range(first_tile_x, last_tile_x + 1):
                tile_rect = QRect(tile_x * self.TILE_SIZE_PX, tile_y * self.TILE_SIZE_PX, self.TILE_SIZE_PX, self.TILE_SIZE_PX).intersected(self.rect())
                painter.drawImage(tile_rect, self._tile_image(tile_rect, tile_x, tile_y))
        self._draw_interaction_overlay(painter, exposed_rect)

    def invalidate_render_cache(self, stave_id: str | None = None) -> None:
        """Invalidate tiles and optional one-stave geometry after a document edit."""
        self._tile_cache.clear()
        if stave_id is None:
            self._stave_render_cache.clear()
            self._page_system_bounds_cache.clear()
        else:
            self._stave_render_cache = {
                key: value for key, value in self._stave_render_cache.items() if key[1] != stave_id
            }
        self.update()

    def invalidate_system_render_cache(self, system_id: str, stave_id: str | None = None) -> None:
        """Invalidate only the rendered region and geometry owned by one system."""
        for key in tuple(self._stave_render_cache):
            cached_system_id, cached_stave_id = key
            if cached_system_id == system_id and (stave_id is None or cached_stave_id == stave_id):
                del self._stave_render_cache[key]

        page = self._current_page()
        system = next((candidate for candidate in page.systems if candidate.id == system_id), None)
        if system is None:
            return
        dirty_rect = self._system_pixel_rect(page, system)
        for key in tuple(self._tile_cache):
            _, tile_x, tile_y = key
            tile_rect = QRect(
                tile_x * self.TILE_SIZE_PX,
                tile_y * self.TILE_SIZE_PX,
                self.TILE_SIZE_PX,
                self.TILE_SIZE_PX,
            )
            if tile_rect.intersects(dirty_rect):
                del self._tile_cache[key]
        self.update(dirty_rect)

    def ledger_layout_signature(self) -> tuple[tuple[str, str, tuple[int, ...]], ...]:
        """Return the per-system ledger geometry that can affect page layout."""
        return tuple(
            (system.id, stave.id, stave.line_pitches(system))
            for page in self._document.pages
            for system in page.systems
            for stave in system.staves
        )

    def repaginate_if_ledger_layout_changed(self, before: tuple[tuple[str, str, tuple[int, ...]], ...]) -> bool:
        """Repack pages only after an edit adds or removes ledger geometry."""
        if self.ledger_layout_signature() != before:
            self.repaginate_document()
            return True
        return False

    def _tile_image(self, tile_rect: QRect, tile_x: int, tile_y: int) -> QImage:
        key = (round(self._zoom, 6), tile_x, tile_y)
        image = self._tile_cache.get(key)
        if image is not None:
            self._tile_cache.move_to_end(key)
            return image
        image = self._render_region(tile_rect)
        self._tile_cache[key] = image
        if len(self._tile_cache) > self.MAX_CACHED_TILES:
            self._tile_cache.popitem(last=False)
        return image

    def _render_region(self, exposed_rect: QRect) -> QImage:
        page = self._current_page()
        render_rect = exposed_rect.adjusted(
            -self.TILE_BLEED_PX,
            -self.TILE_BLEED_PX,
            self.TILE_BLEED_PX,
            self.TILE_BLEED_PX,
        ).intersected(self.rect())
        width = render_rect.width()
        height = render_rect.height()
        buffer = bytearray(width * height * 4)
        surface = cairo.ImageSurface.create_for_data(buffer, cairo.FORMAT_ARGB32, width, height, width * 4)
        context = cairo.Context(surface)
        context.set_antialias(cairo.ANTIALIAS_BEST)
        context.scale(self.pixels_per_mm, self.pixels_per_mm)
        context.translate(
            -render_rect.x() / self.pixels_per_mm,
            -render_rect.y() / self.pixels_per_mm,
        )

        context.set_source_rgb(*self.PAPER_COLOR)
        context.paint()
        visible_top_mm = render_rect.top() / self.pixels_per_mm
        visible_bottom_mm = (render_rect.bottom() + 1) / self.pixels_per_mm
        self._draw_page_to_cairo(
            context,
            page,
            render_rect.left() / self.pixels_per_mm,
            (render_rect.right() + 1) / self.pixels_per_mm,
            visible_top_mm,
            visible_bottom_mm,
            include_snap_bands=self._document.layout.grid_band_visible,
            include_editor_controls=True,
        )

        surface.flush()
        rendered_image = QImage(buffer, width, height, width * 4, QImage.Format.Format_ARGB32_Premultiplied).copy()
        surface.finish()
        return rendered_image.copy(
            exposed_rect.x() - render_rect.x(),
            exposed_rect.y() - render_rect.y(),
            exposed_rect.width(),
            exposed_rect.height(),
        )

    def export_pdf(self, path: str | Path) -> None:
        """Export every document page as vector PDF, excluding editor-only aids."""
        target = Path(path)
        if target.suffix.lower() != ".pdf":
            target = target.with_suffix(".pdf")
        surface: cairo.PDFSurface | None = None
        try:
            for page_index, page in enumerate(self._document.pages):
                width_pt = page.width_mm * 72.0 / 25.4
                height_pt = page.height_mm * 72.0 / 25.4
                if surface is None:
                    surface = cairo.PDFSurface(str(target), width_pt, height_pt)
                else:
                    surface.set_size(width_pt, height_pt)
                context = cairo.Context(surface)
                context.scale(72.0 / 25.4, 72.0 / 25.4)
                context.set_source_rgb(1.0, 1.0, 1.0)
                context.paint()
                self._draw_page_to_cairo(
                    context,
                    page,
                    0.0,
                    page.width_mm,
                    0.0,
                    page.height_mm,
                    include_snap_bands=False,
                    include_midi_only_ledgers=False,
                    include_editor_controls=False,
                    slur_segment_count=SLUR_SEGMENT_COUNT,
                )
                if page_index < len(self._document.pages) - 1:
                    surface.show_page()
        finally:
            if surface is not None:
                surface.finish()

    def _draw_page_to_cairo(self, context, page, visible_left_mm: float, visible_right_mm: float, visible_top_mm: float, visible_bottom_mm: float, include_snap_bands: bool, include_midi_only_ledgers: bool = True, include_editor_controls: bool = True, slur_segment_count: int = 24) -> None:
        layout = self._document.layout
        command_buffer = DrawCommandBuffer()
        page_drawer = DrawerBase(context, self.INK_COLOR, command_buffer)
        page_index = self._document.pages.index(page)
        self._draw_page_metadata(
            page_drawer,
            page,
            page_index,
            visible_left_mm,
            visible_right_mm,
            visible_top_mm,
            visible_bottom_mm,
        )
        grid_drawer = GridDrawer(context, self.INK_COLOR, command_buffer)
        snap_drawer = SnapDrawer(context, self.INK_COLOR, command_buffer)
        stave_drawer = StaveDrawer(context, self.INK_COLOR, command_buffer)
        stave_connector_drawer = StaveConnectorDrawer(context, self.INK_COLOR, command_buffer)
        time_signature_drawer = TimeSignatureDrawer(context, self.INK_COLOR, command_buffer)
        note_drawer = NoteDrawer(context, self.INK_COLOR, command_buffer)
        beam_drawer = BeamDrawer(context, self.INK_COLOR, command_buffer)
        slur_drawer = SlurDrawer(context, self.INK_COLOR, command_buffer)
        culling_metrics = SystemMetrics.from_layout(layout, max(stave.scale for system in page.systems for stave in system.staves))
        final_system = self._document.pages[-1].systems[-1]
        for system in page.systems:
            if not self._system_intersects_render_region(page, system, visible_left_mm, visible_right_mm, visible_top_mm, visible_bottom_mm, include_editor_controls):
                continue
            self._draw_system(grid_drawer, snap_drawer, stave_drawer, stave_connector_drawer, time_signature_drawer, note_drawer, beam_drawer, slur_drawer, page, system, self._system_column_bounds(page, system), visible_top_mm, visible_bottom_mm, include_snap_bands, include_midi_only_ledgers, include_editor_controls, system is final_system, slur_segment_count)
        command_buffer.flush()

    def _draw_page_metadata(
        self,
        drawer: DrawerBase,
        page,
        page_index: int,
        visible_left_mm: float,
        visible_right_mm: float,
        visible_top_mm: float,
        visible_bottom_mm: float,
    ) -> None:
        """Draw first-page title metadata and each page's copyright footer."""
        layout = self._document.layout
        info = self._document.score_info
        left_mm = layout.page_left_margin_mm
        right_mm = page.width_mm - layout.page_right_margin_mm
        if page_index == 0 and visible_top_mm <= layout.page_top_margin_mm + layout.header_height_mm:
            title = info.title.strip()
            composer = info.composer.strip()
            if title and visible_left_mm <= right_mm and visible_right_mm >= left_mm:
                size_mm = layout.engraving_pt_to_mm(layout.font_title.size_pt)
                _, title_y_bearing_mm, _, _ = drawer.text_extents(title, size_mm, layout.font_title)
                drawer.draw_text(
                    title,
                    left_mm,
                    layout.page_top_margin_mm - title_y_bearing_mm,
                    size_mm,
                    layout.font_title,
                    tags=("title",),
                )
            if composer:
                size_mm = layout.engraving_pt_to_mm(layout.font_composer.size_pt)
                _, composer_y_bearing_mm, width_mm, _ = drawer.text_extents(composer, size_mm, layout.font_composer)
                drawer.draw_text(
                    composer,
                    right_mm - width_mm,
                    layout.page_top_margin_mm - composer_y_bearing_mm,
                    size_mm,
                    layout.font_composer,
                    tags=("composer",),
                )
        footer_top_mm = page.height_mm - layout.page_bottom_margin_mm - layout.footer_height_mm
        if visible_top_mm <= page.height_mm and visible_bottom_mm >= footer_top_mm:
            title = info.title.strip() or "Untitled"
            copyright_text = info.copyright.strip()
            footer = f"Page {page_index + 1} of {len(self._document.pages)} - {title}"
            if copyright_text:
                footer += f" - {copyright_text}"
            drawer.draw_text(
                footer,
                left_mm,
                page.height_mm - layout.page_bottom_margin_mm,
                layout.engraving_pt_to_mm(layout.font_copyright.size_pt),
                layout.font_copyright,
                tags=("copyright",),
            )

    @staticmethod
    def _system_intersects_visible_region(system, metrics: SystemMetrics, visible_top_mm: float, visible_bottom_mm: float) -> bool:
        del metrics
        system_bottom_mm = system.top_mm + system.height_mm
        return system_bottom_mm >= visible_top_mm and system.top_mm <= visible_bottom_mm

    def _system_intersects_horizontal_region(self, page, system, visible_left_mm: float, visible_right_mm: float) -> bool:
        system_left_mm, system_right_mm = self._system_column_bounds(page, system)
        return system_right_mm >= visible_left_mm and system_left_mm <= visible_right_mm

    def _system_intersects_render_region(self, page, system, visible_left_mm: float, visible_right_mm: float, visible_top_mm: float, visible_bottom_mm: float, include_editor_controls: bool) -> bool:
        system_left_mm, system_right_mm, system_top_mm, system_bottom_mm = self._system_render_bounds(page, system, include_editor_controls)
        return (
            system_right_mm >= visible_left_mm
            and system_left_mm <= visible_right_mm
            and system_bottom_mm >= visible_top_mm
            and system_top_mm <= visible_bottom_mm
        )

    def _draw_system(self, grid_drawer: GridDrawer, snap_drawer: SnapDrawer, stave_drawer: StaveDrawer, stave_connector_drawer: StaveConnectorDrawer, time_signature_drawer: TimeSignatureDrawer, note_drawer: NoteDrawer, beam_drawer: BeamDrawer, slur_drawer: SlurDrawer, page, system, column_bounds: tuple[float, float], visible_top_mm: float, visible_bottom_mm: float, include_snap_bands: bool, include_midi_only_ledgers: bool, include_editor_controls: bool, is_final_system: bool, slur_segment_count: int) -> None:
        stave_left_positions = self._centered_stave_left_positions(system, stave_drawer, self._document.layout, *column_bounds)
        natural_stave_bounds = [
            stave_drawer.bounds(stave, self._document.layout, left_mm)
            for stave, left_mm in zip(system.staves, stave_left_positions, strict=True)
        ]
        measure_starts, _ = grid_boundaries(self._document.base_grid, self._document.time_per_quarter)
        metrics = [SystemMetrics.from_layout(self._document.layout, stave.scale) for stave in system.staves]
        if all(bounds is not None for bounds in natural_stave_bounds):
            stave_connector_drawer.draw(
                system,
                natural_stave_bounds,
                measure_starts,
                max(metric.barline_width_mm for metric in metrics),
                max(metric.barline_width_mm * 2.0 if is_final_system else metric.barline_width_mm for metric in metrics),
            )
        time_signature_drawn = False
        for stave_index, (stave, left_mm) in enumerate(zip(system.staves, stave_left_positions, strict=True)):
            metric = metrics[stave_index]
            visual_stave_bounds = stave_drawer.bounds(stave, self._document.layout, left_mm, system)
            stave_natural_bounds = natural_stave_bounds[stave_index]
            if visual_stave_bounds is None or stave_natural_bounds is None:
                continue
            render_data = self._stave_render_data(system, stave, left_mm)
            if not time_signature_drawn:
                time_signature_drawer.draw(
                    system,
                    self._document.layout,
                    stave.scale,
                    visual_stave_bounds[0],
                    self._document.base_grid,
                    self._document.time_per_quarter,
                    render_data.collision_index,
                )
                time_signature_drawn = True
            notehead_bleed_mm = self._document.layout.engraving_mm(
                4.0 * self._document.layout.notehead_height_scaling + self._document.layout.note_stem_thickness_mm,
                stave.scale,
            )
            visible_start_tick, visible_end_tick = self._visible_tick_range(
                system,
                visible_top_mm,
                visible_bottom_mm,
                notehead_bleed_mm,
            )
            grid_starts = grid_line_boundaries(self._document.base_grid, self._document.time_per_quarter)
            if include_snap_bands:
                snap_drawer.draw(system, *stave_natural_bounds, self.input_snap_ticks, measure_starts)
            grid_drawer.draw(system, self._document.layout, stave.scale, *stave_natural_bounds, measure_starts, grid_starts, metric, render_data.collision_index, is_final_system, stave_index == len(system.staves) - 1)
            if include_editor_controls and is_final_system and stave_index == len(system.staves) - 1:
                self._draw_add_measure_control(grid_drawer, system, column_bounds)
            stave_drawer.draw(
                system,
                stave,
                self._document.layout,
                left_mm,
                {note.event_id: note.continuation_dot_centres_mm for note in render_data.notes.geometries},
                include_midi_only_ledgers=include_midi_only_ledgers,
            )
            dot_diameter_mm = self._document.layout.engraving_mm(self._document.layout.note_continuation_dot_size_mm, stave.scale)
            for note in render_data.notes_in_tick_range(visible_start_tick, visible_end_tick):
                note_drawer.draw(
                    note,
                    dot_diameter_mm,
                    show_body=self._document.layout.note_midinote_visible,
                    show_head=self._document.layout.note_head_visible,
                    show_stem=self._document.layout.note_stem_visible,
                    show_stop=self._document.layout.note_stop_visible,
                    show_continuation_dots=self._document.layout.note_continuation_dot_visible,
                )
            stem_width_mm = self._document.layout.engraving_mm(self._document.layout.note_stem_thickness_mm, stave.scale)
            beam_corner_radius_mm = self._document.layout.engraving_mm(self._document.layout.beam_corner_radius_mm, stave.scale)
            if self._document.layout.beam_visible:
                for beam in render_data.beams_in_tick_range(visible_start_tick, visible_end_tick):
                    beam_drawer.draw(beam, stem_width_mm, beam_corner_radius_mm)
            if self._document.layout.slur_visible:
                semitone_mm = self._document.layout.engraving_mm(2.0, stave.scale)
                for slur in (event for event in stave.events if isinstance(event, SlurEvent)):
                    points = tuple(
                        (
                            StaveDrawer.pitch_to_x_mm(60 + rpitch, stave.pitch_range[0], left_mm, semitone_mm),
                            self._time_to_y_mm(system, tick),
                        )
                        for rpitch, tick in (
                            (slur.x1_rpitch, slur.y1_tick),
                            (slur.x2_rpitch, slur.y2_tick),
                            (slur.x3_rpitch, slur.y3_tick),
                            (slur.x4_rpitch, slur.y4_tick),
                        )
                    )
                    slur_drawer.draw(
                        points,
                        self._document.layout.engraving_mm(self._document.layout.slur_width_sides_mm, stave.scale),
                        self._document.layout.engraving_mm(self._document.layout.slur_width_middle_mm, stave.scale),
                        slur_segment_count,
                    )
            if include_editor_controls:
                self._draw_stave_control(stave_drawer, system, stave, left_mm)

    def _draw_stave_control(self, drawer: StaveDrawer, system, stave, left_mm: float) -> None:
        """Draw the editor-only stave configuration control above the stave centre."""
        centre_x_mm, centre_y_mm = self._stave_control_centre(system, stave, left_mm)
        left_mm = centre_x_mm - self.STAVE_CONTROL_SIZE_MM * 0.5
        top_mm = centre_y_mm - self.STAVE_CONTROL_SIZE_MM * 0.5
        drawer.draw_rectangle(
            left_mm,
            top_mm,
            self.STAVE_CONTROL_SIZE_MM,
            self.STAVE_CONTROL_SIZE_MM,
            fill_color=(0.78, 0.78, 0.78),
            stroke_color=(0.58, 0.58, 0.58),
            stroke_width_mm=0.25,
            tags=("editor_control",),
        )
        for offset_mm in (-1.0, 0.0, 1.0):
            drawer.draw_oval(
                centre_x_mm - 0.28,
                centre_y_mm + offset_mm - 0.28,
                0.56,
                0.56,
                fill_color=(0.35, 0.35, 0.35),
                tags=("editor_control",),
            )

    def _draw_add_measure_control(self, drawer: GridDrawer, system, column_bounds: tuple[float, float]) -> None:
        centre_x_mm = (column_bounds[0] + column_bounds[1]) * 0.5
        centre_y_mm = system.top_mm + system.height_mm + self.ADD_MEASURE_CONTROL_GAP_MM + self.ADD_MEASURE_CONTROL_SIZE_MM * 0.5
        half_size_mm = self.ADD_MEASURE_CONTROL_SIZE_MM * 0.5
        offset_mm = half_size_mm + self.ADD_MEASURE_CONTROL_GAP_MM * 0.5
        for kind, control_x_mm in (("add", centre_x_mm - offset_mm), ("remove", centre_x_mm + offset_mm)):
            drawer.draw_rectangle(control_x_mm - half_size_mm, centre_y_mm - half_size_mm, self.ADD_MEASURE_CONTROL_SIZE_MM, self.ADD_MEASURE_CONTROL_SIZE_MM, fill_color=(0.78, 0.78, 0.78), stroke_color=(0.58, 0.58, 0.58), stroke_width_mm=0.25, tags=("editor_control",))
            symbol_radius_mm = 1.25
            drawer.draw_line(control_x_mm - symbol_radius_mm, centre_y_mm, control_x_mm + symbol_radius_mm, centre_y_mm, 0.5, tags=("editor_control",))
            if kind == "add":
                drawer.draw_line(control_x_mm, centre_y_mm - symbol_radius_mm, control_x_mm, centre_y_mm + symbol_radius_mm, 0.5, tags=("editor_control",))

    def _stave_render_data(self, system, stave, left_mm: float) -> StaveRenderData:
        systems = [candidate for page in self._document.pages for candidate in page.systems]
        system_index = systems.index(system)
        stave_index = next(index for index, candidate in enumerate(system.staves) if candidate is stave)
        following_stave = (
            systems[system_index + 1].staves[stave_index]
            if system_index + 1 < len(systems) and stave_index < len(systems[system_index + 1].staves)
            else None
        )
        following_starts_by_hand = {
            hand: tuple(
                note.time
                for note in following_stave.events
                if isinstance(note, NoteEvent) and note.hand == hand
            )
            for hand in ("left", "right")
        } if following_stave is not None else {}
        key = (system.id, stave.id)
        layout_signature = json.dumps(asdict(self._document.layout), sort_keys=True, separators=(",", ":"))
        base_grid_signature = json.dumps([asdict(segment) for segment in self._document.base_grid], sort_keys=True, separators=(",", ":"))
        cache_key = (
            system.revision,
            stave.revision,
            following_stave.id if following_stave is not None else None,
            following_stave.revision if following_stave is not None else None,
            left_mm,
            layout_signature,
            base_grid_signature,
        )
        cached = self._stave_render_cache.get(key)
        if cached is None or cached[0] != cache_key:
            cached = (
                cache_key,
                build_stave_render_data(
                    system,
                    stave,
                    self._document.layout,
                    left_mm,
                    self._measure_ticks(),
                    self._document.base_grid,
                    following_starts_by_hand,
                ),
            )
            self._stave_render_cache[key] = cached
        return cached[1]

    @staticmethod
    def _visible_tick_range(system, visible_top_mm: float, visible_bottom_mm: float, bleed_mm: float = 0.0) -> tuple[int, int]:
        tick_height = system.height_mm / (system.end_tick - system.start_tick)
        bleed_ticks = max(1, math.ceil(max(0.0, bleed_mm) / tick_height))
        start_tick = max(system.start_tick, int((visible_top_mm - system.top_mm) / tick_height) + system.start_tick - bleed_ticks)
        end_tick = min(system.end_tick, int((visible_bottom_mm - system.top_mm) / tick_height) + system.start_tick + bleed_ticks + 1)
        return start_tick, max(start_tick + 1, end_tick)

    def _draw_interaction_overlay(self, painter: QPainter, exposed_rect: QRect) -> None:
        """Draw ephemeral selection state; this pass is never exported."""
        self._draw_selection_overlay(painter, exposed_rect)
        if self._tool_manager.active_tool is self._system_break_tool:
            highlight = self._system_break_highlight_geometry()
            if highlight is None:
                return
            left_mm, right_mm, y_mm = highlight
            painter.save()
            painter.setOpacity(0.7)
            painter.setPen(QPen(QColor("#1769aa"), max(2, round(self.pixels_per_mm))))
            painter.drawLine(
                round(left_mm * self.pixels_per_mm),
                round(y_mm * self.pixels_per_mm),
                round(right_mm * self.pixels_per_mm),
                round(y_mm * self.pixels_per_mm),
            )
            painter.restore()
            return
        if self._tool_manager.active_tool is self._time_signature_tool:
            self._draw_time_signature_overlay(painter, exposed_rect)
            return
        if self._tool_manager.active_tool is self._slur_tool:
            self._draw_slur_handle_overlay(painter, exposed_rect)
            return
        drag_preview = self._note_tool.drag_preview
        if drag_preview is not None:
            stave = drag_preview.stave
            note = self._translated_drag_preview(drag_preview)
        elif self._note_tool.duration_preview is not None:
            self._draw_duration_preview(painter, self._note_tool.duration_preview)
            return
        elif self._note_tool.is_editing or self._mouse_stave_target is None or self.mouse_time is None or self.mouse_pitch is None:
            return
        else:
            system, stave, left_mm = self._mouse_stave_target
            note = self._preview_note_geometry(system, stave, left_mm)
            if note is None:
                return
        accent = self.palette().color(QPalette.ColorRole.Highlight)
        paper = QColor.fromRgbF(*self.PAPER_COLOR)

        def polygon(points_mm: tuple[tuple[float, float], ...]) -> QPolygonF:
            return QPolygonF([QPointF(x_mm * self.pixels_per_mm, y_mm * self.pixels_per_mm) for x_mm, y_mm in points_mm])

        painter.save()
        try:
            painter.setOpacity(0.6)
            if self._document.layout.note_midinote_visible:
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(accent)
                painter.drawPolygon(polygon(note.body_points_mm))
            painter.setPen(QPen(accent, max(1, round(note.head_outline_width_mm * self.pixels_per_mm))))
            if self._document.layout.note_head_visible:
                if note.head.form == "cross":
                    points = polygon(note.head.points_mm)
                    painter.drawLine(points[0], points[1])
                    painter.drawLine(points[3], points[4])
                else:
                    painter.setBrush(accent if note.head.filled else paper)
                    painter.drawPolygon(polygon(note.head.points_mm))
            if self._document.layout.note_stem_visible:
                painter.setPen(QPen(accent, max(1, round(note.stem_width_mm * self.pixels_per_mm))))
                painter.drawLine(
                    QPointF(note.stem[0] * self.pixels_per_mm, note.stem[1] * self.pixels_per_mm),
                    QPointF(note.stem[2] * self.pixels_per_mm, note.stem[3] * self.pixels_per_mm),
                )
            if self._document.layout.note_stop_visible and note.stop_points_mm is not None:
                painter.setPen(QPen(accent, max(1, round(note.stop_width_mm * self.pixels_per_mm))))
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawPolyline(polygon(note.stop_points_mm))
            if self._document.layout.note_continuation_dot_visible:
                dot_diameter_mm = self._document.layout.engraving_mm(self._document.layout.note_continuation_dot_size_mm, stave.scale)
                radius_px = dot_diameter_mm * self.pixels_per_mm * 0.5
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(accent)
                for x_mm, y_mm in note.continuation_dot_centres_mm:
                    painter.drawEllipse(QPointF(x_mm * self.pixels_per_mm, y_mm * self.pixels_per_mm), radius_px, radius_px)
        finally:
            painter.restore()

    def _draw_slur_handle_overlay(self, painter: QPainter, exposed_rect: QRect) -> None:
        """Draw the four direct-manipulation handles for each editable slur."""
        accent = self.palette().color(QPalette.ColorRole.Highlight)
        handle_size_px = max(6, round(self.pixels_per_mm * 2.5))
        handle_rect = QRectF(-handle_size_px * 0.5, -handle_size_px * 0.5, handle_size_px, handle_size_px)
        painter.save()
        try:
            painter.setOpacity(0.85)
            preview_points = self._slur_tool.drag_preview_points
            if preview_points is not None:
                path = QPainterPath(QPointF(preview_points[0][0] * self.pixels_per_mm, preview_points[0][1] * self.pixels_per_mm))
                path.cubicTo(
                    QPointF(preview_points[1][0] * self.pixels_per_mm, preview_points[1][1] * self.pixels_per_mm),
                    QPointF(preview_points[2][0] * self.pixels_per_mm, preview_points[2][1] * self.pixels_per_mm),
                    QPointF(preview_points[3][0] * self.pixels_per_mm, preview_points[3][1] * self.pixels_per_mm),
                )
                preview_stave = self._slur_tool._edit.stave
                overlay_width_mm = self._document.layout.engraving_mm(
                    self._document.layout.slur_width_middle_mm,
                    preview_stave.scale,
                )
                overlay_pen = QPen(accent, max(1, round(self.pixels_per_mm * overlay_width_mm)))
                overlay_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
                painter.setPen(overlay_pen)
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawPath(path)
            painter.setPen(QPen(accent, max(1, round(self.pixels_per_mm * 0.35)), Qt.PenStyle.DashLine))
            for (start, first_control, second_control, end), in self._slur_tool.visible_handles():
                points = tuple(QPointF(x_mm * self.pixels_per_mm, y_mm * self.pixels_per_mm) for x_mm, y_mm in (start, first_control, second_control, end))
                if not any(QRectF(point + QPointF(handle_rect.left(), handle_rect.top()), handle_rect.size()).intersects(QRectF(exposed_rect)) for point in points):
                    continue
                painter.drawLine(points[0], points[1])
                painter.drawLine(points[2], points[3])
                painter.setPen(QPen(accent, max(1, round(self.pixels_per_mm * 0.35))))
                handle_fill = QColor.fromRgbF(*self.PAPER_COLOR)
                handle_fill.setAlpha(64)
                painter.setBrush(handle_fill)
                for point in points:
                    painter.save()
                    painter.translate(point)
                    painter.drawRect(handle_rect)
                    painter.restore()
                painter.setPen(QPen(accent, max(1, round(self.pixels_per_mm * 0.35)), Qt.PenStyle.DashLine))
        finally:
            painter.restore()

    def _draw_duration_preview(self, painter: QPainter, edit) -> None:
        """Draw a resize-only note body without rebuilding beams or continuation dots."""
        duration_target = edit.pending_duration_target
        if duration_target is None:
            return
        final_system, end_time = duration_target
        systems = [system for page in self._document.pages for system in page.systems]
        first_index = systems.index(edit.system)
        final_index = systems.index(final_system)
        if final_index < first_index:
            return
        stave_index = edit.system.staves.index(edit.stave)
        accent = self.palette().color(QPalette.ColorRole.Highlight)
        painter.save()
        try:
            painter.setOpacity(0.55)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(accent)
            for system in systems[first_index:final_index + 1]:
                page = next(page for page in self._document.pages if system in page.systems)
                if page is not self._current_page():
                    continue
                stave = system.staves[stave_index]
                left_mm = self._centered_stave_left_positions(
                    system,
                    StaveDrawer(None, self.INK_COLOR),
                    self._document.layout,
                    *self._system_column_bounds(page, system),
                )[stave_index]
                semitone_mm = self._document.layout.engraving_mm(2.0, stave.scale)
                x_mm = StaveDrawer.pitch_to_x_mm(edit.note.pitch, stave.pitch_range[0], left_mm, semitone_mm)
                start_time = edit.note.time if system is edit.system else system.start_tick
                final_time = min(end_time, system.end_tick)
                if final_time <= start_time:
                    continue
                start_y_mm = self._time_to_y_mm(system, start_time)
                end_y_mm = self._time_to_y_mm(system, final_time)
                body = QPolygonF([
                    QPointF(x_mm * self.pixels_per_mm, start_y_mm * self.pixels_per_mm),
                    QPointF((x_mm - semitone_mm) * self.pixels_per_mm, (start_y_mm + semitone_mm) * self.pixels_per_mm),
                    QPointF((x_mm - semitone_mm) * self.pixels_per_mm, end_y_mm * self.pixels_per_mm),
                    QPointF((x_mm + semitone_mm) * self.pixels_per_mm, end_y_mm * self.pixels_per_mm),
                    QPointF((x_mm + semitone_mm) * self.pixels_per_mm, (start_y_mm + semitone_mm) * self.pixels_per_mm),
                ])
                painter.drawPolygon(body)
                if system is final_system:
                    painter.setPen(QPen(accent, max(1, round(self.pixels_per_mm * 0.6))))
                    painter.drawLine(
                        QPointF((x_mm - semitone_mm) * self.pixels_per_mm, end_y_mm * self.pixels_per_mm),
                        QPointF((x_mm + semitone_mm) * self.pixels_per_mm, end_y_mm * self.pixels_per_mm),
                    )
                    painter.setPen(Qt.PenStyle.NoPen)
        finally:
            painter.restore()

    def _draw_time_signature_overlay(self, painter: QPainter, exposed_rect: QRect) -> None:
        """Show every time-signature target and the available beats for one hovered measure."""
        accent = self.palette().color(QPalette.ColorRole.Highlight)
        page = self._current_page()
        measure_starts, _ = grid_boundaries(self._document.base_grid, self._document.time_per_quarter)
        hovered_measure = self._time_signature_hovered_measure()
        painter.save()
        try:
            painter.setOpacity(0.35)
            painter.setPen(QPen(accent, max(1, round(self.pixels_per_mm * 0.45))))
            for system in page.systems:
                left_mm, right_mm = self._system_column_bounds(page, system)
                for time in measure_starts:
                    if system.start_tick <= time <= system.end_tick:
                        y_px = round(self._time_to_y_mm(system, time) * self.pixels_per_mm)
                        painter.drawLine(round(left_mm * self.pixels_per_mm), y_px, round(right_mm * self.pixels_per_mm), y_px)
            if hovered_measure is None:
                return
            system, measure_start, beat_duration, numerator = hovered_measure
            left_mm, right_mm = self._system_column_bounds(page, system)
            painter.setOpacity(0.7)
            painter.setPen(QPen(accent, max(2, round(self.pixels_per_mm * 0.8))))
            for beat in range(1, numerator):
                y_mm = self._time_to_y_mm(system, measure_start + beat * beat_duration)
                if exposed_rect.top() <= y_mm * self.pixels_per_mm <= exposed_rect.bottom():
                    painter.drawLine(
                        round(left_mm * self.pixels_per_mm),
                        round(y_mm * self.pixels_per_mm),
                        round(right_mm * self.pixels_per_mm),
                        round(y_mm * self.pixels_per_mm),
                    )
        finally:
            painter.restore()

    def _draw_selection_overlay(self, painter: QPainter, exposed_rect: QRect) -> None:
        accent = self.palette().color(QPalette.ColorRole.Highlight)
        page = self._current_page()
        drawer = StaveDrawer(None, self.INK_COLOR)
        painter.save()
        try:
            painter.setOpacity(0.75)
            for system in page.systems:
                positions = self._centered_stave_left_positions(system, drawer, self._document.layout, *self._system_column_bounds(page, system))
                for stave, left_mm in zip(system.staves, positions, strict=True):
                    render_data = self._stave_render_data(system, stave, left_mm)
                    for note in render_data.notes.geometries:
                        if note.event_id not in self._selected_note_ids:
                            continue
                        bounds = QRectF(note.bounds_mm[0] * self.pixels_per_mm, note.bounds_mm[1] * self.pixels_per_mm, (note.bounds_mm[2] - note.bounds_mm[0]) * self.pixels_per_mm, (note.bounds_mm[3] - note.bounds_mm[1]) * self.pixels_per_mm)
                        if not bounds.intersects(QRectF(exposed_rect)):
                            continue
                        polygon = lambda points: QPolygonF([QPointF(x_mm * self.pixels_per_mm, y_mm * self.pixels_per_mm) for x_mm, y_mm in points])
                        painter.setPen(Qt.PenStyle.NoPen)
                        painter.setBrush(accent)
                        painter.drawPolygon(polygon(note.body_points_mm))
                        painter.setPen(QPen(accent, max(1, round(note.head_outline_width_mm * self.pixels_per_mm))))
                        painter.setBrush(accent)
                        painter.drawPolygon(polygon(note.head.points_mm))
                        painter.setPen(QPen(accent, max(1, round(note.stem_width_mm * self.pixels_per_mm))))
                        painter.drawLine(QPointF(note.stem[0] * self.pixels_per_mm, note.stem[1] * self.pixels_per_mm), QPointF(note.stem[2] * self.pixels_per_mm, note.stem[3] * self.pixels_per_mm))
            if self._selection_anchor_mm is not None and self._selection_current_mm is not None:
                rect = QRectF(self._selection_anchor_mm * self.pixels_per_mm, self._selection_current_mm * self.pixels_per_mm).normalized()
                painter.setOpacity(1.0)
                painter.setPen(QPen(accent, max(1, round(self.pixels_per_mm * 0.5)), Qt.PenStyle.DashLine))
                painter.setBrush(QColor(accent.red(), accent.green(), accent.blue(), 38))
                painter.drawRect(rect)
        finally:
            painter.restore()

    def _translated_drag_preview(self, edit) -> NoteGeometry:
        """Translate one cached note geometry for a lightweight drag overlay."""
        source = edit.preview_geometry
        if source is None or edit.original_time is None or edit.original_pitch is None:
            raise RuntimeError("Deferred note edit is missing its source geometry")
        left_mm = edit.source_left_mm if edit.source_left_mm is not None else self.stave_left_mm(edit.system, edit.stave)
        semitone_mm = self._document.layout.engraving_mm(2.0, edit.stave.scale)
        original_x_mm = StaveDrawer.pitch_to_x_mm(edit.original_pitch, edit.stave.pitch_range[0], left_mm, semitone_mm)
        preview_x_mm = StaveDrawer.pitch_to_x_mm(edit.preview_pitch, edit.stave.pitch_range[0], left_mm, semitone_mm)
        offset_x_mm = preview_x_mm - original_x_mm
        offset_y_mm = self._time_to_y_mm(edit.system, edit.preview_time) - self._time_to_y_mm(edit.system, edit.original_time)

        def point(point_mm: tuple[float, float]) -> tuple[float, float]:
            return point_mm[0] + offset_x_mm, point_mm[1] + offset_y_mm

        def line(line_mm: tuple[float, float, float, float] | None) -> tuple[float, float, float, float] | None:
            if line_mm is None:
                return None
            return line_mm[0] + offset_x_mm, line_mm[1] + offset_y_mm, line_mm[2] + offset_x_mm, line_mm[3] + offset_y_mm

        return replace(
            source,
            body_points_mm=tuple(point(value) for value in source.body_points_mm),
            head=replace(source.head, points_mm=tuple(point(value) for value in source.head.points_mm)),
            stem=line(source.stem),
            chord_connector=line(source.chord_connector),
            stop_points_mm=tuple(point(value) for value in source.stop_points_mm) if source.stop_points_mm is not None else None,
            continuation_dot_centres_mm=tuple(point(value) for value in source.continuation_dot_centres_mm),
            bounds_mm=(source.bounds_mm[0] + offset_x_mm, source.bounds_mm[1] + offset_y_mm, source.bounds_mm[2] + offset_x_mm, source.bounds_mm[3] + offset_y_mm),
            right_extent_mm=source.right_extent_mm + offset_x_mm,
        )

    def _preview_note_geometry(self, system, stave, left_mm: float) -> NoteGeometry | None:
        preview = NoteEvent(
            time=self.mouse_time,
            duration=self.input_snap_ticks,
            pitch=self.mouse_pitch,
            hand=self._note_tool.hand,
        )
        preview_stave = replace(stave, events=[*stave.events, preview])
        render_data = build_stave_render_data(
            system,
            preview_stave,
            self._document.layout,
            left_mm,
            self._measure_ticks(),
            self._document.base_grid,
        )
        return next((note for note in render_data.notes.geometries if note.event_id == preview.id), None)

    def mouseMoveEvent(self, event) -> None:
        self.update_mouse_cursor(self._point_mm(event.position()))
        if self._selection_anchor_mm is not None:
            self._selection_current_mm = self._point_mm(event.position())
            self.update()
            event.accept()
            return
        if self._left_tool_active:
            active_tool = self._tool_manager.active_tool
            if active_tool is not None:
                active_tool.on_left_drag(self._point_mm(event.position()))
        super().mouseMoveEvent(event)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.setFocus()
            measure_control = self._measure_control_at(self._point_mm(event.position()))
            if measure_control is not None:
                if measure_control == "add":
                    self._document.add_measure()
                else:
                    try:
                        self._document.remove_measure()
                    except ValueError:
                        event.accept()
                        return
                self.finish_time_signature_edit()
                self.commit_document_change()
                event.accept()
                return
            if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                point_mm = self._point_mm(event.position())
                self._selection_anchor_mm = point_mm
                self._selection_current_mm = point_mm
                self._left_tool_active = False
                event.accept()
                return
            self.update_mouse_cursor(self._point_mm(event.position()))
            control_target = self._stave_control_at(self._point_mm(event.position()))
            if control_target is not None:
                system, stave = control_target
                self._control_target = (system.id, stave.id)
                self._show_stave_menu(event.globalPosition().toPoint())
                event.accept()
                return
            note = self.note_at(self._point_mm(event.position()))
            selected_note_ids = {note[2].id} if note is not None else set()
            if selected_note_ids != self._selected_note_ids:
                self._selected_note_ids = selected_note_ids
                self.update()
            active_tool = self._tool_manager.active_tool
            self._left_tool_active = bool(active_tool and active_tool.on_left_press(self._point_mm(event.position())))
            if self._left_tool_active:
                event.accept()
                return
            event.accept()
            return
        if event.button() == Qt.MouseButton.RightButton:
            self.update_mouse_cursor(self._point_mm(event.position()))
            active_tool = self._tool_manager.active_tool
            if active_tool is not None and active_tool.on_right_click(self._point_mm(event.position())):
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self._selection_anchor_mm is not None:
            self._selection_current_mm = self._point_mm(event.position())
            self._select_notes_in_rectangle()
            self._selection_anchor_mm = None
            self._selection_current_mm = None
            self.update()
            event.accept()
            return
        if event.button() == Qt.MouseButton.LeftButton and self._left_tool_active:
            active_tool = self._tool_manager.active_tool
            if active_tool is not None:
                active_tool.on_left_release(self._point_mm(event.position()))
            self._left_tool_active = False
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_Escape:
            window = self.window()
            if window is not None:
                window.close()
                event.accept()
                return
        if event.key() == Qt.Key.Key_Z and event.modifiers() == (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier):
            if self._redo_callback is not None:
                self._redo_callback()
                event.accept()
                return
        if event.matches(QKeySequence.StandardKey.Undo):
            if self._undo_callback is not None:
                self._undo_callback()
                event.accept()
                return
        if event.key() == Qt.Key.Key_Z and event.modifiers() == Qt.KeyboardModifier.NoModifier:
            if self._undo_callback is not None:
                self._undo_callback()
                event.accept()
                return
        if event.matches(QKeySequence.StandardKey.Copy) and self.copy_selection():
            event.accept()
            return
        if event.matches(QKeySequence.StandardKey.Cut) and self.cut_selection():
            event.accept()
            return
        if event.matches(QKeySequence.StandardKey.Paste) and self.paste_selection():
            event.accept()
            return
        if event.modifiers() == Qt.KeyboardModifier.NoModifier:
            if event.key() == Qt.Key.Key_X and self.cut_selection():
                event.accept()
                return
            if event.key() == Qt.Key.Key_C and self.copy_selection():
                event.accept()
                return
            if event.key() == Qt.Key.Key_V and self.paste_selection():
                event.accept()
                return
        if event.key() in (Qt.Key.Key_BracketLeft, Qt.Key.Key_BracketRight):
            hand = "left" if event.key() == Qt.Key.Key_BracketLeft else "right"
            if self.set_selected_notes_hand(hand):
                event.accept()
                return
        if event.key() in (Qt.Key.Key_Left, Qt.Key.Key_Right):
            semitones = -1 if event.key() == Qt.Key.Key_Left else 1
            if self.transpose_selection(semitones):
                event.accept()
                return
        if event.key() in (Qt.Key.Key_Up, Qt.Key.Key_Down):
            ticks = -self.input_snap_ticks if event.key() == Qt.Key.Key_Up else self.input_snap_ticks
            if self.shift_selection_in_time(ticks):
                event.accept()
                return
        if event.key() in (Qt.Key.Key_Backspace, Qt.Key.Key_Delete) and self.delete_selection():
            event.accept()
            return
        super().keyPressEvent(event)

    def _select_notes_in_rectangle(self) -> None:
        if self._selection_anchor_mm is None or self._selection_current_mm is None:
            return
        if (self._selection_current_mm - self._selection_anchor_mm).manhattanLength() < 0.01:
            hit = self.note_at(self._selection_anchor_mm)
            self._selected_note_ids = {hit[2].id} if hit is not None else set()
            slur_hit = self._slur_tool._handle_at(self._selection_anchor_mm)
            self._selected_slur_ids = {slur_hit[2].id} if slur_hit is not None else set()
            return
        rect = QRectF(self._selection_anchor_mm, self._selection_current_mm).normalized()
        selected: set[str] = set()
        selected_slurs: set[str] = set()
        page = self._current_page()
        drawer = StaveDrawer(None, self.INK_COLOR)
        for system in page.systems:
            positions = self._centered_stave_left_positions(system, drawer, self._document.layout, *self._system_column_bounds(page, system))
            for stave, left_mm in zip(system.staves, positions, strict=True):
                for note in self._stave_render_data(system, stave, left_mm).notes.geometries:
                    bounds = QRectF(note.bounds_mm[0], note.bounds_mm[1], note.bounds_mm[2] - note.bounds_mm[0], note.bounds_mm[3] - note.bounds_mm[1])
                    if rect.intersects(bounds):
                        selected.add(note.event_id)
                for slur in (event for event in stave.events if isinstance(event, SlurEvent)):
                    points = self._slur_tool._points_mm(system, stave, left_mm, slur)
                    if any(rect.contains(QPointF(*point)) for point in points):
                        selected_slurs.add(slur.id)
        self._selected_note_ids = selected
        self._selected_slur_ids = selected_slurs

    def _selected_notes(self):
        for page in self._document.pages:
            for system in page.systems:
                for stave in system.staves:
                    for event in stave.events:
                        if isinstance(event, NoteEvent) and event.id in self._selected_note_ids:
                            yield system, stave, event

    def _selected_slurs(self):
        for page in self._document.pages:
            for system in page.systems:
                for stave in system.staves:
                    for event in stave.events:
                        if isinstance(event, SlurEvent) and event.id in self._selected_slur_ids:
                            yield system, stave, event

    def select_slur(self, slur: SlurEvent) -> None:
        """Select one slur when the user grabs any of its handles."""
        if self._selected_slur_ids != {slur.id} or self._selected_note_ids:
            self._selected_note_ids.clear()
            self._selected_slur_ids = {slur.id}
            self.update()

    def copy_selection(self) -> bool:
        self._clipboard_notes = [deepcopy(note) for _, _, note in self._selected_notes()]
        self._clipboard_slurs = [deepcopy(slur) for _, _, slur in self._selected_slurs()]
        return bool(self._clipboard_notes or self._clipboard_slurs)

    def cut_selection(self) -> bool:
        if not self.copy_selection():
            return False
        return self.delete_selection()

    def delete_selection(self) -> bool:
        """Remove selected notes without changing the clipboard."""
        if not self._selected_note_ids and not self._selected_slur_ids:
            return False
        changed = False
        for page in self._document.pages:
            for system in page.systems:
                for stave in system.staves:
                    original_count = len(stave.events)
                    stave.events[:] = [
                        event
                        for event in stave.events
                        if event.id not in self._selected_note_ids and event.id not in self._selected_slur_ids
                    ]
                    if len(stave.events) != original_count:
                        stave.touch()
                        system.touch()
                        changed = True
        if changed:
            self._selected_note_ids.clear()
            self._selected_slur_ids.clear()
            self.invalidate_render_cache()
            self.commit_document_change()
        return changed

    def paste_selection(self) -> bool:
        if (not self._clipboard_notes and not self._clipboard_slurs) or self._mouse_stave_target is None or self.mouse_time is None or self.mouse_pitch is None:
            return False
        system, stave, _ = self._mouse_stave_target
        source_time = min(
            *(note.time for note in self._clipboard_notes),
            *(tick for slur in self._clipboard_slurs for tick in (slur.y1_tick, slur.y2_tick, slur.y3_tick, slur.y4_tick)),
        )
        source_pitch = min(
            *(note.pitch for note in self._clipboard_notes),
            *(60 + rpitch for slur in self._clipboard_slurs for rpitch in (slur.x1_rpitch, slur.x2_rpitch, slur.x3_rpitch, slur.x4_rpitch)),
        )
        pasted = [deepcopy(note) for note in self._clipboard_notes]
        pasted_slurs = [deepcopy(slur) for slur in self._clipboard_slurs]
        for note in pasted:
            note.id = str(uuid4())
            note.time += self.mouse_time - source_time
            note.pitch += self.mouse_pitch - source_pitch
            if note.time < system.start_tick or note.time + note.duration > system.end_tick or not NoteTool._can_place(stave, note):
                return False
        for slur in pasted_slurs:
            slur.id = str(uuid4())
            tick_offset = int(self.mouse_time - source_time)
            pitch_offset = self.mouse_pitch - source_pitch
            for attribute in ("y1_tick", "y2_tick", "y3_tick", "y4_tick"):
                setattr(slur, attribute, getattr(slur, attribute) + tick_offset)
            for attribute in ("x1_rpitch", "x2_rpitch", "x3_rpitch", "x4_rpitch"):
                setattr(slur, attribute, getattr(slur, attribute) + pitch_offset)
            self._slur_tool._constrain_to_page(slur, system, stave, self.stave_left_mm(system, stave))
        stave.events.extend((*pasted, *pasted_slurs))
        stave.touch()
        system.touch()
        self._selected_note_ids = {note.id for note in pasted}
        self._selected_slur_ids = {slur.id for slur in pasted_slurs}
        self.invalidate_system_render_cache(system.id, stave.id)
        self.commit_document_change()
        return True

    def set_selected_notes_hand(self, hand: str) -> bool:
        if hand not in {"left", "right"}:
            raise ValueError("Note hand must be 'left' or 'right'")
        changed = False
        for system, stave, note in self._selected_notes():
            if note.hand != hand:
                note.hand = hand
                stave.touch()
                system.touch()
                changed = True
        if changed:
            self.invalidate_render_cache()
            self.commit_document_change()
        return changed

    def transpose_selection(self, semitones: int) -> bool:
        """Transpose the complete current selection by a semitone offset."""
        selected = list(self._selected_notes())
        if not selected or not semitones:
            return False
        selected_ids = {note.id for _, _, note in selected}
        candidates = [(system, stave, note, note.time, note.pitch + semitones) for system, stave, note in selected]
        if any(not 0 <= pitch <= 127 for _, _, _, _, pitch in candidates):
            return False
        if not self._selection_candidates_are_valid(candidates, selected_ids):
            return False
        ledger_layout_before = self.ledger_layout_signature()
        changed_systems: set[tuple[str, str]] = set()
        for system, stave, note, _, pitch in candidates:
            note.pitch = pitch
            stave.touch()
            system.touch()
            changed_systems.add((system.id, stave.id))
        if not self.repaginate_if_ledger_layout_changed(ledger_layout_before):
            for system_id, stave_id in changed_systems:
                self.invalidate_system_render_cache(system_id, stave_id)
        self.commit_document_change()
        return True

    def shift_selection_in_time(self, ticks: float) -> bool:
        """Move the complete current selection by an exact snap-grid duration."""
        selected = list(self._selected_notes())
        if not selected or not ticks:
            return False
        systems = [system for page in self._document.pages for system in page.systems]
        selected_ids = {note.id for _, _, note in selected}
        candidates = []
        for source_system, source_stave, note in selected:
            time = note.time + ticks
            target_system = next(
                (system for system in systems if system.start_tick <= time and time + note.duration <= system.end_tick),
                None,
            )
            if target_system is None:
                return False
            stave_index = source_system.staves.index(source_stave)
            candidates.append((target_system, target_system.staves[stave_index], note, time, note.pitch))
        if not self._selection_candidates_are_valid(candidates, selected_ids):
            return False
        ledger_layout_before = self.ledger_layout_signature()
        changed_systems: set[tuple[str, str]] = set()
        for source_system, source_stave, note in selected:
            source_stave.events.remove(note)
            source_stave.touch()
            source_system.touch()
            changed_systems.add((source_system.id, source_stave.id))
        for target_system, target_stave, note, time, _ in candidates:
            note.time = time
            target_stave.events.append(note)
            target_stave.touch()
            target_system.touch()
            changed_systems.add((target_system.id, target_stave.id))
        if not self.repaginate_if_ledger_layout_changed(ledger_layout_before):
            for system_id, stave_id in changed_systems:
                self.invalidate_system_render_cache(system_id, stave_id)
        self.commit_document_change()
        return True

    @staticmethod
    def _selection_candidates_are_valid(candidates, selected_ids: set[str]) -> bool:
        comparison = Operator(SHORTEST_DURATION)
        for target_system, target_stave, note, time, pitch in candidates:
            for event in target_stave.events:
                if not isinstance(event, NoteEvent) or event.id in selected_ids:
                    continue
                if event.hand != note.hand or event.pitch != pitch:
                    continue
                if comparison.lt(time, event.time + event.duration) and comparison.lt(event.time, time + note.duration):
                    return False
        for index, (_, first_stave, first_note, first_time, first_pitch) in enumerate(candidates):
            for _, second_stave, second_note, second_time, second_pitch in candidates[index + 1:]:
                if first_stave is not second_stave or first_note.hand != second_note.hand or first_pitch != second_pitch:
                    continue
                if comparison.lt(first_time, second_time + second_note.duration) and comparison.lt(second_time, first_time + first_note.duration):
                    return False
        return True

    def system_break_target_at(self, point_mm: QPointF):
        """Resolve a split barline or a removable top/bottom system edge."""
        tolerance_mm = self.BARLINE_HIT_TOLERANCE_PX / self.pixels_per_mm
        measure_starts, _ = grid_boundaries(self._document.base_grid, self._document.time_per_quarter)
        page = self._current_page()
        for system in page.systems:
            left_mm, right_mm = self._system_column_bounds(page, system)
            if not left_mm - tolerance_mm <= point_mm.x() <= right_mm + tolerance_mm:
                continue
            if abs(point_mm.y() - self._time_to_y_mm(system, system.start_tick)) <= tolerance_mm and self._has_adjacent_system(system, "top"):
                return ("remove", system, "top")
            if abs(point_mm.y() - self._time_to_y_mm(system, system.end_tick)) <= tolerance_mm and self._has_adjacent_system(system, "bottom"):
                return ("remove", system, "bottom")
            for time in measure_starts:
                if system.start_tick < time < system.end_tick and abs(self._time_to_y_mm(system, time) - point_mm.y()) <= tolerance_mm:
                    return ("split", system, time)
        return None

    def time_signature_target_at(self, point_mm: QPointF):
        tolerance_mm = self.BARLINE_HIT_TOLERANCE_PX / self.pixels_per_mm
        measure_starts, _ = grid_boundaries(self._document.base_grid, self._document.time_per_quarter)
        grid_starts = []
        segment_start = 0
        for segment in self._document.base_grid:
            beat_duration = segment.beat_duration(self._document.time_per_quarter)
            grid_starts.extend(segment_start + beat * beat_duration for beat in range(1, segment.numerator))
            segment_start += segment.measure_amount * segment.measure_duration(self._document.time_per_quarter)
        page = self._current_page()
        for system in page.systems:
            left_mm, right_mm = self._system_column_bounds(page, system)
            if not left_mm - tolerance_mm <= point_mm.x() <= right_mm + tolerance_mm:
                continue
            for time in measure_starts:
                if system.start_tick <= time <= system.end_tick and abs(self._time_to_y_mm(system, time) - point_mm.y()) <= tolerance_mm:
                    return "barline", time
            for time in grid_starts:
                if system.start_tick < time < system.end_tick and abs(self._time_to_y_mm(system, time) - point_mm.y()) <= tolerance_mm:
                    return "grid", time
        return None

    def _time_signature_hovered_measure(self):
        """Return the meter details for the measure selected by a hovered barline."""
        if self._last_mouse_position_mm is None:
            return None
        target = self.time_signature_target_at(self._last_mouse_position_mm)
        if target is None or target[0] != "barline":
            return None
        _, measure_start = target
        try:
            segment_index, _ = self._document._time_signature_segment_containing(measure_start)
        except ValueError:
            return None
        segment = self._document.base_grid[segment_index]
        system = next(
            (
                candidate
                for candidate in self._current_page().systems
                if candidate.start_tick <= measure_start and measure_start + segment.measure_duration(self._document.time_per_quarter) <= candidate.end_tick
            ),
            None,
        )
        if system is None:
            return None
        return system, measure_start, segment.beat_duration(self._document.time_per_quarter), segment.numerator

    def _measure_control_at(self, point_mm: QPointF) -> str | None:
        systems = [system for page in self._document.pages for system in page.systems]
        final_system = systems[-1]
        page = self._current_page()
        if final_system not in page.systems:
            return None
        left_mm, right_mm = self._system_column_bounds(page, final_system)
        centre_x_mm = (left_mm + right_mm) * 0.5
        centre_y_mm = final_system.top_mm + final_system.height_mm + self.ADD_MEASURE_CONTROL_GAP_MM + self.ADD_MEASURE_CONTROL_SIZE_MM * 0.5
        half_size_mm = self.ADD_MEASURE_CONTROL_SIZE_MM * 0.5
        offset_mm = half_size_mm + self.ADD_MEASURE_CONTROL_GAP_MM * 0.5
        for kind, control_x_mm in (("add", centre_x_mm - offset_mm), ("remove", centre_x_mm + offset_mm)):
            if abs(point_mm.x() - control_x_mm) <= half_size_mm and abs(point_mm.y() - centre_y_mm) <= half_size_mm:
                return kind
        return None

    def _system_break_highlight_geometry(self) -> tuple[float, float, float] | None:
        if self._last_mouse_position_mm is None:
            return None
        target = self.system_break_target_at(self._last_mouse_position_mm)
        if target is None:
            return None
        _, system, value = target
        page = self._current_page()
        left_mm, right_mm = self._system_column_bounds(page, system)
        tick = value if isinstance(value, int) else (system.start_tick if value == "top" else system.end_tick)
        return left_mm, right_mm, self._time_to_y_mm(system, tick)

    def finish_system_break_edit(self) -> None:
        self.invalidate_render_cache()
        self._page_index = min(self._page_index, self.page_count - 1)
        self._update_size()

    def finish_time_signature_edit(self) -> None:
        self.invalidate_render_cache()
        self._page_index = min(self._page_index, self.page_count - 1)
        self._update_size()

    def repaginate_document(self) -> None:
        """Repack pages after a committed edit changes stave geometry."""
        self._document.repaginate_document()
        self.invalidate_render_cache()
        self._page_index = min(self._page_index, self.page_count - 1)
        self._update_size()

    def _has_adjacent_system(self, system, boundary: str) -> bool:
        systems = [candidate for page in self._document.pages for candidate in page.systems]
        index = systems.index(system)
        return index > 0 if boundary == "top" else index < len(systems) - 1

    @staticmethod
    def _time_to_y_mm(system, time: int) -> float:
        return system.top_mm + (time - system.start_tick) * system.height_mm / (system.end_tick - system.start_tick)

    def select_note_hand(self, hand: str) -> None:
        """Activate note input and set the hand used for newly created notes."""
        note_tool = self._tool_manager.activate(NoteTool.TOOL_NAME)
        if not isinstance(note_tool, NoteTool):
            raise RuntimeError("Registered note tool has an unexpected type")
        note_tool.set_hand(hand)
        self.note_hand_changed.emit(hand)
        self.update()

    def select_system_break_mode(self) -> None:
        self._tool_manager.activate(SystemBreakTool.TOOL_NAME)
        self.update()

    def select_time_signature_mode(self) -> None:
        self._tool_manager.activate(TimeSignatureTool.TOOL_NAME)
        self.update()

    def select_slur_mode(self, hand: str = "left") -> None:
        slur_tool = self._tool_manager.activate(SlurTool.TOOL_NAME)
        if not isinstance(slur_tool, SlurTool):
            raise RuntimeError("Registered slur tool has an unexpected type")
        slur_tool.set_hand(hand)
        self.update()

    def set_input_snap_ticks(self, snap_ticks: float) -> None:
        self.input_snap_ticks = max(float(SHORTEST_DURATION), float(snap_ticks))
        self._tile_cache.clear()
        if self._mouse_stave_target is not None:
            system, _, _ = self._mouse_stave_target
            self.mouse_time = self.snap_time(system, self._last_mouse_y_mm, self.input_snap_ticks)
        self.update()
        self.update()

    def set_snap_band_visible(self, visible: bool) -> None:
        self._document.layout.grid_band_visible = visible
        self._tile_cache.clear()
        self.update()
        self.commit_document_change()

    def stave_at(
        self,
        point_mm: QPointF,
        allow_outside_range: bool = False,
        include_ledger_bounds: bool = True,
    ):
        """Return the system, stave, and stave origin under one paper point."""
        page = self._current_page()
        drawer = StaveDrawer(None, self.INK_COLOR)
        for system in page.systems:
            if not system.top_mm <= point_mm.y() <= system.top_mm + system.height_mm:
                continue
            positions = self._centered_stave_left_positions(system, drawer, self._document.layout, *self._system_column_bounds(page, system))
            for stave, left_mm in zip(system.staves, positions, strict=True):
                if include_ledger_bounds:
                    bounds = drawer.bounds(stave, self._document.layout, left_mm, system)
                else:
                    semitone_mm = self._document.layout.engraving_mm(2.0, stave.scale)
                    low_x_mm = StaveDrawer.pitch_to_x_mm(stave.pitch_range[0], stave.pitch_range[0], left_mm, semitone_mm)
                    high_x_mm = StaveDrawer.pitch_to_x_mm(stave.pitch_range[1], stave.pitch_range[0], left_mm, semitone_mm)
                    bounds = low_x_mm - semitone_mm * 0.5, high_x_mm + semitone_mm * 0.5
                if bounds is not None and bounds[0] <= point_mm.x() <= bounds[1]:
                    return system, stave, left_mm
            if allow_outside_range:
                candidates = []
                for stave, left_mm in zip(system.staves, positions, strict=True):
                    semitone_mm = self._document.layout.engraving_mm(2.0, stave.scale)
                    low_x_mm = StaveDrawer.pitch_to_x_mm(0, stave.pitch_range[0], left_mm, semitone_mm)
                    high_x_mm = StaveDrawer.pitch_to_x_mm(127, stave.pitch_range[0], left_mm, semitone_mm)
                    if low_x_mm - semitone_mm <= point_mm.x() <= high_x_mm + semitone_mm:
                        pitch = self.pitch_at(stave, left_mm, point_mm.x(), allow_outside_range=True)
                        pitch_x_mm = StaveDrawer.pitch_to_x_mm(pitch, stave.pitch_range[0], left_mm, semitone_mm)
                        candidates.append((abs(point_mm.x() - pitch_x_mm), stave, left_mm))
                if candidates:
                    _, stave, left_mm = min(candidates, key=lambda candidate: candidate[0])
                    return system, stave, left_mm
        return None

    def stave_left_mm(self, system, stave) -> float:
        page = self._current_page()
        drawer = StaveDrawer(None, self.INK_COLOR)
        positions = self._centered_stave_left_positions(system, drawer, self._document.layout, *self._system_column_bounds(page, system))
        return positions[system.staves.index(stave)]

    def pitch_at(self, stave, left_mm: float, x_mm: float, allow_outside_range: bool = False) -> int:
        semitone_mm = self._document.layout.engraving_mm(2.0, stave.scale)
        low_pitch, high_pitch = (0, 127) if allow_outside_range else stave.pitch_range
        return min(
            range(low_pitch, high_pitch + 1),
            key=lambda pitch: abs(StaveDrawer.pitch_to_x_mm(pitch, stave.pitch_range[0], left_mm, semitone_mm) - x_mm),
        )

    def snap_time(self, system, y_mm: float, snap_ticks: float, reserved_duration: float = 0.0) -> float:
        raw_time = system.start_tick + (y_mm - system.top_mm) * (system.end_tick - system.start_tick) / system.height_mm
        snapped = round(raw_time / snap_ticks) * snap_ticks
        return max(system.start_tick, min(system.end_tick - reserved_duration, snapped))

    def note_at(self, point_mm: QPointF):
        """Return the note and its cached geometry under one paper point."""
        page = self._current_page()
        drawer = StaveDrawer(None, self.INK_COLOR)
        for system in page.systems:
            positions = self._centered_stave_left_positions(system, drawer, self._document.layout, *self._system_column_bounds(page, system))
            for stave, left_mm in zip(system.staves, positions, strict=True):
                render_data = self._stave_render_data(system, stave, left_mm)
                hit = render_data.hit_test(point_mm.x(), point_mm.y())
                if hit is None:
                    continue
                event_id, part = hit
                note = next((event for event in stave.events if event.id == event_id), None)
                geometry = next((item for item in render_data.notes.geometries if item.event_id == event_id), None)
                if note is not None and geometry is not None:
                    return system, stave, note, geometry, part
        return None

    def note_at_mouse_cursor(self):
        """Return the exact note at the snapped time/pitch cursor, including clusters."""
        if self._mouse_stave_target is None or self.mouse_time is None or self.mouse_pitch is None:
            return None
        system, stave, _ = self._mouse_stave_target
        comparison = Operator(SHORTEST_DURATION)
        for event in reversed(stave.events):
            if getattr(event, "type", None) == "note" and event.pitch == self.mouse_pitch and comparison.ge(self.mouse_time, event.time) and comparison.lt(self.mouse_time, event.time + event.duration):
                return system, stave, event
        return None

    def _point_mm(self, point: QPointF) -> QPointF:
        return QPointF(point.x() / self.pixels_per_mm, point.y() / self.pixels_per_mm)

    def update_mouse_cursor(self, point_mm: QPointF) -> None:
        if self._last_mouse_position_mm is not None and self._last_mouse_position_mm == point_mm:
            return
        self._last_mouse_position_mm = QPointF(point_mm)
        self._last_mouse_y_mm = point_mm.y()
        allow_outside_range = False
        target = self.stave_at(point_mm, allow_outside_range=allow_outside_range, include_ledger_bounds=False)
        self._mouse_stave_target = target
        if target is None:
            self.mouse_time = None
            self.mouse_pitch = None
        else:
            system, stave, left_mm = target
            self.mouse_time = self.snap_time(system, point_mm.y(), self.input_snap_ticks)
            self.mouse_pitch = self.pitch_at(stave, left_mm, point_mm.x(), allow_outside_range=allow_outside_range)
        self.update()

    def _stave_control_at(self, point_mm: QPointF):
        page = self._current_page()
        drawer = StaveDrawer(None, self.INK_COLOR)
        for system in page.systems:
            positions = self._centered_stave_left_positions(system, drawer, self._document.layout, *self._system_column_bounds(page, system))
            for stave, left_mm in zip(system.staves, positions, strict=True):
                centre_x_mm, centre_y_mm = self._stave_control_centre(system, stave, left_mm)
                half_size_mm = self.STAVE_CONTROL_SIZE_MM * 0.5
                if abs(point_mm.x() - centre_x_mm) <= half_size_mm and abs(point_mm.y() - centre_y_mm) <= half_size_mm:
                    return system, stave
        return None

    def _stave_control_centre(self, system, stave, left_mm: float) -> tuple[float, float]:
        bounds = StaveDrawer(None, self.INK_COLOR).bounds(stave, self._document.layout, left_mm)
        if bounds is None:
            centre_x_mm = left_mm
        else:
            centre_x_mm = (bounds[0] + bounds[1]) * 0.5
        return (
            centre_x_mm,
            system.top_mm - self.STAVE_CONTROL_GAP_MM - self.STAVE_CONTROL_SIZE_MM * 0.5,
        )

    def _show_stave_menu(self, position: QPoint | None = None) -> None:
        if self._control_target is None:
            return
        menu = QMenu(self)
        staves_action = QAction("Configure Staves...", menu)
        scale_action = QAction("Set Stave Scale", menu)
        range_action = QAction("Set Stave Range", menu)
        staves_action.triggered.connect(self._configure_staves)
        scale_action.triggered.connect(self._set_stave_scale)
        range_action.triggered.connect(self._set_stave_range)
        menu.addAction(staves_action)
        menu.addSeparator()
        menu.addAction(scale_action)
        menu.addAction(range_action)
        menu.exec(position or QCursor.pos())

    def _set_stave_scale(self) -> None:
        target = self._control_target
        if target is None:
            return
        system = self._system_by_id(target[0])
        stave = next((candidate for candidate in system.staves if candidate.id == target[1]), None) if system else None
        if stave is None:
            return
        scale, accepted = QInputDialog.getDouble(self, "Set Stave Scale", "Stave scale", stave.scale, 0.1, 4.0, 2)
        if accepted:
            self._apply_stave_scale(system, stave, scale)

    def _apply_stave_scale(self, system, stave: Stave, scale: float) -> None:
        """Apply a local scale to one stave without changing its siblings."""
        if stave not in system.staves:
            raise ValueError("Stave does not belong to the target system")
        stave.scale = scale
        stave.touch()
        system.touch()
        self._document.repaginate_document()
        self.invalidate_render_cache(stave.id)
        self._page_index = min(self._page_index, self.page_count - 1)
        self._update_size()
        self.commit_document_change()

    def _configure_staves(self) -> None:
        target = self._control_target
        system = self._system_by_id(target[0]) if target is not None else None
        if system is None:
            return
        dialog = StavesDialog(system.staves, self)
        if dialog.exec() != dialog.DialogCode.Accepted:
            return
        self._apply_stave_configuration(system.staves, dialog.staves)

    def _apply_stave_configuration(self, source_staves, configured_staves) -> None:
        """Apply a template's stave order and settings to every document system."""
        source_indices = {stave.id: index for index, stave in enumerate(source_staves)}
        for page in self._document.pages:
            for candidate_system in page.systems:
                existing_staves = candidate_system.staves
                reordered_staves = []
                for configured_stave in configured_staves:
                    source_index = source_indices.get(configured_stave.id)
                    if source_index is None:
                        reordered_staves.append(Stave(
                            name=configured_stave.name,
                            pitch_range=list(configured_stave.pitch_range),
                            scale=configured_stave.scale,
                        ))
                        continue
                    stave = existing_staves[source_index]
                    stave.name = configured_stave.name
                    stave.pitch_range = list(configured_stave.pitch_range)
                    stave.scale = configured_stave.scale
                    stave.touch()
                    reordered_staves.append(stave)
                candidate_system.staves = reordered_staves
                candidate_system.touch()
        self._document.repaginate_document()
        self.invalidate_render_cache()
        self._page_index = min(self._page_index, self.page_count - 1)
        self._update_size()
        self.commit_document_change()

    def _set_stave_range(self) -> None:
        target = self._control_target
        if target is None:
            return
        system = self._system_by_id(target[0])
        stave = next((stave for stave in system.staves if stave.id == target[1]), None) if system else None
        if stave is None:
            return
        dialog = StaveRangeDialog(stave, self)
        if dialog.exec() == dialog.DialogCode.Accepted:
            stave.pitch_range = dialog.pitch_range
            stave.touch()
            self._document.repaginate_document()
            self.invalidate_render_cache(stave.id)
            self._page_index = min(self._page_index, self.page_count - 1)
            self._update_size()
            self.commit_document_change()

    def _system_by_id(self, system_id: str):
        return next((system for system in self._current_page().systems if system.id == system_id), None)

    def _current_page(self):
        return self._document.pages[self._page_index]

    @staticmethod
    def _centered_stave_left_positions(system, stave_drawer: StaveDrawer, layout, left_limit_mm: float, right_limit_mm: float) -> list[float]:
        """Center every fixed-width stave group inside one system's margins."""
        bounds = [stave_drawer.bounds(stave, layout, 0.0, system) for stave in system.staves]
        visual_bounds = [bound for bound in bounds if bound is not None]
        if not visual_bounds:
            return [(left_limit_mm + right_limit_mm) * 0.5] * len(system.staves)
        widths = [right_mm - left_mm for left_mm, right_mm in visual_bounds]
        group_width_mm = sum(widths) + PaperCanvas.STAVE_GAP_MM * (len(widths) - 1)
        cursor_mm = left_limit_mm + (right_limit_mm - left_limit_mm - group_width_mm) * 0.5
        left_positions: list[float] = []
        for bound in bounds:
            if bound is None:
                left_positions.append(cursor_mm)
                continue
            first_x_mm, last_x_mm = bound
            left_positions.append(cursor_mm - first_x_mm)
            cursor_mm += last_x_mm - first_x_mm + PaperCanvas.STAVE_GAP_MM
        return left_positions

    def _system_column_bounds(self, page, system) -> tuple[float, float]:
        """Return cached ledger-aware stave bounds for one system on a page."""
        system_ids = tuple(candidate.id for candidate in page.systems)
        cached = self._page_system_bounds_cache.get(page.id)
        if cached is None or cached[0] != system_ids:
            page_bounds = self._build_page_system_bounds(page)
            self._page_system_bounds_cache[page.id] = (system_ids, page_bounds)
        else:
            page_bounds = cached[1]
        return page_bounds[system.id]

    def _build_page_system_bounds(self, page) -> dict[str, tuple[float, float]]:
        """Allocate ledger-aware system widths with equal gaps across a page."""
        available_left = self._document.layout.page_left_margin_mm
        available_width = page.width_mm - available_left - self._document.layout.page_right_margin_mm
        footprints = [self._document._system_required_width_mm(system) for system in page.systems]
        required_width = sum(footprints)
        if required_width > available_width:
            column_width = available_width / len(page.systems)
            return {
                system.id: (
                    available_left + index * column_width + system.left_margin_mm,
                    available_left + (index + 1) * column_width - system.right_margin_mm,
                )
                for index, system in enumerate(page.systems)
            }
        gap_width = (available_width - required_width) / (len(page.systems) + 1)
        cursor_mm = available_left + gap_width
        bounds: dict[str, tuple[float, float]] = {}
        for system, footprint_width in zip(page.systems, footprints, strict=True):
            left_mm = cursor_mm + system.left_margin_mm
            right_mm = cursor_mm + footprint_width - system.right_margin_mm
            if right_mm <= left_mm:
                raise ValueError("System margins leave no stave space")
            bounds[system.id] = (left_mm, right_mm)
            cursor_mm += footprint_width + gap_width
        return bounds

    def _system_pixel_rect(self, page, system) -> QRect:
        """Return the tile-dirty rectangle for all drawing owned by one system."""
        left_mm, right_mm, top_mm, bottom_mm = self._system_render_bounds(page, system, include_editor_controls=True)
        bleed_px = self.TILE_BLEED_PX
        left_px = max(0, math.floor(left_mm * self.pixels_per_mm) - bleed_px)
        right_px = min(self.width(), math.ceil(right_mm * self.pixels_per_mm) + bleed_px)
        top_px = max(0, math.floor(top_mm * self.pixels_per_mm) - bleed_px)
        bottom_px = min(self.height(), math.ceil(bottom_mm * self.pixels_per_mm) + bleed_px)
        return QRect(left_px, top_px, max(1, right_px - left_px), max(1, bottom_px - top_px))

    def _system_render_bounds(self, page, system, include_editor_controls: bool) -> tuple[float, float, float, float]:
        """Return all visible system geometry, including notation and measure labels."""
        left_mm, right_mm = self._system_column_bounds(page, system)
        bounds_drawer = StaveDrawer(None, self.INK_COLOR)
        stave_left_positions = self._centered_stave_left_positions(
            system,
            bounds_drawer,
            self._document.layout,
            left_mm,
            right_mm,
        )
        notation_right_mm = right_mm
        top_mm = system.top_mm
        bottom_mm = system.top_mm + system.height_mm
        for stave, stave_left_mm in zip(system.staves, stave_left_positions, strict=True):
            render_data = self._stave_render_data(system, stave, stave_left_mm)
            geometries = (*render_data.notes.geometries, *render_data.beams.geometries)
            if geometries:
                left_mm = min(left_mm, *(geometry.bounds_mm[0] for geometry in geometries))
                notation_right_mm = max(notation_right_mm, *(geometry.right_extent_mm for geometry in geometries))
            if self._document.layout.slur_visible:
                semitone_mm = self._document.layout.engraving_mm(2.0, stave.scale)
                for slur in (event for event in stave.events if isinstance(event, SlurEvent)):
                    for rpitch, tick in (
                        (slur.x1_rpitch, slur.y1_tick),
                        (slur.x2_rpitch, slur.y2_tick),
                        (slur.x3_rpitch, slur.y3_tick),
                        (slur.x4_rpitch, slur.y4_tick),
                    ):
                        x_mm = StaveDrawer.pitch_to_x_mm(60 + rpitch, stave.pitch_range[0], stave_left_mm, semitone_mm)
                        y_mm = self._time_to_y_mm(system, tick)
                        left_mm = min(left_mm, max(0.0, x_mm))
                        notation_right_mm = max(notation_right_mm, min(page.width_mm, x_mm))
                        top_mm = min(top_mm, max(0.0, y_mm))
                        bottom_mm = max(bottom_mm, min(page.height_mm, y_mm))
        if self._document.layout.measure_numbers_visible and system.staves:
            largest_scale = max(stave.scale for stave in system.staves)
            metrics = SystemMetrics.from_layout(self._document.layout, largest_scale)
            number_size_mm = self._document.layout.engraving_pt_to_mm(
                self._document.layout.measure_numbering_font.size_pt,
                largest_scale,
            )
            right_mm = notation_right_mm + metrics.measure_number_offset_mm + number_size_mm * 8.0
        else:
            right_mm = notation_right_mm
        if self._document.layout.time_signature_visible and system.staves:
            stave_scale = system.staves[0].scale
            scale = self._document.layout.engraving_scale(stave_scale)
            left_mm -= self._document.layout.engraving_mm(
                self._document.layout.time_signature_indicator_lane_width_mm,
                stave_scale,
            ) + 1.5 * scale
            top_mm -= max(
                self._document.layout.engraving_pt_to_mm(self._document.layout.time_signature_indicator_classic_font.size_pt, stave_scale),
                self._document.layout.engraving_pt_to_mm(self._document.layout.time_signature_indicator_klavarskribo_font.size_pt, stave_scale),
            ) + 2.0 * scale
        if include_editor_controls:
            top_mm = min(top_mm, system.top_mm - self.STAVE_CONTROL_GAP_MM - self.STAVE_CONTROL_SIZE_MM)
            final_system = [candidate for document_page in self._document.pages for candidate in document_page.systems][-1]
            if system is final_system:
                bottom_mm = max(bottom_mm, system.top_mm + system.height_mm + self.ADD_MEASURE_CONTROL_GAP_MM + self.ADD_MEASURE_CONTROL_SIZE_MM)
        return left_mm, right_mm, top_mm, bottom_mm

    def _measure_ticks(self) -> int:
        return self._document.time_per_quarter * 4
