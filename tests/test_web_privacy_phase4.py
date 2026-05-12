from pathlib import Path

from typer.testing import CliRunner

from segretario.cli import app
from segretario.connectors.web_client import (
    PrivacyProjectionRequired,
    WebConnector,
)


def test_web_connector_requires_projection_for_private_context():
    connector = WebConnector()

    try:
        connector.prepare_query(
            "Find clinics near my exact home address",
            context_privacy="private",
        )
    except PrivacyProjectionRequired as exc:
        assert "privacy projection" in str(exc)
    else:
        raise AssertionError("private context query must require projection")


def test_web_connector_uses_projection_instead_of_raw_private_query():
    connector = WebConnector()

    payload = connector.prepare_query(
        "Find clinics near Via Roma 12 for Mario Rossi",
        context_privacy="private",
        projection="Find clinics in a city district for an adult",
    )

    assert payload["query"] == "Find clinics in a city district for an adult"
    assert payload["context_privacy"] == "projected"
    assert "Via Roma" not in payload["query"]
    assert "Mario Rossi" not in payload["query"]


def test_web_connector_rejects_no_export_path_markers_in_projection():
    connector = WebConnector()

    try:
        connector.prepare_query(
            "public topic",
            context_privacy="private",
            projection="summarize self/profile details",
        )
    except ValueError as exc:
        assert "no-export" in str(exc)
    else:
        raise AssertionError("projection must not contain no-export path markers")


def test_web_cli_private_context_without_projection_waits_confirmation(tmp_path: Path, monkeypatch):
    vault = tmp_path / "vault"
    config = _write_config(tmp_path, vault)
    monkeypatch.setenv("SEGRETARIO_CONFIG", str(config))

    result = CliRunner().invoke(
        app,
        ["web", "Find clinics near my exact home address", "--private-context"],
    )

    assert result.exit_code == 1
    assert "requires privacy projection" in result.output
    assert (tmp_path / "state" / "taskboard.sqlite").exists()
    assert (tmp_path / "state" / "audit" / "events.jsonl").exists()


def test_web_cli_private_context_with_projection_outputs_only_projection(
    tmp_path: Path,
    monkeypatch,
):
    vault = tmp_path / "vault"
    config = _write_config(tmp_path, vault)
    monkeypatch.setenv("SEGRETARIO_CONFIG", str(config))

    result = CliRunner().invoke(
        app,
        [
            "web",
            "Find clinics near Via Roma 12 for Mario Rossi",
            "--private-context",
            "--projection",
            "Find clinics in a city district for an adult",
        ],
    )

    assert result.exit_code == 0
    assert "web query: Find clinics in a city district for an adult" in result.output
    assert "Via Roma" not in result.output
    assert "Mario Rossi" not in result.output


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
