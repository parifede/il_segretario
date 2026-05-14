from pathlib import Path

from typer.testing import CliRunner

from segretario.cli import app
from segretario.vault.relink import relink_dry_run


def test_cli_search_and_stats_honor_configured_skip_paths(tmp_path: Path, monkeypatch):
    vault = _make_vault(tmp_path)
    (vault / ".pytest_cache").mkdir()
    (vault / ".pytest_cache" / "cache.md").write_text("HIDDEN_SKIP_TOKEN\n", encoding="utf-8")
    (vault / "output").mkdir()
    (vault / "output" / "report.md").write_text("HIDDEN_OUTPUT_TOKEN\n", encoding="utf-8")
    (vault / "knowledge" / "note.md").write_text("# Note\nVISIBLE_TOKEN\n", encoding="utf-8")
    config = _write_config(tmp_path, vault)
    monkeypatch.setenv("SEGRETARIO_CONFIG", str(config))

    hidden = CliRunner().invoke(app, ["search", "HIDDEN_SKIP_TOKEN"])
    visible = CliRunner().invoke(app, ["search", "VISIBLE_TOKEN"])
    stats = CliRunner().invoke(app, ["stats"])

    assert hidden.exit_code == 0
    assert "No matches found." in hidden.output
    assert visible.exit_code == 0
    assert "knowledge/note.md" in visible.output
    assert stats.exit_code == 0
    assert ".pytest_cache:" not in stats.output
    assert "output:" not in stats.output
    assert "knowledge: 1" in stats.output


def test_relink_dry_run_honors_configured_skip_paths(tmp_path: Path):
    vault = _make_vault(tmp_path)
    (vault / "knowledge" / "source.md").write_text(
        "# Source\n\nThis mentions Output Target.\n",
        encoding="utf-8",
    )
    (vault / "output").mkdir()
    (vault / "output" / "target.md").write_text("# Output Target\n", encoding="utf-8")

    report = relink_dry_run(vault, skip_paths=["output"])

    assert not any("Output Target" in suggestion for suggestion in report.suggestions)


def _make_vault(tmp_path: Path) -> Path:
    vault = tmp_path / "vault"
    (vault / "meta").mkdir(parents=True)
    (vault / "knowledge").mkdir()
    (vault / "raw" / "elaborati").mkdir(parents=True)
    (vault / "AGENTS.md").write_text("# AGENTS\n", encoding="utf-8")
    (vault / "meta" / "index.md").write_text("# Index\n", encoding="utf-8")
    (vault / "meta" / "log.md").write_text("# Log\n", encoding="utf-8")
    return vault


def _write_config(tmp_path: Path, vault: Path) -> Path:
    config = tmp_path / "segretario.yaml"
    config.write_text(
        f"""
project_name: skip_paths_test
vault:
  path: "{vault.as_posix()}"
  skip_paths:
    - raw/elaborati
    - .pytest_cache
    - output
taskboard:
  sqlite_path: "{(tmp_path / 'state' / 'taskboard.sqlite').as_posix()}"
audit:
  events_path: "{(tmp_path / 'state' / 'audit' / 'events.jsonl').as_posix()}"
  hash_chain_path: "{(tmp_path / 'state' / 'audit' / 'hash_chain.jsonl').as_posix()}"
""".strip(),
        encoding="utf-8",
    )
    return config
