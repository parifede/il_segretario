from datetime import date
from pathlib import Path

from typer.testing import CliRunner

from segretario.cli import app
from segretario.vault.relink import relink_dry_run


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
