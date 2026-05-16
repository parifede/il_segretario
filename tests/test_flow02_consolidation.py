from __future__ import annotations

import json
from pathlib import Path

import pytest

from segretario.connectors.async_llm_client import (
    AsyncLLMClientStub,
    ConsolidationResult,
)
from segretario.flow02.session.consolidation import ConsolidationJob


def test_consolidation_stub_no_op(tmp_path):
    session = tmp_path / "session.jsonl"
    session.write_text('{"role":"user","content_ref":"ciao"}\n', encoding="utf-8")
    result = ConsolidationJob().run(session, tmp_path)
    assert result.ok


def test_consolidation_writes_atomically_when_facts_extracted(tmp_path):
    class FakeClient:
        def consolidate_session(self, session_jsonl, vault_path):
            return ConsolidationResult(
                ok=True,
                message="ok",
                extracted_facts=[
                    {"type": "fact", "content": "Marco preferisce le riunioni il martedì"}
                ],
            )

    session = tmp_path / "session_test.jsonl"
    session.write_text('{"role":"user","content_ref":"x"}\n', encoding="utf-8")

    job = ConsolidationJob(client=FakeClient())
    result = job.run(session, tmp_path)

    assert result.ok
    knowledge_dir = tmp_path / "knowledge" / "consolidated"
    assert knowledge_dir.exists()
    files = list(knowledge_dir.glob("session_test_*.json"))
    assert len(files) == 1
    data = json.loads(files[0].read_text(encoding="utf-8"))
    assert data["session_id"] == "session_test"
    assert len(data["items"]) == 1


def test_consolidation_handles_missing_jsonl(tmp_path):
    class FailClient:
        def consolidate_session(self, session_jsonl, vault_path):
            return ConsolidationResult(ok=False, message="not found")

    job = ConsolidationJob(client=FailClient())
    result = job.run(tmp_path / "nonexistent.jsonl", tmp_path)
    assert result.ok is False


def test_consolidation_empty_session(tmp_path):
    """Empty session: no file written, but ok."""
    session = tmp_path / "empty.jsonl"
    session.write_text("", encoding="utf-8")

    class EmptyClient:
        def consolidate_session(self, session_jsonl, vault_path):
            return ConsolidationResult(ok=True, message="empty", extracted_facts=[])

    job = ConsolidationJob(client=EmptyClient())
    result = job.run(session, tmp_path)
    assert result.ok
    assert not (tmp_path / "knowledge" / "consolidated").exists()
