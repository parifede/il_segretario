from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath


@dataclass(frozen=True)
class VaultPathPolicy:
    path: str
    skip: bool = False
    local_only: bool = False
    no_export: bool = False
    requires_confirmation: bool = False
    requires_explicit_profile_update: bool = False

    @property
    def export_allowed(self) -> bool:
        return not self.skip and not self.local_only and not self.no_export


def classify_vault_path(path: str, *, operation: str = "read") -> VaultPathPolicy:
    normalized = _normalize(path)
    parts = PurePosixPath(normalized).parts

    if _starts_with(parts, ("raw", "elaborati")):
        return VaultPathPolicy(path=normalized, skip=True, local_only=True)

    if parts == ("meta", "privacy_map.local.json"):
        return VaultPathPolicy(path=normalized, local_only=True, no_export=True)

    if parts and parts[0] == "self":
        is_profile_write = operation == "write" and _is_profile_path(parts)
        return VaultPathPolicy(
            path=normalized,
            local_only=True,
            requires_confirmation=is_profile_write,
            requires_explicit_profile_update=is_profile_write,
        )

    if parts and parts[0] == "output":
        return VaultPathPolicy(path=normalized, local_only=True)

    return VaultPathPolicy(path=normalized)


def matches_configured_skip_path(path: str, skip_paths: list[str] | tuple[str, ...] | None) -> bool:
    normalized = _normalize(path)
    for skip_path in skip_paths or ():
        normalized_skip = _normalize(str(skip_path))
        if not normalized_skip:
            continue
        if normalized == normalized_skip or normalized.startswith(f"{normalized_skip}/"):
            return True
    return False


def _normalize(path: str) -> str:
    normalized = path.replace("\\", "/").strip("/")
    if ".." in PurePosixPath(normalized).parts:
        raise ValueError("vault path cannot contain parent traversal")
    return normalized


def _starts_with(parts: tuple[str, ...], prefix: tuple[str, ...]) -> bool:
    return parts[: len(prefix)] == prefix


def _is_profile_path(parts: tuple[str, ...]) -> bool:
    return len(parts) >= 2 and parts[1].split(".", 1)[0] == "profile"
