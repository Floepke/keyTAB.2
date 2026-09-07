"""Beat-based time-signature segments for keyTAB2 documents."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class BaseGrid:
    """A consecutive run of measures with beat-defined grouping.

    ``beat_grouping`` is a list of enabled written-beat markers. ``1`` selects
    the measure barline; values from ``2`` through ``numerator`` select visible
    grid lines. Markers above the numerator are retained but ignored, allowing
    a grid to survive a later time-signature change.
    """

    numerator: int = 4
    denominator: int = 4
    beat_grouping: list[int] = field(default_factory=lambda: [1, 2, 3, 4])
    measure_amount: int = 8
    indicator_enabled: bool = True

    def validate(self) -> None:
        if self.numerator < 1:
            raise ValueError("Base-grid numerator must be positive")
        if self.denominator < 1 or self.denominator & (self.denominator - 1):
            raise ValueError("Base-grid denominator must be a positive power of two")
        if self.measure_amount < 1:
            raise ValueError("Base-grid measure_amount must be positive")
        if not self.beat_grouping:
            raise ValueError("Base-grid beat_grouping must contain at least one marker")
        if not all(isinstance(beat, int) and beat > 0 for beat in self.beat_grouping):
            raise ValueError("Base-grid beat_grouping values must be positive integers")

    def beat_duration(self, time_per_quarter: int) -> int:
        return time_per_quarter * 4 // self.denominator

    def measure_duration(self, time_per_quarter: int) -> int:
        return self.numerator * self.beat_duration(time_per_quarter)

    def group_boundary_offsets(self, time_per_quarter: int) -> tuple[int, ...]:
        beat_duration = self.beat_duration(time_per_quarter)
        enabled_grid_beats = sorted({beat for beat in self.beat_grouping if 1 < beat <= self.numerator})
        return tuple((beat - 1) * beat_duration for beat in enabled_grid_beats)


def grid_boundaries(base_grid: list[BaseGrid], time_per_quarter: int) -> tuple[tuple[int, ...], tuple[int, ...]]:
    """Return document-time measure starts and enabled internal grid lines."""
    measure_starts: list[int] = []
    group_starts: list[int] = []
    current_time = 0
    for segment in base_grid:
        duration = segment.measure_duration(time_per_quarter)
        group_offsets = segment.group_boundary_offsets(time_per_quarter)
        for _ in range(segment.measure_amount):
            measure_starts.append(current_time)
            group_starts.extend(current_time + offset for offset in group_offsets)
            current_time += duration
    measure_starts.append(current_time)
    return tuple(measure_starts), tuple(group_starts)


def grid_line_boundaries(base_grid: list[BaseGrid], time_per_quarter: int) -> tuple[int, ...]:
    """Return internal times that should receive a visible grid line."""
    boundaries: list[int] = []
    current_time = 0
    for segment in base_grid:
        measure_duration = segment.measure_duration(time_per_quarter)
        offsets = segment.group_boundary_offsets(time_per_quarter)
        for _ in range(segment.measure_amount):
            boundaries.extend(current_time + offset for offset in offsets)
            current_time += measure_duration
    return tuple(boundaries)


def total_duration(base_grid: list[BaseGrid], time_per_quarter: int) -> int:
    return sum(segment.measure_amount * segment.measure_duration(time_per_quarter) for segment in base_grid)


def beam_windows(base_grid: list[BaseGrid], time_per_quarter: int) -> tuple[tuple[int, int], ...]:
    """Return automatic beam windows, split at enabled grid lines."""
    measure_starts, _ = grid_boundaries(base_grid, time_per_quarter)
    boundaries = tuple(sorted(set(measure_starts + grid_line_boundaries(base_grid, time_per_quarter))))
    return tuple((start, end) for start, end in zip(boundaries, boundaries[1:]) if start < end)


def apply_beam_overrides(default_windows: tuple[tuple[int, int], ...], overrides: list[tuple[int, int]]) -> tuple[tuple[int, int], ...]:
    """Replace automatic windows overlapped by explicit beam-marker windows."""
    windows = list(default_windows)
    for start, end in sorted(overrides):
        if end <= start:
            continue
        windows = [window for window in windows if window[0] >= end or window[1] <= start]
        windows.append((start, end))
    return tuple(sorted(windows))