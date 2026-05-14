from __future__ import annotations

from pathlib import Path

from segretario.vault.index_log import append_log, ensure_meta_index


class VaultTool:
    """Vault metadata side-effect wrapper."""

    def ensure_meta_index(self, vault_path: str | Path) -> Path:
        return ensure_meta_index(vault_path)

    def append_log(self, vault_path: str | Path, entry: str) -> Path:
        return append_log(vault_path, entry)
