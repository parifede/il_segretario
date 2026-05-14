from __future__ import annotations

from datetime import date
from pathlib import Path
import sqlite3

from typer.testing import CliRunner

from segretario.audit import AuditLog
from segretario.cli import app
from segretario.vault.repair import repair_raw_plan


def test_repair_raw_plan_classifies_unprocessed_raw_without_reading_elaborati(tmp_path: Path):
    vault = _make_vault(tmp_path)
    (vault / "raw" / "articles" / "public.md").write_text("# Public\n", encoding="utf-8")
    (vault / "raw" / ".gitkeep").write_text("", encoding="utf-8")
    (vault / "raw" / "telegram" / "chat.md").parent.mkdir()
    (vault / "raw" / "telegram" / "chat.md").write_text("private-ish\n", encoding="utf-8")
    (vault / "raw" / "books").mkdir()
    (vault / "raw" / "books" / "book.pdf").write_bytes(b"%PDF")
    (vault / "raw" / "elaborati" / "secret.md").write_text(
        "DO_NOT_PLAN_RAW_ELABORATI",
        encoding="utf-8",
    )

    report = repair_raw_plan(vault, today=date(2026, 5, 14), skip_paths=["raw/elaborati"])

    rendered = (vault / report.path).read_text(encoding="utf-8")
    assert report.path == "output/repair-raw-plan-2026-05-14.md"
    assert "- raw/articles/public.md -> ingest_candidate: markdown/text source" in report.items
    assert "- raw/telegram/chat.md -> review_before_ingest: private-looking path" in report.items
    assert "- raw/books/book.pdf -> leave_in_raw: unsupported pdf source" in report.items
    assert not any(".gitkeep" in item for item in report.items)
    assert "raw/elaborati/secret.md" not in rendered
    assert "DO_NOT_PLAN_RAW_ELABORATI" not in rendered


def test_repair_raw_plan_skips_sources_already_referenced_by_knowledge(tmp_path: Path):
    vault = _make_vault(tmp_path)
    (vault / "raw" / "articles" / "processed.md").write_text("# Processed\n", encoding="utf-8")
    (vault / "raw" / "articles" / "new.txt").write_text("New\n", encoding="utf-8")
    (vault / "knowledge" / "processed.md").write_text(
        "---\ntitle: Processed\nsource_path: raw/articles/processed.md\n---\n# Processed\n",
        encoding="utf-8",
    )

    report = repair_raw_plan(vault, today=date(2026, 5, 14), skip_paths=["raw/elaborati"])

    rendered = "\n".join(report.items)
    assert "raw/articles/processed.md" not in rendered
    assert "- raw/articles/new.txt -> ingest_candidate: markdown/text source" in rendered


def test_repair_raw_plan_cli_routes_through_core_taskboard_and_audit(tmp_path: Path, monkeypatch):
    vault = _make_vault(tmp_path)
    (vault / "raw" / "articles" / "public.md").write_text("# Public\n", encoding="utf-8")
    config = _write_config(tmp_path, vault)
    monkeypatch.setenv("SEGRETARIO_CONFIG", str(config))

    result = CliRunner().invoke(app, ["repair", "raw-plan"])

    assert result.exit_code == 0
    assert "Repair raw plan: output/repair-raw-plan-" in result.output
    assert "raw/articles/public.md -> ingest_candidate" in result.output
    db = sqlite3.connect(tmp_path / "state" / "taskboard.sqlite")
    rows = db.execute("select command, status from tasks order by id").fetchall()
    assert rows == [("repair.raw_plan", "completed")]
    assert _audit(tmp_path).verify() is True


def test_repair_raw_plan_cli_limits_user_output_while_report_stays_complete(
    tmp_path: Path,
    monkeypatch,
):
    vault = _make_vault(tmp_path)
    (vault / "raw" / "articles" / "first.md").write_text("# First\n", encoding="utf-8")
    (vault / "raw" / "articles" / "second.md").write_text("# Second\n", encoding="utf-8")
    config = _write_config(tmp_path, vault)
    monkeypatch.setenv("SEGRETARIO_CONFIG", str(config))

    result = CliRunner().invoke(app, ["repair", "raw-plan", "--limit", "1"])

    report = (vault / "output" / "repair-raw-plan-2026-05-14.md")
    assert result.exit_code == 0
    assert "raw/articles/first.md" in result.output
    assert "raw/articles/second.md" not in result.output
    assert "- ... 1 more entries in report" in result.output
    assert "raw/articles/second.md" in report.read_text(encoding="utf-8")


def _make_vault(tmp_path: Path) -> Path:
    vault = tmp_path / "vault"
    (vault / "knowledge").mkdir(parents=True)
    (vault / "raw" / "articles").mkdir(parents=True)
    (vault / "raw" / "elaborati").mkdir(parents=True)
    (vault / "meta").mkdir()
    (vault / "AGENTS.md").write_text("# AGENTS\n", encoding="utf-8")
    (vault / "meta" / "index.md").write_text("# Index\n", encoding="utf-8")
    (vault / "meta" / "log.md").write_text("# Log\n", encoding="utf-8")
    return vault


def _write_config(tmp_path: Path, vault: Path) -> Path:
    config = tmp_path / "segretario.yaml"
    config.write_text(
        f"""
project_name: repair_raw_plan_test
vault:
  path: "{vault.as_posix()}"
  skip_paths:
    - raw/elaborati
taskboard:
  sqlite_path: "{(tmp_path / 'state' / 'taskboard.sqlite').as_posix()}"
audit:
  events_path: "{(tmp_path / 'state' / 'audit' / 'events.jsonl').as_posix()}"
  hash_chain_path: "{(tmp_path / 'state' / 'audit' / 'hash_chain.jsonl').as_posix()}"
""".strip(),
        encoding="utf-8",
    )
    return config


def _audit(tmp_path: Path) -> AuditLog:
    return AuditLog(
        events_path=tmp_path / "state" / "audit" / "events.jsonl",
        chain_path=tmp_path / "state" / "audit" / "hash_chain.jsonl",
    )
