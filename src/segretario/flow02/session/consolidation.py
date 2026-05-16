from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from segretario.connectors.async_llm_client import (
    AsyncLLMClient,
    AsyncLLMClientStub,
    ConsolidationResult,
    _ollama_list_loaded,
    _ollama_stop_model,
)


class ConsolidationJob:
    """Esegue il consolidamento di una sessione chiusa.

    Pattern write-then-rename per atomicità.
    Prima di chiamare il modello async, fa unload del modello sync per
    liberare VRAM (operazione sicura: la chiusura sessione implica utente
    inattivo da >1h).
    """

    def __init__(
        self,
        client: AsyncLLMClient | None = None,
        *,
        sync_model_to_unload: str | None = None,
        ollama_base_url: str | None = None,
    ) -> None:
        self._client = client or AsyncLLMClientStub()
        self._sync_model = sync_model_to_unload
        self._ollama_base_url = ollama_base_url

    def run(
        self, session_jsonl: Path, vault_path: Path
    ) -> ConsolidationResult:
        # 1. Unload del modello sync, se configurato
        if self._sync_model and self._ollama_base_url:
            loaded = _ollama_list_loaded(self._ollama_base_url)
            if self._sync_model in loaded:
                _ollama_stop_model(self._ollama_base_url, self._sync_model)

        # 2. Consolidamento vero
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
