from datetime import date
from pathlib import Path

from typer.testing import CliRunner

from segretario.cli import app
from segretario.vault.relink import relink_apply, relink_dry_run


def test_relink_dry_run_suggests_missing_links_without_modifying_pages(tmp_path: Path):
    vault = tmp_path / "vault"
    alpha = vault / "knowledge" / "alpha.md"
    beta = vault / "knowledge" / "beta.md"
    alpha.parent.mkdir(parents=True)
    alpha.write_text("# Alpha\n\nBeta is related.\n", encoding="utf-8")
    beta.write_text("# Beta\n\nAlpha is related.\n", encoding="utf-8")
    before = alpha.read_text(encoding="utf-8")

    report = relink_dry_run(vault, today=date(2026, 5, 12))

    assert report.path == "output/relink-2026-05-12.md"
    assert "knowledge/alpha.md -> [[Beta]]" in report.suggestions
    assert "knowledge/beta.md -> [[Alpha]]" in report.suggestions
    assert alpha.read_text(encoding="utf-8") == before
    assert (vault / report.path).exists()


def test_relink_dry_run_skips_raw_elaborati(tmp_path: Path):
    vault = tmp_path / "vault"
    (vault / "knowledge").mkdir(parents=True)
    (vault / "raw" / "elaborati").mkdir(parents=True)
    (vault / "knowledge" / "alpha.md").write_text("# Alpha\n\nNo refs.\n", encoding="utf-8")
    (vault / "raw" / "elaborati" / "beta.md").write_text(
        "# Beta\n\nAlpha should not see this.\n",
        encoding="utf-8",
    )

    report = relink_dry_run(vault, today=date(2026, 5, 12))

    rendered = (vault / report.path).read_text(encoding="utf-8")
    assert "raw/elaborati" not in rendered
    assert "Beta" not in "\n".join(report.suggestions)


def test_relink_dry_run_skips_ambiguous_duplicate_titles(tmp_path: Path):
    vault = tmp_path / "vault"
    (vault / "knowledge" / "images").mkdir(parents=True)
    (vault / "knowledge" / "note.md").write_text(
        "# Note\n\nStub Immagine appears here.\n",
        encoding="utf-8",
    )
    (vault / "knowledge" / "images" / "a.md").write_text(
        "# Stub Immagine\n\nA.\n",
        encoding="utf-8",
    )
    (vault / "knowledge" / "images" / "b.md").write_text(
        "# Stub Immagine\n\nB.\n",
        encoding="utf-8",
    )

    report = relink_dry_run(vault, today=date(2026, 5, 12))

    assert "knowledge/note.md -> [[Stub Immagine]]" not in report.suggestions


def test_relink_cli_writes_report_through_core(tmp_path: Path, monkeypatch):
    vault = tmp_path / "vault"
    (vault / "knowledge").mkdir(parents=True)
    (vault / "knowledge" / "alpha.md").write_text("# Alpha\n\nBeta.\n", encoding="utf-8")
    (vault / "knowledge" / "beta.md").write_text("# Beta\n\nAlpha.\n", encoding="utf-8")
    config = _write_config(tmp_path, vault)
    monkeypatch.setenv("SEGRETARIO_CONFIG", str(config))

    result = CliRunner().invoke(app, ["relink", "--dry-run"])

    assert result.exit_code == 0
    assert "Relink report: output/relink-" in result.output
    assert "knowledge/alpha.md -> [[Beta]]" in result.output
    assert (tmp_path / "state" / "taskboard.sqlite").exists()
    assert (tmp_path / "state" / "audit" / "events.jsonl").exists()


def test_relink_cli_accepts_source_scope_for_dry_run(tmp_path: Path, monkeypatch):
    vault = tmp_path / "vault"
    (vault / "knowledge").mkdir(parents=True)
    (vault / "output").mkdir(parents=True)
    (vault / "knowledge" / "alpha.md").write_text("# Alpha\n\nBeta.\n", encoding="utf-8")
    (vault / "knowledge" / "beta.md").write_text("# Beta\n\nAlpha.\n", encoding="utf-8")
    (vault / "output" / "digest.md").write_text("# Digest\n\nAlpha.\n", encoding="utf-8")
    config = _write_config(tmp_path, vault)
    monkeypatch.setenv("SEGRETARIO_CONFIG", str(config))

    result = CliRunner().invoke(app, ["relink", "knowledge/", "--dry-run"])

    assert result.exit_code == 0
    assert "knowledge/alpha.md -> [[Beta]]" in result.output
    assert "output/digest.md -> [[Alpha]]" not in result.output


