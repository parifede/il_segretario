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


def test_extract_queue_creates_pdf_tasks_without_duplicates(tmp_path: Path, monkeypatch):
    vault = _make_vault(tmp_path)
    (vault / "raw" / "first.pdf").write_bytes(_simple_pdf_bytes("First PDF"))
    (vault / "raw" / "second.pdf").write_bytes(_simple_pdf_bytes("Second PDF"))
    config = _write_config(tmp_path, vault)
    monkeypatch.setenv("SEGRETARIO_CONFIG", str(config))
    runner = CliRunner()

    first = runner.invoke(app, ["extract", "queue", "--kind", "pdf", "--limit", "1"])
    second = runner.invoke(app, ["extract", "queue", "--kind", "pdf", "--limit", "1"])
    third = runner.invoke(app, ["extract", "queue", "--kind", "pdf", "--limit", "1"])

    assert first.exit_code == 0
    assert "Queued extract tasks: 1" in first.output
    assert "raw/first.pdf" in first.output
    assert second.exit_code == 0
    assert "raw/second.pdf" in second.output
    assert third.exit_code == 0
    assert "Queued extract tasks: 0" in third.output
    db = sqlite3.connect(tmp_path / "state" / "taskboard.sqlite")
    rows = db.execute("select command, status from tasks order by id").fetchall()
    assert rows == [("extract.pdf", "queued"), ("extract.pdf", "queued")]
    assert _audit(tmp_path).verify() is True


def test_agents_run_extracts_queued_pdf_to_raw_extracted(tmp_path: Path, monkeypatch):
    vault = _make_vault(tmp_path)
    (vault / "raw" / "course.pdf").write_bytes(_simple_pdf_bytes("Hello PDF extraction"))
    config = _write_config(tmp_path, vault)
    monkeypatch.setenv("SEGRETARIO_CONFIG", str(config))
    runner = CliRunner()
    runner.invoke(app, ["extract", "queue", "--kind", "pdf", "--limit", "1"])

    result = runner.invoke(app, ["agents", "run", "--limit", "1"])

    assert result.exit_code == 0
    assert "Executed: 1" in result.output
    assert "extract.pdf completed -> raw/extracted/course.md" in result.output
    extracted = vault / "raw" / "extracted" / "course.md"
    assert extracted.exists()
    text = extracted.read_text(encoding="utf-8")
    assert "source_path: raw/course.pdf" in text
    assert "extracted_from: pdf" in text
    assert "privacy: private" in text
    assert "cloud_ok: false" in text
    assert "Hello PDF extraction" in text
    assert _audit(tmp_path).verify() is True


def test_pdf_extraction_rejects_elaborati_path(tmp_path: Path, monkeypatch):
    vault = _make_vault(tmp_path)
    (vault / "raw" / "elaborati" / "secret.pdf").write_bytes(_simple_pdf_bytes("SECRET"))
    config = _write_config(tmp_path, vault)
    monkeypatch.setenv("SEGRETARIO_CONFIG", str(config))

    result = CliRunner().invoke(
        app,
        ["extract", "pdf", "raw/elaborati/secret.pdf"],
    )

    assert result.exit_code == 1
    assert "outside skipped paths" in result.output
    assert not (vault / "raw" / "extracted").exists()
    assert "SECRET" not in result.output


def test_pdf_extraction_rejects_parent_traversal_without_output(tmp_path: Path, monkeypatch):
    vault = _make_vault(tmp_path)
    config = _write_config(tmp_path, vault)
    monkeypatch.setenv("SEGRETARIO_CONFIG", str(config))

    result = CliRunner().invoke(app, ["extract", "pdf", "../outside.pdf"])

    assert result.exit_code == 1
    assert "parent traversal" in result.output
    assert not (vault / "raw" / "extracted").exists()


def test_agents_run_revalidates_tampered_extract_payload_skip_path(tmp_path: Path, monkeypatch):
    vault = _make_vault(tmp_path)
    (vault / "raw" / "safe.pdf").write_bytes(_simple_pdf_bytes("SAFE"))
    (vault / "raw" / "elaborati" / "secret.pdf").write_bytes(_simple_pdf_bytes("SECRET"))
    config = _write_config(tmp_path, vault)
    monkeypatch.setenv("SEGRETARIO_CONFIG", str(config))
    runner = CliRunner()
    runner.invoke(app, ["extract", "queue", "--kind", "pdf", "--limit", "1"])
    payload = tmp_path / "state" / "task_payloads" / "task-1.json"
    data = payload.read_text(encoding="utf-8").replace("raw/safe.pdf", "raw/elaborati/secret.pdf")
    payload.write_text(data, encoding="utf-8")

    result = runner.invoke(app, ["agents", "run", "--limit", "1"])

    assert result.exit_code == 0
    assert "extract.pdf failed" in result.output
    assert not (vault / "raw" / "extracted").exists()
    assert "SECRET" not in result.output
    db = sqlite3.connect(tmp_path / "state" / "taskboard.sqlite")
    status = db.execute("select status from tasks where id = 1").fetchone()[0]
    assert status == "failed"
    assert _audit(tmp_path).verify() is True


def test_pdf_extraction_refuses_large_pdf_content_free(tmp_path: Path, monkeypatch):
    vault = _make_vault(tmp_path)
    (vault / "raw" / "large.pdf").write_bytes(b"%PDF" + (b"SECRET_BODY" * 3_000_000))
    config = _write_config(tmp_path, vault)
    monkeypatch.setenv("SEGRETARIO_CONFIG", str(config))

    result = CliRunner().invoke(app, ["extract", "pdf", "raw/large.pdf"])

    assert result.exit_code == 1
    assert "size limit" in result.output
    assert "SECRET_BODY" not in result.output
    assert not (vault / "raw" / "extracted").exists()


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


def _simple_pdf_bytes(text: str) -> bytes:
    escaped = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    return (
        "%PDF-1.4\n"
        "1 0 obj << /Type /Catalog /Pages 2 0 R >> endobj\n"
        "2 0 obj << /Type /Pages /Kids [3 0 R] /Count 1 >> endobj\n"
        "3 0 obj << /Type /Page /Parent 2 0 R /Contents 4 0 R >> endobj\n"
        f"4 0 obj << /Length {len(escaped) + 41} >> stream\n"
        "BT /F1 12 Tf 72 720 Td "
        f"({escaped}) Tj"
        " ET\n"
        "endstream endobj\n"
        "trailer << /Root 1 0 R >>\n%%EOF\n"
    ).encode("latin-1")


def _audit(tmp_path: Path) -> AuditLog:
    return AuditLog(
        events_path=tmp_path / "state" / "audit" / "events.jsonl",
        chain_path=tmp_path / "state" / "audit" / "hash_chain.jsonl",
    )
