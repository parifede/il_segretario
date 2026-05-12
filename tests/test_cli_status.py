from typer.testing import CliRunner

from segretario.cli import app


def test_status_prints_partial_report_without_crashing(tmp_path, monkeypatch):
    config = tmp_path / "segretario.yaml"
    config.write_text(
        f"""
project_name: il_segretario
vault:
  path: "{(tmp_path / 'missing_vault').as_posix()}"
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
    monkeypatch.setenv("SEGRETARIO_CONFIG", str(config))

    result = CliRunner().invoke(app, ["status"])

    assert result.exit_code == 0
    assert "il_segretario status" in result.output
    assert "Vault check:" in result.output
    assert "missing" in result.output
    assert "LLM:" in result.output
    assert "Ollama:" in result.output
    assert "Google:" in result.output
