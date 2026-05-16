from __future__ import annotations

from pathlib import Path


class ConsolidationResult:
    def __init__(self, *, ok: bool, message: str) -> None:
        self.ok = ok
        self.message = message


class ConsolidationJob:
    """Stub Fase 5: il consolidamento reale con Qwen3.5/3.6 è implementato in
    un spec dedicato. Questo stub è no-op e non chiama Ollama."""

    def run(self, session_jsonl: Path, vault_path: Path) -> ConsolidationResult:
        return ConsolidationResult(ok=True, message="consolidation stub (fase 5)")
