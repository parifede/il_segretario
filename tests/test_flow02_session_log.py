from __future__ import annotations

import json
from pathlib import Path

import pytest

from segretario.flow02.session.log import SessionLog


def test_append_creates_jsonl_file(tmp_path):
    log = SessionLog(tmp_path / "session.jsonl")
    entry = log.append(session_id="s1", role="user", content_ref="Ciao")
    assert (tmp_path / "session.jsonl").exists()
    assert entry["role"] == "user"
    assert entry["session_id"] == "s1"
    assert "message_id" in entry
    assert "timestamp" in entry


def test_append_only_existing_entries_unchanged(tmp_path):
    log = SessionLog(tmp_path / "session.jsonl")
    log.append(session_id="s1", role="user", content_ref="Prima")
    first = log.entries()[0]
    log.append(session_id="s1", role="zarsuit", content_ref="Risposta")
    assert log.entries()[0] == first


def test_entries_returns_all_appended(tmp_path):
    log = SessionLog(tmp_path / "session.jsonl")
    log.append(session_id="s1", role="user", content_ref="Msg1")
    log.append(session_id="s1", role="zarsuit", content_ref="Msg2")
    entries = log.entries()
    assert len(entries) == 2
    assert entries[0]["content_ref"] == "Msg1"
    assert entries[1]["content_ref"] == "Msg2"


def test_entries_empty_when_file_does_not_exist(tmp_path):
    log = SessionLog(tmp_path / "nonexistent.jsonl")
    assert log.entries() == []


def test_to_chat_md_contains_roles_and_content(tmp_path):
    log = SessionLog(tmp_path / "session.jsonl")
    log.append(session_id="s1", role="user", content_ref="Domanda")
    log.append(session_id="s1", role="zarsuit", content_ref="Risposta")
    md = log.to_chat_md()
    assert "user" in md
    assert "zarsuit" in md
    assert "Domanda" in md
    assert "Risposta" in md


def test_internal_request_id_stored_when_provided(tmp_path):
    log = SessionLog(tmp_path / "session.jsonl")
    log.append(session_id="s1", role="zarsuit",
               content_ref="output", internal_request_id="iid-123")
    entry = log.entries()[0]
    assert entry["internal_request_id"] == "iid-123"
