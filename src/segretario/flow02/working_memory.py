from __future__ import annotations

from segretario.flow02.models import WorkingMemoryTurn


class WorkingMemory:
    """L2: turni della conversazione sanificati, con sliding window."""

    def __init__(self, ceiling: int) -> None:
        self._ceiling = ceiling
        self._turns: list[WorkingMemoryTurn] = []

    def add_turn(self, turn: WorkingMemoryTurn) -> None:
        self._turns.append(turn)

    def compact_if_needed(self) -> None:
        """Droppa i turni più vecchi solo se si supera il tetto."""
        while self.total_tokens() > self._ceiling and len(self._turns) > 1:
            self._turns.pop(0)

    def turns(self) -> list[WorkingMemoryTurn]:
        return list(self._turns)

    def total_tokens(self) -> int:
        return sum(t.tokens for t in self._turns)

    def with_ceiling(self, ceiling: int) -> WorkingMemory:
        """Restituisce una nuova WorkingMemory con tetto diverso (per retry)."""
        wm = WorkingMemory(ceiling)
        wm._turns = list(self._turns)
        return wm
