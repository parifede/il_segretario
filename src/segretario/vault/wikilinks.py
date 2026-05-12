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
