from __future__ import annotations

import json
from pathlib import Path
from typing import Protocol

import httpx

from segretario.config.settings import LLMSettings


def _ollama_stop_model(base_url: str, model: str, timeout: int = 30) -> bool:
    """Forza lo stop di un modello caricato in VRAM via Ollama API.

    Equivalente a `ollama stop <model>`. Usa keep_alive=0 in una richiesta
    di generate vuota per fare unload immediato.

    Ritorna True se la chiamata è andata a buon fine, False altrimenti.
    Non solleva eccezioni: l'unload è best-effort.
    """
    try:
        with httpx.Client(timeout=timeout) as client:
            response = client.post(
                f"{base_url}/api/generate",
                json={
                    "model": model,
                    "prompt": "",
                    "keep_alive": 0,
                    "stream": False,
                },
            )
            return response.status_code == 200
    except httpx.HTTPError:
        return False


def _ollama_list_loaded(base_url: str, timeout: int = 10) -> list[str]:
    """Ritorna la lista dei modelli attualmente caricati in VRAM via /api/ps."""
    try:
        with httpx.Client(timeout=timeout) as client:
            response = client.get(f"{base_url}/api/ps")
            response.raise_for_status()
            data = response.json()
            return [m.get("name", "") for m in data.get("models", [])]
    except httpx.HTTPError:
        return []


class ConsolidationResult:
    def __init__(
        self,
        *,
        ok: bool,
        message: str,
        extracted_facts: list[dict] | None = None,
    ) -> None:
        self.ok = ok
        self.message = message
        self.extracted_facts = extracted_facts or []


class AsyncLLMClient(Protocol):
    def consolidate_session(
        self, session_jsonl: Path, vault_path: Path
    ) -> ConsolidationResult: ...


class AsyncLLMClientStub:
    """Stub no-op: used in tests and when async_model is not available."""

    def consolidate_session(
        self, session_jsonl: Path, vault_path: Path
    ) -> ConsolidationResult:
        return ConsolidationResult(ok=True, message="async stub no-op")


class OllamaAsyncLLMClient:
    """Real client via Ollama HTTP API. Loads the async model, runs
    the consolidation prompt, then unloads the model (keep_alive: 0)."""

    def __init__(self, settings: LLMSettings) -> None:
        self._model = settings.async_model
        self._base_url = settings.base_url
        self._timeout = settings.async_model_timeout_seconds

    def consolidate_session(
        self, session_jsonl: Path, vault_path: Path
    ) -> ConsolidationResult:
        if not session_jsonl.exists():
            return ConsolidationResult(
                ok=False,
                message=f"session jsonl not found: {session_jsonl}",
            )

        entries = [
            json.loads(line)
            for line in session_jsonl.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        if not entries:
            return ConsolidationResult(
                ok=True,
                message="empty session, nothing to consolidate",
            )

        prompt = self._build_prompt(entries)

        try:
            with httpx.Client(timeout=self._timeout) as client:
                response = client.post(
                    f"{self._base_url}/api/generate",
                    json={
                        "model": self._model,
                        "prompt": prompt,
                        "stream": False,
                        "format": "json",
                        "options": {"temperature": 0.2},
                        # keep_alive=0: scarica async_model immediatamente dopo l'inferenza.
                        # Coerente con il design (PDF sezione 3.3): scarica sync_model ->
                        # carica async_model -> consolidamento -> scarica async_model ->
                        # ricarica sync_model. Lo stop di sync_model PRIMA dell'inferenza
                        # è gestito da ConsolidationJob.
                        "keep_alive": 0,
                    },
                )
                response.raise_for_status()
                data = response.json()
        except httpx.HTTPError as e:
            return ConsolidationResult(
                ok=False, message=f"ollama call failed: {e}"
            )

        try:
            parsed = json.loads(data.get("response", "{}"))
        except json.JSONDecodeError:
            return ConsolidationResult(
                ok=False, message="ollama response is not valid JSON"
            )

        facts = parsed.get("facts", [])
        decisions = parsed.get("decisions", [])
        preferences = parsed.get("preferences", [])

        all_items = (
            [{"type": "fact", **f} for f in facts]
            + [{"type": "decision", **d} for d in decisions]
            + [{"type": "preference", **p} for p in preferences]
        )

        return ConsolidationResult(
            ok=True,
            message=f"consolidated {len(all_items)} items",
            extracted_facts=all_items,
        )

    def _build_prompt(self, entries: list[dict]) -> str:
        conversation = "\n".join(
            f"[{e.get('role', '?')}] {e.get('content_ref', '')}"
            for e in entries
        )
        return f"""Sei un agente di consolidamento. Analizza la seguente sessione di conversazione ed estrai informazioni rilevanti da salvare nel knowledge base a lungo termine.

Sessione:
{conversation}

Restituisci SOLO JSON valido con questa struttura:
{{
  "facts": [{{"content": "fatto rilevante", "category": "..."}}],
  "decisions": [{{"content": "decisione presa", "context": "..."}}],
  "preferences": [{{"content": "preferenza dichiarata", "domain": "..."}}]
}}

Estrai solo informazioni esplicitamente affermate. Non inventare. Se la sessione non contiene nulla di rilevante, restituisci liste vuote."""


def build_async_client(settings: LLMSettings) -> AsyncLLMClient:
    """Creates the appropriate client based on config."""
    if settings.provider != "ollama":
        return AsyncLLMClientStub()
    return OllamaAsyncLLMClient(settings)
