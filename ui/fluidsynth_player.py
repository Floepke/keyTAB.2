"""Cancellable FluidSynth playback for keyTAB 2 documents."""

from __future__ import annotations

import ctypes
import ctypes.util
import os
import sys
from pathlib import Path
from threading import Event, Lock, Thread, current_thread
from time import monotonic, sleep

from PySide6.QtCore import QObject, Signal

from keytab2_model import NoteEvent, TempoEvent
from keytab2_model.document import KeyTab2Document


class FluidSynthPlayer(QObject):
    """Play document notes through FluidSynth without blocking the UI thread."""

    playback_started = Signal()
    playback_finished = Signal()
    playback_failed = Signal(str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._synth = None
        self._channel = 0
        self._stop_event = Event()
        self._thread: Thread | None = None
        self._lock = Lock()
        self._playing = False
        self._playback_started_at: float | None = None
        self._playback_start_tick = 0
        self._playback_tempos: list[TempoEvent] = []
        self._playback_time_per_quarter = 1

    @property
    def is_playing(self) -> bool:
        with self._lock:
            return self._playing

    def initialize(self) -> bool:
        """Open the audio driver without producing an audible note."""
        try:
            self._ensure_synth()
        except (ImportError, OSError, RuntimeError):
            return False
        self._all_notes_off()
        return True

    def play(self, document: KeyTab2Document, start_tick: int = 0) -> bool:
        self.stop()
        start_tick = max(0, int(start_tick))
        events = self._scheduled_events(document, start_tick)
        if not events:
            self.playback_failed.emit("There are no notes to play.")
            return False
        try:
            self._ensure_synth()
        except (ImportError, OSError, RuntimeError) as error:
            self.playback_failed.emit(str(error))
            return False

        self._stop_event.clear()
        with self._lock:
            self._playing = True
            self._playback_started_at = monotonic()
            self._playback_start_tick = start_tick
            self._playback_tempos = self._resolved_tempos(document)
            self._playback_time_per_quarter = document.time_per_quarter
        self._thread = Thread(target=self._run, args=(events,), name="fluidsynth-playback", daemon=True)
        self._thread.start()
        self.playback_started.emit()
        return True

    def stop(self) -> None:
        self._stop_event.set()
        self._all_notes_off()

    def current_tick(self) -> int | None:
        """Return the current score tick while full-score playback is active."""
        with self._lock:
            if not self._playing or self._playback_started_at is None:
                return None
            elapsed_seconds = monotonic() - self._playback_started_at
            start_tick = self._playback_start_tick
            tempos = self._playback_tempos
            time_per_quarter = self._playback_time_per_quarter
        return self._ticks_for_seconds(elapsed_seconds, start_tick, tempos, time_per_quarter)

    def audition(self, pitch: int, velocity: int = 64, duration_seconds: float = 0.15) -> bool:
        """Play one short note while full-score playback is idle."""
        if self.is_playing:
            return False
        try:
            self._ensure_synth()
        except (ImportError, OSError, RuntimeError) as error:
            self.playback_failed.emit(str(error))
            return False
        midi_pitch = max(0, min(127, int(pitch)))
        midi_velocity = max(1, min(127, int(velocity)))

        def run_audition() -> None:
            try:
                self._synth.noteon(self._channel, midi_pitch, midi_velocity)
                sleep(max(0.02, float(duration_seconds)))
                self._synth.noteoff(self._channel, midi_pitch)
            except Exception:
                self._all_notes_off()

        Thread(target=run_audition, name="fluidsynth-audition", daemon=True).start()
        return True

    def shutdown(self) -> None:
        self.stop()
        thread = self._thread
        if thread is not None and thread is not current_thread():
            thread.join(timeout=0.5)
        self._thread = None
        if self._synth is not None:
            self._synth.delete()
            self._synth = None

    def _ensure_synth(self) -> None:
        if self._synth is not None:
            return
        library = self._library_path()
        if not library:
            raise RuntimeError("FluidSynth is not installed. On macOS, run: brew install fluid-synth")
        ctypes.CDLL(library)
        if sys.platform == "darwin" and library.startswith("/opt/homebrew/"):
            os.environ.setdefault("HOMEBREW_PREFIX", "/opt/homebrew")
        try:
            import fluidsynth
        except ImportError as error:
            raise ImportError("pyfluidsynth is not installed. Run: .venv/bin/python -m pip install -r requirements.txt") from error
        soundfont = self._soundfont_path()
        synth = fluidsynth.Synth()
        try:
            synth.start(driver="coreaudio" if sys.platform == "darwin" else "pulseaudio")
        except Exception:
            synth.start()
        soundfont_id = synth.sfload(str(soundfont))
        if soundfont_id < 0:
            synth.delete()
            raise RuntimeError(f"FluidSynth could not load soundfont: {soundfont}")
        synth.program_select(self._channel, soundfont_id, 0, 0)
        self._synth = synth

    @staticmethod
    def _library_path() -> str | None:
        library = ctypes.util.find_library("fluidsynth")
        if library:
            return library
        if sys.platform == "darwin":
            for path in (
                "/opt/homebrew/opt/fluid-synth/lib/libfluidsynth.dylib",
                "/usr/local/opt/fluid-synth/lib/libfluidsynth.dylib",
            ):
                if Path(path).is_file():
                    return path
        return None

    @staticmethod
    def _soundfont_path() -> Path:
        configured = os.environ.get("KEYTAB_SOUNDFONT")
        bundled = None
        if getattr(sys, "frozen", False):
            bundled = Path(sys.executable).resolve().parent.parent / "Resources" / "soundfonts" / "FluidR3_GM.sf2"
        candidates = [
            Path(configured).expanduser() if configured else None,
            bundled,
            Path.home() / ".keyTAB2" / "soundfonts" / "FluidR3_GM.sf2",
            Path("/opt/homebrew/opt/fluid-synth/share/fluid-synth/sf2/VintageDreamsWaves-v2.sf2"),
            Path("/usr/local/opt/fluid-synth/share/fluid-synth/sf2/VintageDreamsWaves-v2.sf2"),
            Path("/usr/share/sounds/sf2/FluidR3_GM.sf2"),
            Path("/usr/share/sounds/sf2/TimGM6mb.sf2"),
        ]
        soundfont = next((candidate for candidate in candidates if candidate is not None and candidate.is_file()), None)
        if soundfont is None:
            raise RuntimeError("No soundfont found. Set KEYTAB_SOUNDFONT to an .sf2 file.")
        return soundfont

    def _run(self, events: list[tuple[float, str, int, int]]) -> None:
        start_time = monotonic()
        try:
            for scheduled_time, kind, pitch, velocity in events:
                if self._stop_event.wait(max(0.0, start_time + scheduled_time - monotonic())):
                    break
                if kind == "on":
                    self._synth.noteon(self._channel, pitch, velocity)
                else:
                    self._synth.noteoff(self._channel, pitch)
        finally:
            self._all_notes_off()
            with self._lock:
                self._playing = False
                self._playback_started_at = None
            self.playback_finished.emit()

    def _all_notes_off(self) -> None:
        if self._synth is not None:
            self._synth.all_notes_off(self._channel)

    @staticmethod
    def _resolved_tempos(document: KeyTab2Document) -> list[TempoEvent]:
        tempos = sorted((event for event in document.timeline_events if isinstance(event, TempoEvent)), key=lambda event: event.start_tick)
        if not tempos or tempos[0].start_tick > 0:
            tempos.insert(0, TempoEvent(start_tick=0, tempo=120))
        return tempos

    @staticmethod
    def _seconds_at_tick(tick: int, tempos: list[TempoEvent], time_per_quarter: int) -> float:
        seconds = 0.0
        for index, tempo in enumerate(tempos):
            next_tick = tempos[index + 1].start_tick if index + 1 < len(tempos) else tick
            if tick <= tempo.start_tick:
                break
            end_tick = min(tick, next_tick)
            seconds += (end_tick - tempo.start_tick) * 60.0 / (max(1, tempo.tempo) * time_per_quarter)
            if tick <= next_tick:
                break
        return seconds

    @staticmethod
    def _ticks_for_seconds(seconds: float, start_tick: int, tempos: list[TempoEvent], time_per_quarter: int) -> int:
        tick = start_tick
        remaining_seconds = max(0.0, seconds)
        tempo_index = max(index for index, tempo in enumerate(tempos) if tempo.start_tick <= start_tick)
        while remaining_seconds > 0.0:
            tempo = tempos[tempo_index]
            next_tick = tempos[tempo_index + 1].start_tick if tempo_index + 1 < len(tempos) else None
            seconds_per_tick = 60.0 / (max(1, tempo.tempo) * time_per_quarter)
            if next_tick is None:
                return round(tick + remaining_seconds / seconds_per_tick)
            ticks_until_change = next_tick - tick
            seconds_until_change = ticks_until_change * seconds_per_tick
            if remaining_seconds <= seconds_until_change:
                return round(tick + remaining_seconds / seconds_per_tick)
            tick = next_tick
            remaining_seconds -= seconds_until_change
            tempo_index += 1
        return tick

    @classmethod
    def _scheduled_events(cls, document: KeyTab2Document, start_tick: int = 0) -> list[tuple[float, str, int, int]]:
        tempos = cls._resolved_tempos(document)
        start_seconds = cls._seconds_at_tick(start_tick, tempos, document.time_per_quarter)

        events: list[tuple[float, str, int, int]] = []
        for page in document.pages:
            for system in page.systems:
                for stave in system.staves:
                    for note in stave.events:
                        if not isinstance(note, NoteEvent) or note.duration <= 0 or note.time + note.duration <= start_tick:
                            continue
                        pitch = max(0, min(127, int(note.pitch)))
                        velocity = max(1, min(127, int(note.velocity)))
                        events.append((max(0.0, cls._seconds_at_tick(note.time, tempos, document.time_per_quarter) - start_seconds), "on", pitch, velocity))
                        events.append((cls._seconds_at_tick(note.time + note.duration, tempos, document.time_per_quarter) - start_seconds, "off", pitch, 0))
        return sorted(events, key=lambda event: (event[0], 0 if event[1] == "off" else 1))