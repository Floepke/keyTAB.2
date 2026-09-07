"""Dependency-free Standard MIDI File import for keyTAB2 documents."""

from __future__ import annotations

import struct
from collections import defaultdict
from pathlib import Path

from keytab2_model import BaseGrid, KeyTab2Document, NoteEvent
from keytab2_model.base_grid import grid_boundaries, total_duration


class MidiImportError(ValueError):
    """Raised when a file cannot be read as a Standard MIDI File."""


def _read_vlq(data: bytes, position: int) -> tuple[int, int]:
    value = 0
    for _ in range(4):
        if position >= len(data):
            raise MidiImportError("Truncated MIDI variable-length value")
        byte = data[position]
        position += 1
        value = (value << 7) | (byte & 0x7F)
        if not byte & 0x80:
            return value, position
    return value, position


def _parse_midi(path: str | Path) -> tuple[int, list[tuple[str, int, int, int, int]]]:
    data = Path(path).read_bytes()
    if len(data) < 14 or data[:4] != b"MThd":
        raise MidiImportError("Not a Standard MIDI File")
    header_length = struct.unpack(">I", data[4:8])[0]
    if header_length < 6 or len(data) < 8 + header_length:
        raise MidiImportError("Truncated MIDI header")
    division = struct.unpack(">H", data[12:14])[0]
    if division & 0x8000:
        raise MidiImportError("SMPTE-timed MIDI files are not supported")
    position = 8 + header_length
    events: list[tuple[str, int, int, int, int]] = []
    while position + 8 <= len(data):
        chunk_type = data[position:position + 4]
        chunk_length = struct.unpack(">I", data[position + 4:position + 8])[0]
        position += 8
        chunk = data[position:position + chunk_length]
        position += chunk_length
        if chunk_type != b"MTrk":
            continue
        tick = 0
        cursor = 0
        running_status: int | None = None
        while cursor < len(chunk):
            delta, cursor = _read_vlq(chunk, cursor)
            tick += delta
            if cursor >= len(chunk):
                break
            status = chunk[cursor]
            cursor += 1
            if status == 0xFF:
                if cursor >= len(chunk):
                    break
                meta_type = chunk[cursor]
                cursor += 1
                length, cursor = _read_vlq(chunk, cursor)
                payload = chunk[cursor:cursor + length]
                cursor += length
                if meta_type == 0x58 and len(payload) >= 2:
                    events.append(("time_signature", tick, payload[0], 2 ** payload[1], 0))
                if meta_type == 0x2F:
                    break
                continue
            if status in (0xF0, 0xF7):
                length, cursor = _read_vlq(chunk, cursor)
                cursor += length
                running_status = None
                continue
            if status & 0x80:
                running_status = status
                if cursor >= len(chunk):
                    break
                data_one = chunk[cursor]
                cursor += 1
            elif running_status is not None:
                data_one = status
                status = running_status
            else:
                continue
            status_type = status >> 4
            channel = status & 0x0F
            if status_type in (0xC, 0xD):
                continue
            if cursor >= len(chunk):
                break
            data_two = chunk[cursor]
            cursor += 1
            if status_type == 0x9:
                events.append(("note_on" if data_two else "note_off", tick, channel, data_one, data_two))
            elif status_type == 0x8:
                events.append(("note_off", tick, channel, data_one, data_two))
    return division, events


def load_midi(path: str | Path) -> KeyTab2Document:
    """Load a MIDI file into the default stave, splitting every six measures."""
    ticks_per_quarter, events = _parse_midi(path)
    document = KeyTab2Document.new()
    document.score_info.title = Path(path).stem or document.score_info.title
    time_signatures = sorted(
        {(tick, numerator, denominator) for kind, tick, numerator, denominator, _ in events if kind == "time_signature"},
    )
    note_events = [event for event in events if event[0] in {"note_on", "note_off"} and event[2] != 9]
    max_tick = max((event[1] for event in note_events), default=ticks_per_quarter * 4)

    def document_tick(midi_tick: int) -> int:
        return round(midi_tick * document.time_per_quarter / ticks_per_quarter)

    signature_changes = [(document_tick(tick), numerator, denominator) for tick, numerator, denominator in time_signatures]
    if not signature_changes or signature_changes[0][0] != 0:
        signature_changes.insert(0, (0, 4, 4))
    base_grid: list[BaseGrid] = []
    final_tick = document_tick(max_tick)
    for index, (start_tick, numerator, denominator) in enumerate(signature_changes):
        next_tick = signature_changes[index + 1][0] if index + 1 < len(signature_changes) else final_tick
        measure_ticks = numerator * document.time_per_quarter * 4 // denominator
        amount = max(1, -(-(next_tick - start_tick) // measure_ticks))
        base_grid.append(BaseGrid(numerator=numerator, denominator=denominator, beat_grouping=list(range(1, numerator + 1)), measure_amount=amount))
    document.base_grid = base_grid
    system = document.pages[0].systems[0]
    system.end_tick = total_duration(base_grid, document.time_per_quarter)
    open_notes: dict[tuple[int, int], list[tuple[int, int]]] = defaultdict(list)
    for kind, tick, channel, pitch, velocity in note_events:
        key = (channel, pitch)
        if kind == "note_on":
            open_notes[key].append((tick, velocity))
        elif open_notes[key]:
            start_tick, start_velocity = open_notes[key].pop()
            duration = max(1, document_tick(tick) - document_tick(start_tick))
            system.staves[0].events.append(NoteEvent(
                time=document_tick(start_tick), duration=duration, pitch=pitch, velocity=start_velocity,
                hand="left" if pitch < 60 else "right",
            ))
    for (_, pitch), starts in open_notes.items():
        for start_tick, velocity in starts:
            system.staves[0].events.append(NoteEvent(
                time=document_tick(start_tick), duration=max(1, document.time_per_quarter // 8), pitch=pitch,
                velocity=velocity, hand="left" if pitch < 60 else "right",
            ))
    system.staves[0].touch()
    measure_starts, _ = grid_boundaries(base_grid, document.time_per_quarter)
    following = system
    for split_tick in measure_starts[6:-1:6]:
        following = document.split_system_at(document.pages[-1].id, following.id, split_tick)
    document.repaginate_document()
    return document