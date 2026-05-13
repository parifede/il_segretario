from __future__ import annotations

from pathlib import Path
from typing import Any

from segretario.agents.base import BaseAgent
from segretario.vault.index_log import append_log, ensure_meta_index


class WikiMaintainerAgent(BaseAgent):
    allowed_actions = frozenset({"meta.index.ensure", "meta.log.append"})
    allowed_tools = frozenset({"MarkdownTool", "VaultTool"})

    def run(self, request: object) -> dict[str, Any]:
        payload = self.payload(request)
        action = self.require_allowed_action(self.command(request, payload))
        vault_path = self.require_vault_path(payload)

        if action == "meta.index.ensure":
            path = ensure_meta_index(vault_path)
            return {"path": _relative_path(path, vault_path)}

        if action == "meta.log.append":
            entry = payload.get("entry")
            if not isinstance(entry, str) or not entry.strip():
                raise ValueError("meta.log.append requires a non-empty entry")
            path = append_log(vault_path, entry)
            return {"path": _relative_path(path, vault_path)}

        raise ValueError(f"unsupported wiki maintenance action: {action}")


def _relative_path(path: Path, vault_path: object) -> str:
    return path.relative_to(Path(vault_path)).as_posix()
