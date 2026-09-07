"""Bounded document snapshot history for editor undo and redo."""

from __future__ import annotations

from copy import deepcopy

from keytab2_model import KeyTab2Document


class CtlZ:
    """Store keyTAB2 document snapshots and restore them as independent models."""

    def __init__(self, document: KeyTab2Document, max_steps: int = 64) -> None:
        self.max_steps = max(1, int(max_steps))
        self.buffer: list[dict] = []
        self.index = -1
        self.reset_ctlz(document)

    @staticmethod
    def _snapshot(document: KeyTab2Document) -> dict:
        snapshot = document.to_dict()
        snapshot.pop("modified_at", None)
        return deepcopy(snapshot)

    def reset_ctlz(self, document: KeyTab2Document) -> None:
        self.buffer = [self._snapshot(document)]
        self.index = 0

    def add_ctlz(self, document: KeyTab2Document) -> bool:
        current = self._snapshot(document)
        if current == self.buffer[self.index]:
            return False
        if self.index < len(self.buffer) - 1:
            self.buffer = self.buffer[:self.index + 1]
        self.buffer.append(current)
        if len(self.buffer) > self.max_steps + 1:
            self.buffer.pop(0)
        self.index = len(self.buffer) - 1
        return True

    @property
    def can_undo(self) -> bool:
        return self.index > 0

    @property
    def can_redo(self) -> bool:
        return self.index < len(self.buffer) - 1

    def undo(self) -> KeyTab2Document | None:
        if not self.can_undo:
            return None
        self.index -= 1
        return KeyTab2Document.from_dict(deepcopy(self.buffer[self.index]))

    def redo(self) -> KeyTab2Document | None:
        if not self.can_redo:
            return None
        self.index += 1
        return KeyTab2Document.from_dict(deepcopy(self.buffer[self.index]))