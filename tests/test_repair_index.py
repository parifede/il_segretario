from __future__ import annotations

from datetime import date
from pathlib import Path
import sqlite3

from typer.testing import CliRunner

from segretario.audit import AuditLog
from segretario.cli import app
from segretario.vault.repair import repair_index_apply, repair_index_dry_run


def test_repair_index_dry_run_reports_orphan_knowledge_without_writing_index(tmp_path: Path):
    vault = _make_vault(tmp_path)
    (vault / "knowledge" / "alpha.md").write_text(
        "---\ntitle: Alpha Topic\nstatus: active\n---\n# Alpha Topic\n",
        encoding="utf-8",
    )
    before = (vault / "meta" / "index.md").read_text(encoding="utf-8")

    report = repair_index_dry_run(vault, today=date(2026, 5, 14))

    assert report.path == "output/repair-index-2026-05-14.md"
    assert report.entries == ["- [[Alpha Topic]]"]
    assert (vault / report.path).read_text(encoding="utf-8").count("[[Alpha Topic]]") == 1
    assert (vault / "meta" / "index.md").read_text(encoding="utf-8") == before


def test_repair_index_treats_path_alias_links_as_indexed(tmp_path: Path):
    vault = _make_vault(tmp_path)
    (vault / "knowledge" / "nested").mkdir()
    (vault / "knowledge" / "nested" / "alpha.md").write_text(
        "# Alpha Topic\n",
        encoding="utf-8",
    )
    (vault / "meta" / "index.md").write_text(
        "# Index\n\n## Knowledge\n- [[knowledge/nested/alpha|Alpha Topic]] `knowledge/nested/alpha.md`\n",
        encoding="utf-8",
    )

    report = repair_index_dry_run(vault, today=date(2026, 5, 14))

    assert report.entries == []


def test_repair_index_apply_adds_orphans_to_index_and_appends_log(tmp_path: Path):
    vault = _make_vault(tmp_path)
    (vault / "knowledge" / "alpha.md").write_text("# Alpha Topic\n", encoding="utf-8")
    (vault / "knowledge" / "beta.md").write_text(
        "---\ntitle: Beta Topic\nstatus: active\n---\n# Ignored Heading\n",
        encoding="utf-8",
    )

    report = repair_index_apply(vault, today=date(2026, 5, 14))

    index = (vault / "meta" / "index.md").read_text(encoding="utf-8")
    log = (vault / "meta" / "log.md").read_text(encoding="utf-8")
    assert report.entries == ["- [[Alpha Topic]]", "- [[Beta Topic]]"]
    assert index.count("## Knowledge") == 1
    assert "- [[Alpha Topic]]" in index
    assert "- [[Beta Topic]]" in index
    assert "- old entry" in log
    assert "- 2026-05-14 repair index -> output/repair-index-apply-2026-05-14.md" in log


def test_repair_index_respects_configured_skip_paths(tmp_path: Path):
    vault = _make_vault(tmp_path)
    (vault / "knowledge" / "visible.md").write_text("# Visible Topic\n", encoding="utf-8")
    (vault / "knowledge" / "private").mkdir()
    (vault / "knowledge" / "private" / "hidden.md").write_text("# Hidden Topic\n", encoding="utf-8")

    report = repair_index_dry_run(
        vault,
        today=date(2026, 5, 14),
        skip_paths=["knowledge/private"],
    )

    assert report.entries == ["- [[Visible Topic]]"]
    assert "Hidden Topic" not in (vault / report.path).read_text(encoding="utf-8")


def test_repair_index_strips_existing_wikilinks_from_titles(tmp_path: Path):
    vault = _make_vault(tmp_path)
    (vault / "knowledge" / "linked-title.md").write_text(
        "# [[Conversazione]] Completa\n",
        encoding="utf-8",
    )

    report = repair_index_dry_run(vault, today=date(2026, 5, 14))

    assert report.entries == ["- [[Conversazione Completa]]"]
    assert "[[[[" not in (vault / report.path).read_text(encoding="utf-8")


def test_repair_index_skips_ambiguous_duplicate_titles(tmp_path: Path):
    vault = _make_vault(tmp_path)
    (vault / "knowledge" / "images").mkdir()
    (vault / "knowledge" / "images" / "a.md").write_text("# Stub Immagine\n", encoding="utf-8")
    (vault / "knowledge" / "images" / "b.md").write_text("# Stub Immagine\n", encoding="utf-8")
    (vault / "knowledge" / "single.md").write_text("# Single Topic\n", encoding="utf-8")

    report = repair_index_dry_run(vault, today=date(2026, 5, 14))

    assert report.entries == ["- [[Single Topic]]"]
    assert "Stub Immagine" not in (vault / report.path).read_text(encoding="utf-8")


def test_repair_index_apply_removes_redundant_plain_title_when_alias_exists(tmp_path: Path):
    vault = _make_vault(tmp_path)
    (vault / "knowledge" / "nested").mkdir()
    (vault / "knowledge" / "nested" / "alpha.md").write_text("# Alpha Topic\n", encoding="utf-8")
    (vault / "meta" / "index.md").write_text(
        "# Index\n\n## Knowledge\n- [[Alpha Topic]]\n"
        "- [[knowledge/nested/alpha|Alpha Topic]] `knowledge/nested/alpha.md`\n",
        encoding="utf-8",
    )

    report = repair_index_apply(vault, today=date(2026, 5, 14))

    index = (vault / "meta" / "index.md").read_text(encoding="utf-8")
    assert report.entries == []
    assert "- [[Alpha Topic]]\n" not in index
    assert "[[knowledge/nested/alpha|Alpha Topic]]" in index


def test_repair_index_cli_routes_through_core_taskboard_and_audit(tmp_path: Path, monkeypatch):
    vault = _make_vault(tmp_path)
    (vault / "knowledge" / "alpha.md").write_text("# Alpha Topic\n", encoding="utf-8")
    config = _write_config(tmp_path, vault)
    monkeypatch.setenv("SEGRETARIO_CONFIG", str(config))

    dry_run = CliRunner().invoke(app, ["repair", "index", "--dry-run"])
    apply = CliRunner().invoke(app, ["repair", "index", "--apply"])

    assert dry_run.exit_code == 0
    assert "Repair index report: output/repair-index-" in dry_run.output
    assert "- [[Alpha Topic]]" in dry_run.output
    assert apply.exit_code == 0
    assert "Repair index apply report: output/repair-index-apply-" in apply.output
    assert "- [[Alpha Topic]]" in (vault / "meta" / "index.md").read_text(encoding="utf-8")
    db = sqlite3.connect(tmp_path / "state" / "taskboard.sqlite")
    rows = db.execute("select command, status from tasks order by id").fetchall()
    assert rows == [("repair.index.dry_run", "completed"), ("repair.index.apply", "completed")]
    assert _audit(tmp_path).verify() is True


def _make_vault(tmp_path: Path) -> Path:
    vault = tmp_path / "vault"
    (vault / "knowledge").mkdir(parents=True)
    (vault / "meta").mkdir()
    (vault / "AGENTS.md").write_text("# AGENTS\n", encoding="utf-8")
    (vault / "meta" / "index.md").write_text(
        "# Index\n\n## Self\n\n## Knowledge\n\n## Output\n",
        encoding="utf-8",
    )
    (vault / "meta" / "log.md").write_text("# Log\n- old entry\n", encoding="utf-8")
    return vault


def _write_config(tmp_path: Path, vault: Path) -> Path:
    config = tmp_path / "segretario.yaml"
    config.write_text(
        f"""
project_name: repair_index_test
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
