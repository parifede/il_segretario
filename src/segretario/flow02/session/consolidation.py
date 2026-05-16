from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from segretario.connectors.async_llm_client import (
    AsyncLLMClient,
    AsyncLLMClientStub,
    ConsolidationResult,
)


class ConsolidationJob:
    """Runs consolidation for a closed session.

    Uses write-then-rename for atomic file writes.
    """

    def __init__(self, client: AsyncLLMClient | None = None) -> None:
        self._client = client or AsyncLLMClientStub()

    def run(
        self, session_jsonl: Path, vault_path: Path
    ) -> ConsolidationResult:
        result = self._client.consolidate_session(session_jsonl, vault_path)
        if not result.ok:
            return result

        if result.extracted_facts:
            self._write_atomically(vault_path, session_jsonl.stem, result)

        return result

    def _write_atomically(
        self,
        vault_path: Path,
        session_id: str,
        result: ConsolidationResult,
    ) -> None:
        target_dir = vault_path / "knowledge" / "consolidated"
        target_dir.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        target = target_dir / f"{session_id}_{timestamp}.json"
        tmp = target.with_suffix(".tmp")

        payload = {
            "session_id": session_id,
            "consolidated_at": datetime.now(timezone.utc).isoformat(),
            "items": result.extracted_facts,
        }
        tmp.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        tmp.replace(target)
