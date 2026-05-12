from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


REQUIRED_FILES = ("AGENTS.md", "meta/index.md", "meta/log.md")
LOCAL_ONLY_PATHS = ("self/", "meta/privacy_map.local.json")


@dataclass(frozen=True)
class VaultPreflightReport:
    ok: bool
    required_files: dict[str, str]
    skip_paths: list[str]
    local_only_paths: list[str]
    notes: list[str]


def run_vault_preflight(
    vault_path: str | Path,
    *,
    skip_paths: list[str] | tuple[str, ...],
) -> VaultPreflightReport:
    """Check vault operating invariants without reading private/raw bodies."""

    vault = Path(vault_path)
    required_files = {
        relative: "ok" if (vault / relative).exists() else "missing"
        for relative in REQUIRED_FILES
    }
    normalized_skip_paths = [_normalize_skip_path(path) for path in skip_paths]
    notes = []

    if not vault.exists():
        notes.append("vault path is missing")
    if "raw/elaborati" not in normalized_skip_paths:
        notes.append("raw/elaborati is not configured as a skip path")

    for relative, status in required_files.items():
        if status != "ok":
            notes.append(f"{relative} is missing")

    return VaultPreflightReport(
        ok=vault.is_dir() and all(status == "ok" for status in required_files.values()),
        required_files=required_files,
        skip_paths=normalized_skip_paths,
        local_only_paths=list(LOCAL_ONLY_PATHS),
        notes=notes,
    )


def _normalize_skip_path(path: str) -> str:
    return path.replace("\\", "/").strip("/")