def test_relink_apply_respects_source_scope(tmp_path: Path):
    vault = tmp_path / "vault"
    alpha = vault / "knowledge" / "alpha.md"
    beta = vault / "knowledge" / "beta.md"
    nested = vault / "knowledge" / "nested" / "gamma.md"
    alpha.parent.mkdir(parents=True)
    nested.parent.mkdir(parents=True)
    alpha.write_text("# Alpha\n\nBeta.\n", encoding="utf-8")
    beta.write_text("# Beta\n\nAlpha.\n", encoding="utf-8")
    nested.write_text("# Gamma\n\nAlpha and Beta.\n", encoding="utf-8")

    report = relink_apply(vault, source_scope="knowledge/nested", today=date(2026, 5, 12))

    assert report.suggestions == [
        "knowledge/nested/gamma.md -> [[Alpha]]",
        "knowledge/nested/gamma.md -> [[Beta]]",
    ]
    assert "[[Alpha]] and [[Beta]]" in nested.read_text(encoding="utf-8")
    assert "[[Beta]]" not in alpha.read_text(encoding="utf-8")


def test_relink_apply_updates_only_unambiguous_knowledge_links(tmp_path: Path):
    vault = tmp_path / "vault"
    alpha = vault / "knowledge" / "alpha.md"
    beta = vault / "knowledge" / "beta.md"
    output = vault / "output" / "daily-digest.md"
    output.parent.mkdir(parents=True)
    alpha.parent.mkdir(parents=True)
    alpha.write_text("# Alpha\n\nBeta is related.\n", encoding="utf-8")
    beta.write_text("# Beta\n\nAlpha is related.\n", encoding="utf-8")
    output.write_text("# Daily Digest\n\nAlpha appears here.\n", encoding="utf-8")

    report = relink_apply(vault, today=date(2026, 5, 12))

    assert report.path == "output/relink-apply-2026-05-12.md"
    assert "knowledge/alpha.md -> [[Beta]]" in report.suggestions
    assert "knowledge/beta.md -> [[Alpha]]" in report.suggestions
    assert "Beta is related" not in alpha.read_text(encoding="utf-8")
    assert "[[Beta]] is related" in alpha.read_text(encoding="utf-8")
    assert "[[Alpha]] appears here" not in output.read_text(encoding="utf-8")


def test_relink_apply_cli_routes_through_core_and_writes_pages(
    tmp_path: Path,
    monkeypatch,
):
    vault = tmp_path / "vault"
    (vault / "knowledge").mkdir(parents=True)
    (vault / "knowledge" / "alpha.md").write_text("# Alpha\n\nBeta.\n", encoding="utf-8")
    (vault / "knowledge" / "beta.md").write_text("# Beta\n\nAlpha.\n", encoding="utf-8")
    config = _write_config(tmp_path, vault)
    monkeypatch.setenv("SEGRETARIO_CONFIG", str(config))

    result = CliRunner().invoke(app, ["relink", "--apply"])

    assert result.exit_code == 0
    assert "Relink apply report: output/relink-apply-" in result.output
    assert "[[Beta]]" in (vault / "knowledge" / "alpha.md").read_text(encoding="utf-8")
    assert (tmp_path / "state" / "taskboard.sqlite").exists()
    assert (tmp_path / "state" / "audit" / "events.jsonl").exists()


def _write_config(tmp_path: Path, vault: Path) -> Path:
    config = tmp_path / "segretario.yaml"
    config.write_text(
        f"""
project_name: il_segretario
vault:
  path: "{vault.as_posix()}"
taskboard:
  sqlite_path: "{(tmp_path / 'state' / 'taskboard.sqlite').as_posix()}"
audit:
  events_path: "{(tmp_path / 'state' / 'audit' / 'events.jsonl').as_posix()}"
  hash_chain_path: "{(tmp_path / 'state' / 'audit' / 'hash_chain.jsonl').as_posix()}"
google:
  credentials_path: "{(tmp_path / 'secrets' / 'google' / 'credentials.json').as_posix()}"
  token_path: "{(tmp_path / 'secrets' / 'google' / 'token.json').as_posix()}"
""".strip(),
        encoding="utf-8",
    )
    return config
