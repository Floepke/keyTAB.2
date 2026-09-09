from __future__ import annotations

import unittest

from keytab2_model import KeyTab2Document, NoteEvent, TempoEvent
from ui.fluidsynth_player import FluidSynthPlayer


class FluidSynthPlayerTests(unittest.TestCase):
    def test_audition_does_not_interrupt_full_score_playback(self) -> None:
        player = FluidSynthPlayer()
        player._playing = True

        self.assertFalse(player.audition(60))

    def test_schedules_note_on_and_off_at_document_tempo(self) -> None:
        document = KeyTab2Document.new()
        document.pages[0].systems[0].staves[0].events.append(NoteEvent(time=256, duration=512, pitch=60, velocity=96))

        events = FluidSynthPlayer._scheduled_events(document)

        self.assertEqual(events, [(0.5, "on", 60, 96), (1.5, "off", 60, 0)])

    def test_applies_tempo_changes_when_scheduling_note_events(self) -> None:
        document = KeyTab2Document.new()
        document.timeline_events = [TempoEvent(start_tick=0, tempo=120), TempoEvent(start_tick=256, tempo=60)]
        document.pages[0].systems[0].staves[0].events.append(NoteEvent(time=256, duration=256, pitch=60))

        events = FluidSynthPlayer._scheduled_events(document)

        self.assertEqual(events, [(0.5, "on", 60, 64), (1.5, "off", 60, 0)])


if __name__ == "__main__":
    unittest.main()