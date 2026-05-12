from __future__ import annotations

from typing import Any

import yaml


def parse_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    if not text.startswith("---\n"):
        return {}, text

    closing = text.find("\n---\n", 4)
    if closing == -1:
        return {}, text

    raw_metadata = text[4:closing]
    metadata = yaml.safe_load(raw_metadata) or {}
    if not isinstance(metadata, dict):
        raise ValueError("frontmatter must be a YAML mapping")

    return metadata, text[closing + len("\n---\n") :]


def render_frontmatter(metadata: dict[str, Any], body: str) -> str:
    if not metadata:
        return body

    header = yaml.safe_dump(metadata, sort_keys=False, allow_unicode=True)
    return f"---\n{header}---\n{body}"
