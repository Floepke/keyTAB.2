from __future__ import annotations

import unittest

from keytab2_model import KeyTab2Document, NoteEvent
from ui.ctlz import CtlZ


class CtlZTests(unittest.TestCase):
    def test_undo_redo_restores_snapshots_and_replaces_the_redo_branch(self) -> None:
        document = KeyTab2Document.new()
        history = CtlZ(document, max_steps=64)
        self.assertFalse(history.add_ctlz(document))
        stave = document.pages[0].systems[0].staves[0]
        stave.events.append(NoteEvent(time=256, duration=64, pitch=60))
        self.assertTrue(history.add_ctlz(document))
        stave.events.append(NoteEvent(time=320, duration=64, pitch=64))
        self.assertTrue(history.add_ctlz(document))

        restored = history.undo()

        self.assertIsNotNone(restored)
        self.assertEqual([event.pitch for event in restored.pages[0].systems[0].staves[0].events], [60])
        self.assertTrue(history.can_redo)
        restored.pages[0].systems[0].staves[0].events.append(NoteEvent(time=384, duration=64, pitch=67))
        self.assertTrue(history.add_ctlz(restored))
        self.assertFalse(history.can_redo)

    def test_history_keeps_sixty_four_reversible_steps(self) -> None:
        document = KeyTab2Document.new()
        history = CtlZ(document, max_steps=64)
        stave = document.pages[0].systems[0].staves[0]
        for pitch in range(65):
            stave.events.append(NoteEvent(time=pitch * 64, duration=32, pitch=pitch))
            history.add_ctlz(document)

        undo_count = 0
        while history.undo() is not None:
            undo_count += 1

        self.assertEqual(undo_count, 64)