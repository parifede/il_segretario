from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import click
import yaml

from segretario.config.settings import Settings


class ConfigFileNotFound(click.ClickException, FileNotFoundError):
    pass


def project_root() -> Path:
    return Path(__file__).resolve().parents[3]


def default_config_path() -> Path:
    return project_root() / "segretario.yaml"


def load_settings(config_path: Path | str | None = None) -> Settings:
    resolved_config, explicit_config = _select_config_path(config_path)
    data: dict[str, Any] = {}
    loaded_config_path: Path | None = None

    if resolved_config and explicit_config and not resolved_config.exists():
        raise ConfigFileNotFound(f"config file not found: {resolved_config}")

    if resolved_config and resolved_config.exists():
        loaded_config_path = resolved_config
        raw = yaml.safe_load(resolved_config.read_text(encoding="utf-8")) or {}
        if not isinstance(raw, dict):
            raise ValueError(f"Config file must contain a YAML mapping: {resolved_config}")
        data.update(raw)

    _apply_env_overrides(data)
    settings = Settings.model_validate(data)
    settings.loaded_config_path = loaded_config_path
    return settings


def _select_config_path(config_path: Path | str | None) -> tuple[Path | None, bool]:
    if config_path is not None:
        return Path(config_path), True
    env_path = os.getenv("SEGRETARIO_CONFIG")
    if env_path:
        return Path(env_path), True
    return default_config_path(), False


def _apply_env_overrides(data: dict[str, Any]) -> None:
    if vault_path := os.getenv("SEGRETARIO_VAULT_PATH"):
        data.setdefault("vault", {})["path"] = vault_path
    if model := os.getenv("SEGRETARIO_OLLAMA_MODEL"):
        data.setdefault("llm", {})["sync_model"] = model
    if base_url := os.getenv("SEGRETARIO_OLLAMA_BASE_URL"):
        data.setdefault("llm", {})["base_url"] = base_url
