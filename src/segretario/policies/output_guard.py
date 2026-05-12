from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

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
