from __future__ import annotations

import re


_WIKILINK_RE = re.compile(r"\[\[([^\]]*)\]\]")


def extract_wikilink_targets(text: str) -> list[str]:
    targets: list[str] = []
    for match in _WIKILINK_RE.finditer(text):
        target = match.group(1).split("|", 1)[0].strip()
        if target:
            targets.append(target)
    return targets


def extract_wikilink_references(text: str) -> set[str]:
    references: set[str] = set()
    for match in _WIKILINK_RE.finditer(text):
        raw = match.group(1)
        target, separator, alias = raw.partition("|")
        target = target.strip()
        alias = alias.strip() if separator else ""
        if target:
            references.add(target)
            if not target.endswith(".md"):
                references.add(f"{target}.md")
            else:
                references.add(target.removesuffix(".md"))
        if alias:
            references.add(alias)
    return references
