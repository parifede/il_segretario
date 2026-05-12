from pathlib import Path

from typer.testing import CliRunner

from segretario.cli import app


def test_search_cli_creates_task_and_audit_records(tmp_path, monkeypatch):
    vault = tmp_path / "vault"
    (vault / "knowledge").mkdir(parents=True)
    (vault / "knowledge" / "Topic.md").write_text("alpha\n", encoding="utf-8")
    config = _write_config(tmp_path, vault)
    monkeypatch.setenv("SEGRETARIO_CONFIG", str(config))

    result = CliRunner().invoke(app, ["search", "alpha"])

    assert result.exit_code == 0
    assert "knowledge/Topic.md" in result.output
    assert (tmp_path / "state" / "taskboard.sqlite").exists()
    assert (tmp_path / "state" / "audit" / "events.jsonl").exists()


def test_ingest_cli_creates_task_and_audit_records(tmp_path, monkeypatch):
    vault = tmp_path / "vault"
    source = vault / "raw" / "articles" / "source.md"
    source.parent.mkdir(parents=True)
    source.write_text("# Source Topic\n\nAlpha.\n", encoding="utf-8")
    config = _write_config(tmp_path, vault)
    monkeypatch.setenv("SEGRETARIO_CONFIG", str(config))

    result = CliRunner().invoke(app, ["ingest", "raw/articles/source.md", "--auto"])

    assert result.exit_code == 0
    assert "knowledge/source-topic.md" in result.output
    assert (tmp_path / "state" / "taskboard.sqlite").exists()
    assert (tmp_path / "state" / "audit" / "events.jsonl").exists()


def _write_config(tmp_path: Path, vault: Path) -> Path:
    config = tmp_path / "segretario.yaml"
    config.write_text(
        f"""
project_name: il_segretario
vault:
  path: "{vault.as_posix()}"
llm:
  provider: ollama
  model: "local-test-model"
  base_url: "http://127.0.0.1:9"
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
