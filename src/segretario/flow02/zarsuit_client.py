from __future__ import annotations

import json
from pathlib import Path
from typing import Protocol

from segretario.flow02.models import (
    DetailLevel,
    SecretaryTaskRequest,
    ZarsuitOutput,
)


class ZarsuitClient(Protocol):
    def call(self, request: SecretaryTaskRequest) -> ZarsuitOutput: ...


class ZarsuitClientStub:
    """Stub deterministica per test e sviluppo; non chiama Ollama né rete."""

    def __init__(self, responses_file: Path | None = None) -> None:
        self._responses: list[dict] = []
        self._call_count = 0
        if responses_file and responses_file.exists():
            data = json.loads(responses_file.read_text(encoding="utf-8"))
            self._responses = data if isinstance(data, list) else [data]

    def add_response(
        self,
        *,
        content: str,
        cited_fields: list[str] | None = None,
        suggested_next_steps: list[str] | None = None,
        detail_level: DetailLevel = DetailLevel.SUMMARY,
        raw_json: dict | None = None,
    ) -> None:
        self._responses.append({
            "content": content,
            "cited_fields": cited_fields or [],
            "suggested_next_steps": suggested_next_steps or [],
            "detail_level": detail_level.value,
            "raw_json": raw_json,
        })

    def call(self, request: SecretaryTaskRequest) -> ZarsuitOutput:
        if not self._responses:
            return ZarsuitOutput(
                internal_request_id=request.context.internal_request_id,
                content=f"[stub] risposta per: {request.user_visible_goal}",
                cited_fields=[],
                suggested_next_steps=[],
                detail_level=DetailLevel.SUMMARY,
            )
        idx = min(self._call_count, len(self._responses) - 1)
        r = self._responses[idx]
        self._call_count += 1
        return ZarsuitOutput(
            internal_request_id=request.context.internal_request_id,
            content=r["content"],
            cited_fields=r.get("cited_fields", []),
            suggested_next_steps=r.get("suggested_next_steps", []),
            detail_level=DetailLevel(r.get("detail_level", "summary")),
            raw_json=r.get("raw_json"),
        )
