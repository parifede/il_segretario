from pathlib import Path

from typer.testing import CliRunner

import segretario.cli as cli


def test_query_cli_refuses_without_matching_pages(tmp_path, monkeypatch):
    vault = tmp_path / "vault"
    vault.mkdir()
    monkeypatch.setenv("SEGRETARIO_CONFIG", str(_write_config(tmp_path, vault)))

    result = CliRunner().invoke(cli.app, ["query", "alpha"])

    assert result.exit_code == 0
    assert "No relevant vault pages found" in result.output


def test_query_cli_prints_query_result(tmp_path, monkeypatch):
    vault = tmp_path / "vault"
    vault.mkdir()
    monkeypatch.setenv("SEGRETARIO_CONFIG", str(_write_config(tmp_path, vault)))

    class Result:
        answer = "Local answer [[Topic]]"
        sources = ["[[Topic]]"]

    def fake_query_vault(vault_path, question, *, llm):
        assert vault_path == vault
        assert question == "alpha"
        return Result()

    monkeypatch.setattr(cli, "query_vault", fake_query_vault)

    result = CliRunner().invoke(cli.app, ["query", "alpha"])

    assert result.exit_code == 0
    assert "Local answer [[Topic]]" in result.output


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
