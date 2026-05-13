from pathlib import Path

import pytest
from typer.testing import CliRunner

from segretario.config.loader import load_settings
from segretario.cli import app


runner = CliRunner()


def test_load_settings_raises_for_explicit_missing_config(monkeypatch):
    monkeypatch.delenv("SEGRETARIO_CONFIG", raising=False)
    monkeypatch.delenv("SEGRETARIO_VAULT_PATH", raising=False)
    monkeypatch.delenv("SEGRETARIO_OLLAMA_MODEL", raising=False)
    monkeypatch.delenv("SEGRETARIO_OLLAMA_BASE_URL", raising=False)

    with pytest.raises(FileNotFoundError, match="config file not found"):
        load_settings(config_path=Path("missing.yaml"))


def test_load_settings_raises_for_env_missing_config(monkeypatch):
    monkeypatch.setenv("SEGRETARIO_CONFIG", "missing-from-env.yaml")

    with pytest.raises(FileNotFoundError, match="config file not found"):
        load_settings()


def test_cli_reports_missing_explicit_config_without_traceback():
    result = runner.invoke(app, ["config", "show", "--config", "missing-cli.yaml"])

    assert result.exit_code == 1
    assert "config file not found: missing-cli.yaml" in result.output
    assert "Traceback" not in result.output


def test_environment_overrides_config_file(tmp_path, monkeypatch):
    config = tmp_path / "segretario.yaml"
    config.write_text(
        """
project_name: il_segretario
vault:
  path: "E:\\\\from_config"
llm:
  model: "from-config"
  base_url: "http://127.0.0.1:11434"
""".strip(),
        encoding="utf-8",
    )
    monkeypatch.setenv("SEGRETARIO_VAULT_PATH", "E:\\from_env")
    monkeypatch.setenv("SEGRETARIO_OLLAMA_MODEL", "from-env")

    settings = load_settings(config_path=config)

    assert settings.vault.path == Path("E:\\from_env")
    assert settings.llm.model == "from-env"
