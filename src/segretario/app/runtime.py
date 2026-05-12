from __future__ import annotations

from segretario.config.loader import load_settings


def get_runtime_settings():
    return load_settings()
