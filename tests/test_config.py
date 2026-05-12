from pathlib import Path

from segretario.config.loader import load_settings


def test_load_settings_uses_defaults_when_no_config(monkeypatch):
    monkeypatch.delenv("SEGRETARIO_CONFIG", raising=False)
    monkeypatch.delenv("SEGRETARIO_VAULT_PATH", raising=False)
    monkeypatch.delenv("SEGRETARIO_OLLAMA_MODEL", raising=False)
    monkeypatch.delenv("SEGRETARIO_OLLAMA_BASE_URL", raising=False)

    settings = load_settings(config_path=Path("missing.yaml"))

    assert settings.project_name == "il_segretario"
    assert str(settings.vault.path).endswith("vault_dev")
    assert settings.llm.provider == "ollama"


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
