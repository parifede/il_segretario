from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from segretario.flow02.character_store import CharacterStore
from segretario.flow02.models import WorkingMemoryTurn
from segretario.flow02.recall_engine import RecallEngine
from segretario.flow02.working_memory import WorkingMemory


# ── CharacterStore ────────────────────────────────────────────────────────────

def test_character_store_returns_identity():
    store = CharacterStore("Sei Zarsuit, l'assistente.")
    assert store.identity() == "Sei Zarsuit, l'assistente."


def test_character_store_from_config():
    store = CharacterStore.from_config("Identità custom")
    assert store.identity() == "Identità custom"


# ── WorkingMemory ─────────────────────────────────────────────────────────────

def _turn(content: str, tokens: int = 100) -> WorkingMemoryTurn:
    return WorkingMemoryTurn(role="user", content=content,
                             timestamp=datetime.now(timezone.utc), tokens=tokens)


def test_working_memory_add_and_retrieve():
    wm = WorkingMemory(ceiling=4000)
    wm.add_turn(_turn("ciao", 50))
    assert len(wm.turns()) == 1
    assert wm.total_tokens() == 50


def test_working_memory_compact_drops_oldest_when_over_ceiling():
    wm = WorkingMemory(ceiling=3000)
    for i in range(4):
        wm.add_turn(_turn(f"turno {i}", tokens=1000))
    wm.compact_if_needed()
    assert wm.total_tokens() <= 3000
    assert wm.turns()[-1].content == "turno 3"  # più recente preservato


def test_working_memory_no_compact_when_under_ceiling():
    wm = WorkingMemory(ceiling=5000)
    for i in range(3):
        wm.add_turn(_turn(f"turno {i}", tokens=1000))
    original = list(wm.turns())
    wm.compact_if_needed()
    assert wm.turns() == original


def test_working_memory_with_ceiling_returns_new_instance():
    wm = WorkingMemory(ceiling=4000)
    wm.add_turn(_turn("turno", tokens=500))
    wm2 = wm.with_ceiling(8000)
    assert wm2 is not wm
    assert len(wm2.turns()) == len(wm.turns())


def test_working_memory_with_ceiling_doubled_allows_more_turns():
    # 5 turni da 1000 token ciascuno
    wm = WorkingMemory(ceiling=4000)
    for i in range(5):
        wm.add_turn(_turn(f"t{i}", tokens=1000))

    wm_normal = wm.with_ceiling(4000)
    wm_normal.compact_if_needed()

    wm_retry = wm.with_ceiling(8000)
    wm_retry.compact_if_needed()

    assert len(wm_retry.turns()) > len(wm_normal.turns())


# ── RecallEngine ──────────────────────────────────────────────────────────────

def test_recall_engine_returns_none_for_missing_index(tmp_path):
    engine = RecallEngine(tmp_path / "nonexistent.md")
    assert engine.recall("riunione") is None


def test_recall_engine_returns_matching_lines(tmp_path):
    index = tmp_path / "index.md"
    index.write_text("riunione con Marco martedì\naltra nota senza match", encoding="utf-8")
    engine = RecallEngine(index)
    result = engine.recall("riunione Marco")
    assert result is not None
    assert "riunione" in result


def test_recall_engine_respects_token_budget(tmp_path):
    index = tmp_path / "index.md"
    long_line = "riunione " + "x" * 2000
    index.write_text("\n".join([long_line] * 10), encoding="utf-8")
    engine = RecallEngine(index)
    result = engine.recall("riunione", max_tokens=100)
    assert result is not None
    assert len(result) <= 100 * 4 + 10  # margine minimo
