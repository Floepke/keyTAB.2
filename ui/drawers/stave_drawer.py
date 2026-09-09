"""Bounded black-key Klavarskribo stave drawing."""

from __future__ import annotations

from keytab2_model.document import PIANO_HIGH_MIDI_PITCH, PIANO_LOW_MIDI_PITCH, NoteEvent, Stave, System
from keytab2_model.layout import Layout
from ui.drawers.base import DrawerBase


class StaveDrawer(DrawerBase):
    """Draw the two-/three-line black-key groups for one bounded stave."""

    BLACK_PITCH_CLASSES = {1, 3, 6, 8, 10}
    CLEF_KEY_NUMBERS = {41, 43}
    THREE_LINE_KEY_CLASSES = {1, 9, 11}
    EXTRA_GAP_AFTER_PITCH_CLASSES = {4, 11}
    MIDI_ONLY_LEDGER_COLOR = (0.62, 0.62, 0.62)

    @classmethod
    def pitch_to_x_mm(cls, midi_pitch: int, range_low: int, left_mm: float, semitone_mm: float) -> float:
        """Map a MIDI pitch to Klavarskribo x, adding a second space after E and B."""
        return left_mm + Stave.pitch_offset_units(midi_pitch, range_low) * semitone_mm

    @staticmethod
    def effective_scale(layout: Layout, stave: Stave) -> float:
        return layout.engraving_scale(stave.scale)

    def _line_style(self, pitch: int, layout: Layout, effective_scale: float) -> tuple[float, list[float], tuple[float, float, float] | None]:
        if pitch == PIANO_LOW_MIDI_PITCH + 1:
            return layout.stave_three_line_thickness_mm * effective_scale, [], None
        key_number = pitch - 20
        if key_number in self.CLEF_KEY_NUMBERS:
            return (
                layout.stave_clef_line_thickness_mm * effective_scale,
                [value * effective_scale for value in layout.stave_clef_line_dash_pattern_mm],
                None,
            )
        if (key_number - 1) % 12 in self.THREE_LINE_KEY_CLASSES:
            return layout.stave_three_line_thickness_mm * effective_scale, [], None
        return layout.stave_two_line_thickness_mm * effective_scale, [], None

    @staticmethod
    def _ledger_color(pitch: int) -> tuple[float, float, float] | None:
        return None if PIANO_LOW_MIDI_PITCH <= pitch <= PIANO_HIGH_MIDI_PITCH else StaveDrawer.MIDI_ONLY_LEDGER_COLOR

    def bounds(self, stave: Stave, layout: Layout, left_mm: float, system: System | None = None) -> tuple[float, float] | None:
        low_pitch, high_pitch = stave.pitch_range
        black_pitches = stave.line_pitches(system)
        if not black_pitches:
            return None
        semitone_mm = 2.0 * self.effective_scale(layout, stave)
        return (
            self.pitch_to_x_mm(black_pitches[0], low_pitch, left_mm, semitone_mm),
            self.pitch_to_x_mm(black_pitches[-1], low_pitch, left_mm, semitone_mm),
        )

    def draw(
        self,
        system: System,
        stave: Stave,
        layout: Layout,
        left_mm: float,
        continuation_dot_centres: dict[str, tuple[tuple[float, float], ...]] | None = None,
        stop_centres: dict[str, tuple[float, float]] | None = None,
        include_midi_only_ledgers: bool = True,
    ) -> None:
        low_pitch, high_pitch = stave.pitch_range
        black_pitches = stave.natural_line_pitches()
        if not black_pitches:
            return

        effective_scale = self.effective_scale(layout, stave)
        semitone_mm = 2.0 * effective_scale
        top_mm = system.top_mm
        bottom_mm = top_mm + system.height_mm
        for pitch in black_pitches:
            x_mm = self.pitch_to_x_mm(pitch, low_pitch, left_mm, semitone_mm)
            line_width, dash_pattern, color = self._line_style(pitch, layout, effective_scale)
            self.draw_line(x_mm, top_mm, x_mm, bottom_mm, line_width, dash_pattern_mm=dash_pattern, tags=("stave_line",))

        ledger_length_mm = layout.stave_ledger_line_length_mm * effective_scale
        drawn_ledgers: set[tuple[int, float]] = set()
        for event in stave.events:
            if not isinstance(event, NoteEvent) or event.time >= system.end_tick or event.time + event.duration <= system.start_tick:
                continue
            start_y_mm = system.top_mm + (max(event.time, system.start_tick) - system.start_tick) * system.height_mm / (system.end_tick - system.start_tick)
            dot_centres = continuation_dot_centres.get(event.id, ()) if continuation_dot_centres else ()
            stop_centre = stop_centres.get(event.id) if stop_centres else None
            for _, y_center_mm in ((0.0, start_y_mm + semitone_mm), *dot_centres, *((stop_centre,) if stop_centre else ())):
                for pitch in stave.ledger_line_pitches_for_pitch(event.pitch):
                    if not include_midi_only_ledgers and self._ledger_color(pitch) is not None:
                        continue
                    signature = (pitch, y_center_mm)
                    if signature in drawn_ledgers:
                        continue
                    drawn_ledgers.add(signature)
                    x_mm = self.pitch_to_x_mm(pitch, low_pitch, left_mm, semitone_mm)
                    line_width, dash_pattern, _ = self._line_style(pitch, layout, effective_scale)
                    self.draw_line(
                        x_mm,
                        y_center_mm - 3.0 * semitone_mm,
                        x_mm,
                        y_center_mm - 3.0 * semitone_mm + ledger_length_mm,
                        line_width,
                        color=self._ledger_color(pitch),
                        dash_pattern_mm=dash_pattern,
                        tags=("stave_line",),
                    )
