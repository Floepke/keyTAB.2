"""Final-mm notehead geometry adapted from keyTAB1's notation definitions."""

from __future__ import annotations

import math
from dataclasses import dataclass


BLACK_PITCH_CLASSES = {1, 3, 6, 8, 10}
VALID_FORMS = {"circle", "triangle", "bullet", "cross"}


@dataclass(frozen=True)
class NoteheadGeometry:
    points_mm: tuple[tuple[float, float], ...]
    form: str
    filled: bool


def resolve_notehead(notehead: str, pitch: int, black_above: bool) -> tuple[str, bool, bool]:
    """Return form, is-up, and fill state for an event's notehead literal."""
    literal = str(notehead or "auto").strip().lower()
    if literal == "auto":
        return "circle", pitch % 12 in BLACK_PITCH_CLASSES and black_above, pitch % 12 in BLACK_PITCH_CLASSES
    parts = literal.split("_")
    form = "cross" if parts[0] == "cross" else parts[0]
    if form not in VALID_FORMS:
        return "circle", False, False
    return form, literal.endswith("_up"), "black" in parts


def build_notehead_outline(
    x_mm: float,
    y_mm: float,
    hand: str,
    form: str,
    is_up: bool,
    filled: bool,
    semitone_mm: float,
    width_scale: float,
    height_scale: float,
    tilt: float,
) -> NoteheadGeometry:
    """Build a notehead whose stem attaches at the vertical anchor ``y_mm``."""
    half_width = semitone_mm * max(0.05, width_scale)
    height = semitone_mm * 2.0 * max(0.1, height_scale)
    top = y_mm - height if is_up else y_mm
    if form == "triangle":
        points = ((x_mm, top), (x_mm - half_width, top + height), (x_mm + half_width, top + height)) if not is_up else ((x_mm - half_width, top), (x_mm + half_width, top), (x_mm, top + height))
        return NoteheadGeometry(points, form, filled)
    if form == "bullet":
        point_y = top + height if not is_up else top
        flat_y = top if not is_up else top + height
        points = ((x_mm - half_width, flat_y), (x_mm + half_width, flat_y), (x_mm + half_width, top + height * 0.33), (x_mm, point_y), (x_mm - half_width, top + height * 0.33))
        return NoteheadGeometry(points, form, filled)
    if form == "cross":
        return NoteheadGeometry(((x_mm - half_width, top), (x_mm + half_width, top + height), (x_mm, top + height * 0.5), (x_mm + half_width, top), (x_mm - half_width, top + height)), form, False)

    sign = -1.0 if hand == "right" else 1.0
    points = tuple(
        (
            x_mm + half_width * math.cos(angle),
            top + height * 0.5 + height * 0.5 * math.sin(angle) + sign * tilt * half_width * math.cos(angle),
        )
        for angle in (2.0 * math.pi * index / 48.0 for index in range(48))
    )
    attachment_y = y_mm
    edge_y = max(point[1] for point in points) if is_up else min(point[1] for point in points)
    anchored_points = tuple((point_x, point_y + attachment_y - edge_y) for point_x, point_y in points)
    return NoteheadGeometry(anchored_points, form, filled)