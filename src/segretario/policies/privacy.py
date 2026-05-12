from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any, Mapping


@dataclass(frozen=True)
class KnowledgeExportDecision:
    local_only: bool
    export_allowed: bool


@dataclass(frozen=True)
class WebQueryDecision:
    allowed: bool
    requires_projection: bool


def knowledge_export_decision(
    path: str,
    *,
    frontmatter: Mapping[str, Any] | None = None,
) -> KnowledgeExportDecision:
    frontmatter = frontmatter or {}
    is_knowledge = _normalize(path).parts[:1] == ("knowledge",)
    explicitly_public = frontmatter.get("privacy") == "public"
    cloud_ok = frontmatter.get("cloud_ok") is True
    can_export = is_knowledge and explicitly_public and cloud_ok

    return KnowledgeExportDecision(local_only=not can_export, export_allowed=can_export)


def web_query_decision(*, context_privacy: str) -> WebQueryDecision:
    requires_projection = context_privacy == "private"
    return WebQueryDecision(
        allowed=not requires_projection,
        requires_projection=requires_projection,
    )


def _normalize(path: str) -> PurePosixPath:
    normalized = PurePosixPath(path.replace("\\", "/").strip("/"))
    if ".." in normalized.parts:
        raise ValueError("vault path cannot contain parent traversal")
    return normalized
