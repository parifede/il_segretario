from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
import re

from segretario.policies.privacy import knowledge_export_decision
from segretario.vault.frontmatter import parse_frontmatter
from segretario.vault.paths import classify_vault_path


class ExternalAnswerDecision(StrEnum):
    ALLOW = "allow"
    PROJECT = "project"
    BLOCK = "block"


@dataclass(frozen=True)
class ExternalAnswer:
    decision: ExternalAnswerDecision
    answer: str
    source_path: str


def prepare_external_answer(
    vault_path: str | Path,
    *,
    source_path: str,
    question: str,
    projection: str | None = None,
) -> ExternalAnswer:
    """Prepare a policy-safe answer for an external agent or copied prompt."""

    del question
    policy = classify_vault_path(source_path)
    if (
        policy.skip
        or policy.no_export
        or source_path.replace("\\", "/").strip("/").startswith("self/")
    ):
        return ExternalAnswer(
            decision=ExternalAnswerDecision.BLOCK,
            answer=f"external answer blocked: no-export path {policy.path}",
            source_path=policy.path,
        )

    path = Path(vault_path) / policy.path
    if not path.exists() or not path.is_file():
        raise FileNotFoundError(f"source path not found: {policy.path}")

    text = path.read_text(encoding="utf-8")
    frontmatter, body = parse_frontmatter(text)
    export_decision = knowledge_export_decision(policy.path, frontmatter=frontmatter)
    if export_decision.export_allowed:
        return ExternalAnswer(
            decision=ExternalAnswerDecision.ALLOW,
            answer=_trim_answer(body),
            source_path=policy.path,
        )

    if projection and projection.strip():
        _reject_no_export_markers(projection)
        return ExternalAnswer(
            decision=ExternalAnswerDecision.PROJECT,
            answer=projection.strip(),
            source_path=policy.path,
        )

    return ExternalAnswer(
        decision=ExternalAnswerDecision.PROJECT,
        answer=f"external answer requires privacy projection for {policy.path}",
        source_path=policy.path,
    )


def _trim_answer(body: str) -> str:
    stripped = body.strip()
    if not stripped:
        return ""
    return stripped[:4000]


def _reject_no_export_markers(projection: str) -> None:
    normalized = projection.replace("\\", "/").casefold()
    forbidden = ("self/", "meta/privacy_map.local.json", "raw/elaborati")
    if any(marker in normalized for marker in forbidden):
        raise ValueError("projection contains no-export path markers")


def sanitize_user_output(value: object, *, debug: bool = False) -> str:
    """Filter user-facing text before CLI display.

    Debug mode may preserve stack frames, but secrets are still redacted.
    """

    text = "" if value is None else str(value)
    text = _redact_oauth_tokens(text)
    text = _redact_sensitive_absolute_paths(text)
    if not debug:
        text = _remove_stack_trace(text)
    text = _redact_privacy_map_contents(text)
    return text


def _remove_stack_trace(text: str) -> str:
    if "Traceback (most recent call last):" not in text:
        return text
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    last_line = lines[-1] if lines else "internal error"
    if last_line.startswith('File "'):
        last_line = "internal error"
    return f"error: {last_line}"


def _redact_oauth_tokens(text: str) -> str:
    patterns = [
        r"ya29\.[A-Za-z0-9._~-]+",
        r"(?i)(Bearer\s+)[A-Za-z0-9._~+/=-]+",
        r"(?i)((?:access|refresh|id)_token\s*[:=]\s*)[^\s,;]+",
    ]
    redacted = text
    redacted = re.sub(patterns[0], "[REDACTED_OAUTH_TOKEN]", redacted)
    redacted = re.sub(patterns[1], r"\1[REDACTED_OAUTH_TOKEN]", redacted)
    redacted = re.sub(patterns[2], r"\1[REDACTED_OAUTH_TOKEN]", redacted)
    return redacted


def _redact_sensitive_absolute_paths(text: str) -> str:
    path_pattern = r"[A-Za-z]:[\\/][^\s\"'<>|]+"

    def replace(match: re.Match[str]) -> str:
        path = match.group(0)
        normalized = path.replace("\\", "/").casefold()
        sensitive_markers = (
            "/secrets/",
            "/self/",
            "/meta/privacy_map.local.json",
            "/raw/elaborati/",
        )
        if any(marker in normalized for marker in sensitive_markers):
            return "[LOCAL_PRIVATE_PATH]"
        return path

    return re.sub(path_pattern, replace, text)


def _redact_privacy_map_contents(text: str) -> str:
    normalized = text.replace("\\", "/").casefold()
    if "meta/privacy_map.local.json" not in normalized:
        return text
    if "{" not in text and "[" not in text:
        return text
    marker_match = re.search(r"meta/privacy_map\.local\.json", text, flags=re.IGNORECASE)
    if marker_match is None:
        return text
    prefix = text[: marker_match.start()]
    marker = text[marker_match.start() : marker_match.end()]
    return f"{prefix}{marker}: [REDACTED_LOCAL_PRIVACY_MAP]"
