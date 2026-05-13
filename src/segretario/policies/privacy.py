from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath
import re
from typing import Any, Mapping


@dataclass(frozen=True)
class KnowledgeExportDecision:
    local_only: bool
    export_allowed: bool


@dataclass(frozen=True)
class WebQueryDecision:
    allowed: bool
    requires_projection: bool


@dataclass(frozen=True)
class PrivacyProjection:
    text: str
    replacements: dict[str, list[str]]


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


def project_private_context(text: str) -> PrivacyProjection:
    projected = text
    replacements: dict[str, list[str]] = {}
    counters: dict[str, int] = {}

    def token(kind: str) -> str:
        index = counters.get(kind, 0)
        counters[kind] = index + 1
        suffix = chr(ord("A") + index)
        return f"{kind}_TOKEN_{suffix}"

    def replace_pattern(pattern: str, kind: str, value: str | None = None, *, flags: int = 0) -> None:
        nonlocal projected

        def repl(match: re.Match[str]) -> str:
            original = match.group(0)
            replacement = value or token(kind)
            replacements.setdefault(kind, []).append(original)
            return replacement

        projected = re.sub(pattern, repl, projected, flags=flags)

    replace_pattern(r"\b[A-Z]{2}\d{2}[A-Z0-9]{11,30}\b", "BANK")
    replace_pattern(r"\b[A-Z]{6}\d{2}[A-Z]\d{2}[A-Z]\d{3}[A-Z]\b", "ID")
    replace_pattern(r"\b[A-Z]{2}\d{3}[A-Z]{2}\b", "VEHICLE")
    replace_pattern(r"\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b", "EMAIL")
    replace_pattern(r"(?:\+?\d{1,3}[\s.-]?)?(?:\d[\s.-]?){8,12}\d\b", "PHONE")

    projected = re.sub(
        r"\b(\d{1,2})\s+anni\b",
        lambda match: _age_band(int(match.group(1))),
        projected,
        flags=re.IGNORECASE,
    )
    projected = re.sub(
        r"\b(?:guadagna|reddito|income)\s+(?:€\s*)?(\d{4,7})(?:\s*euro)?\b",
        lambda match: f"guadagna {_income_band(int(match.group(1)))}",
        projected,
        flags=re.IGNORECASE,
    )
    replace_pattern(
        r"\bVia\s+[A-ZÀ-Ý][\wÀ-ÿ'\-]*(?:\s+\d+[A-Za-z]?)?,\s*([A-ZÀ-Ý][\wÀ-ÿ'\-]*)",
        "LOCATION",
        flags=re.IGNORECASE,
    )
    projected = re.sub(
        r"LOCATION_TOKEN_[A-Z]",
        lambda match: _location_from_replacement(text) or "geographic area",
        projected,
    )
    projected = re.sub(
        r"\blavora come\s+.+?\s+presso\b",
        "lavora come technical role band presso",
        projected,
        flags=re.IGNORECASE,
    )
    projected = re.sub(
        r"\b(?:diabete tipo 2|diabete|depressione|ansia|tumore|cancro|ipertensione)\b",
        "broad health category",
        projected,
        flags=re.IGNORECASE,
    )
    replace_pattern(
        r"\b(?:Acme\s+S\.p\.A\.|[A-ZÀ-Ý][\wÀ-ÿ'&.-]+(?:\s+(?:S\.p\.A\.|S\.r\.l\.|Ltd|Inc|LLC)))",
        "ORG",
    )
    replace_pattern(r"\b[A-ZÀ-Ý][a-zà-ÿ]+(?:\s+[A-ZÀ-Ý][a-zà-ÿ]+)+\b", "PERSON")

    return PrivacyProjection(text=projected, replacements=replacements)


def _normalize(path: str) -> PurePosixPath:
    normalized = PurePosixPath(path.replace("\\", "/").strip("/"))
    if ".." in normalized.parts:
        raise ValueError("vault path cannot contain parent traversal")
    return normalized


def _age_band(age: int) -> str:
    lower = age // 10 * 10
    upper = lower + 9
    return f"{lower}-{upper} age band"


def _income_band(amount: int) -> str:
    if amount < 20000:
        return "income band under 20k"
    if amount < 40000:
        return "income band 20k-40k"
    if amount < 60000:
        return "income band 40k-60k"
    if amount < 100000:
        return "income band 60k-100k"
    return "income band over 100k"


def _location_from_replacement(text: str) -> str | None:
    match = re.search(
        r"\bVia\s+[A-ZÀ-Ý][\wÀ-ÿ'\-]*(?:\s+\d+[A-Za-z]?)?,\s*([A-ZÀ-Ý][\wÀ-ÿ'\-]*)",
        text,
        flags=re.IGNORECASE,
    )
    if not match:
        return None
    return f"area urbana di {match.group(1)}"
