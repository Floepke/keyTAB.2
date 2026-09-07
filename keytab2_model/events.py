"""Typed, discriminated events persisted by the keyTAB2 document model."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4


def _new_id() -> str:
    return str(uuid4())


@dataclass
class Event:
    id: str = field(default_factory=_new_id)


@dataclass
class NoteEvent(Event):
    time: int = 0
    duration: int = 100
    pitch: int = 40
    velocity: int = 64
    hand: str = "left"
    notehead: str = "auto"
    color: str = "auto"
    acc: int = 0
    continuation_id: str | None = None
    continues_from_previous: bool = False
    continues_to_next: bool = False
    type: str = field(default="note", init=False)


@dataclass
class GraceNoteEvent(Event):
    start_tick: int = 50
    pitch: int = 41
    notehead: str = "auto"
    type: str = field(default="grace_note", init=False)


@dataclass
class PedalEvent(Event):
    start_tick: int = 0
    rpitch: int = 0
    symbol: str = "down_keytab"
    invisible: bool = False
    type: str = field(default="pedal", init=False)


@dataclass
class TextEvent(Event):
    text: str = "myText"
    alignment: str = "left"
    start_tick: int = 0
    x_rpitch: float = 0.0
    rotation: float = 0.0
    x_offset_mm: float = 0.0
    y_offset_mm: float = 0.0
    font: dict[str, Any] = field(default_factory=lambda: {"family": "Edwin", "size_pt": 12.0, "bold": False, "italic": True, "underline": False, "x_offset": 0.0, "y_offset": 0.0})
    use_custom_font: bool = False
    text_background_width_offset_mm: float = 0.0
    type: str = field(default="text", init=False)


@dataclass
class SlurEvent(Event):
    x1_rpitch: int = 0
    y1_tick: int = 0
    x2_rpitch: int = 0
    y2_tick: int = 25
    x3_rpitch: int = 0
    y3_tick: int = 75
    x4_rpitch: int = 0
    y4_tick: int = 100
    type: str = field(default="slur", init=False)


@dataclass
class BeamEvent(Event):
    time: int = 0
    duration: int = 256
    hand: str = "left"
    type: str = field(default="beam", init=False)


@dataclass
class GridBandEvent(Event):
    start_tick: int = 0
    duration_ticks: int = 256
    type: str = field(default="grid_band", init=False)


@dataclass
class StartRepeatEvent(Event):
    start_tick: int = 0
    type: str = field(default="start_repeat", init=False)


@dataclass
class EndRepeatEvent(Event):
    start_tick: int = 0
    type: str = field(default="end_repeat", init=False)


@dataclass
class DoubleBarEvent(Event):
    start_tick: int = 0
    type: str = field(default="double_bar", init=False)


@dataclass
class CountLineEvent(Event):
    start_tick: int = 0
    rpitch1: int = 0
    rpitch2: int = 4
    type: str = field(default="count_line", init=False)


@dataclass
class LineBreakEvent(Event):
    start_tick: int = 0
    margin_mm: list[float] = field(default_factory=lambda: [5.0, 5.0])
    stave_range: list[int] | str = "auto"
    page_break: bool = False
    type: str = field(default="line_break", init=False)


@dataclass
class TempoEvent(Event):
    start_tick: int = 0
    duration_ticks: int = 256
    tempo: int = 120
    x_offset_mm: float = 0.0
    invisible: bool = False
    type: str = field(default="tempo", init=False)


@dataclass
class ArpeggioEvent(Event):
    start_tick: int = 0
    rtime1_ticks: int = 0
    rtime2_ticks: int = 32
    note_pitches: list[int] = field(default_factory=list)
    type: str = field(default="arpeggio", init=False)


@dataclass
class CrescendoEvent(Event):
    start_tick: int = 0
    duration_ticks: int = 256
    x_rpitch: int = 0
    type: str = field(default="crescendo", init=False)


@dataclass
class DecrescendoEvent(Event):
    start_tick: int = 0
    duration_ticks: int = 256
    x_rpitch: int = 0
    type: str = field(default="decrescendo", init=False)


@dataclass
class DynamicSymbolEvent(Event):
    start_tick: int = 0
    x_rpitch: int = 0
    symbol: str = ""
    rotation: float = 0.0
    type: str = field(default="dynamic_symbol", init=False)


@dataclass
class LineEvent(Event):
    start_tick: int = 0
    time1_tick: int = 0
    time2_tick: int = 0
    rpitch1: float = 0.0
    rpitch2: float = 0.0
    width_mm: float = 0.5
    dash_pattern_mm: list[float] = field(default_factory=lambda: [3.0])
    dash_offset_mm: float = 0.0
    color: str = "auto"
    zigzag_type: str | None = None
    zigzag_amp_semitone: float = 0.0
    zigzag_freq_ticks: float = 64.0
    arrow: str | None = None
    arrow_form: list[float] = field(default_factory=lambda: [0.5, 0.5])
    type: str = field(default="line", init=False)


StaveEvent = NoteEvent | GraceNoteEvent | PedalEvent | TextEvent | SlurEvent | BeamEvent | GridBandEvent | StartRepeatEvent | EndRepeatEvent | DoubleBarEvent | CountLineEvent | ArpeggioEvent | CrescendoEvent | DecrescendoEvent | DynamicSymbolEvent | LineEvent
LineOwnedEvent = StaveEvent | LineBreakEvent
PageEvent = LineOwnedEvent
TimelineEvent = TempoEvent

EVENT_TYPES: dict[str, type[Event]] = {
    "note": NoteEvent,
    "grace_note": GraceNoteEvent,
    "pedal": PedalEvent,
    "text": TextEvent,
    "slur": SlurEvent,
    "beam": BeamEvent,
    "grid_band": GridBandEvent,
    "start_repeat": StartRepeatEvent,
    "end_repeat": EndRepeatEvent,
    "double_bar": DoubleBarEvent,
    "count_line": CountLineEvent,
    "line_break": LineBreakEvent,
    "tempo": TempoEvent,
    "arpeggio": ArpeggioEvent,
    "crescendo": CrescendoEvent,
    "decrescendo": DecrescendoEvent,
    "dynamic_symbol": DynamicSymbolEvent,
    "line": LineEvent,
}