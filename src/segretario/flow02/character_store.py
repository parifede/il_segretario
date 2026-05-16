from __future__ import annotations


class CharacterStore:
    """L1: identità statica di Zarsuit, caricata da config."""

    def __init__(self, identity_text: str) -> None:
        self._identity = identity_text

    def identity(self) -> str:
        return self._identity

    @classmethod
    def from_config(cls, identity: str) -> CharacterStore:
        return cls(identity)
