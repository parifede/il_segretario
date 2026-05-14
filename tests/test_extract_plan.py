from __future__ import annotations

from datetime import date
from pathlib import Path
import sqlite3

from typer.testing import CliRunner

from segretario.audit import AuditLog
from segretario.cli import app
from segretario.tools.extractor_tool import plan_extraction


def test_extract_plan_classifies_rich_sources_without_reading_elaborati(tmp_path: Path):
    vault = _make_vault(tmp_path)
    (vault / "raw" / "course.pdf").write_bytes(b"%PDF")
    (vault / "raw" / "image.png").write_bytes(b"\x89PNG")
    (vault / "raw" / "sheet.xlsx").write_bytes(b"PK")
    (vault / "raw" / "deck.pptx").write_bytes(b"PK")
    (vault / "raw" / "changes.patch").write_text("diff --git a/a b/a\n", encoding="utf-8")
    (vault / "raw" / "bundle.zip").write_bytes(b"PK")
    (vault / "raw" / "notes.md").write_text("# Notes\n", encoding="utf-8")
    (vault / "raw" / "elaborati" / "secret.pdf").write_bytes(b"SECRET")

    report = plan_extraction(vault, today=date(2026, 5, 14), skip_paths=["raw/elaborati"])

    rendered = (vault / report.path).read_text(encoding="utf-8")
    assert report.path == "output/extract-plan-2026-05-14.md"
    assert "- raw/course.pdf -> extract_candidate: pdf text extraction candidate" in report.items
    assert "- raw/image.png -> extract_candidate: image OCR or metadata extraction candidate" in report.items
    assert "- raw/sheet.xlsx -> extract_candidate: spreadsheet/table extraction candidate" in report.items
    assert "- raw/deck.pptx -> extract_candidate: presentation text extraction candidate" in report.items
    assert "- raw/changes.patch -> extract_candidate: patch text extraction candidate" in report.items
    assert "- raw/bundle.zip -> review_before_extract: archive/bundle requires explicit expansion policy" in report.items
    assert not any("raw/notes.md" in item for item in report.items)
    assert "raw/elaborati/secret.pdf" not in rendered
    assert "SECRET" not in rendered


def test_extract_plan_skips_sources_already_ingested_from_log(tmp_path: Path):
    vault = _make_vault(tmp_path)
    (vault / "raw" / "old.pdf").write_bytes(b"%PDF")
    (vault / "raw" / "new.pdf").write_bytes(b"%PDF")
    (vault / "meta" / "log.md").write_text(
        "# Log\n- 2026-05-14 ingest raw/old.pdf -> knowledge/old.md\n",
        encoding="utf-8",
    )

    report = plan_extraction(vault, today=date(2026, 5, 14), skip_paths=["raw/elaborati"])

    rendered = "\n".join(report.items)
    assert "raw/old.pdf" not in rendered
    assert "- raw/new.pdf -> extract_candidate: pdf text extraction candidate" in rendered


def test_extract_plan_cli_routes_through_core_taskboard_and_audit(
    tmp_path: Path,
    monkeypatch,
):
    vault = _make_vault(tmp_path)
    (vault / "raw" / "course.pdf").write_bytes(b"%PDF")
    config = _write_config(tmp_path, vault)
    monkeypatch.setenv("SEGRETARIO_CONFIG", str(config))

    result = CliRunner().invoke(app, ["extract", "plan"])

    assert result.exit_code == 0
    assert "Extract plan: output/extract-plan-" in result.output
    assert "raw/course.pdf -> extract_candidate" in result.output
    db = sqlite3.connect(tmp_path / "state" / "taskboard.sqlite")
    rows = db.execute("select command, status from tasks order by id").fetchall()
    assert rows == [("extract.plan", "completed")]
    assert _audit(tmp_path).verify() is True


def _make_vault(tmp_path: Path) -> Path:
    vault = tmp_path / "vault"
    (vault / "raw" / "elaborati").mkdir(parents=True)
    (vault / "knowledge").mkdir(parents=True)
    (vault / "meta").mkdir()
    (vault / "AGENTS.md").write_text("# AGENTS\n", encoding="utf-8")
    (vault / "meta" / "index.md").write_text("# Index\n", encoding="utf-8")
    (vault / "meta" / "log.md").write_text("# Log\n", encoding="utf-8")
    return vault


def _write_config(tmp_path: Path, vault: Path) -> Path:
    config = tmp_path / "segretario.yaml"
    config.write_text(
        f"""
project_name: extract_plan_test
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
