from __future__ import annotations

from dataclasses import asdict
from typing import Any

from segretario.agents.base import BaseAgent
from segretario.policies.output_guard import prepare_external_answer
from segretario.policies.privacy import knowledge_export_decision, web_query_decision
from segretario.vault.paths import classify_vault_path


class SecurityAgent(BaseAgent):
    def run(self, request: object) -> dict[str, Any]:
        payload = self.payload(request)
        action = self.command(request, payload)

        if action in {"classify_path", "security.path"}:
            policy = classify_vault_path(
                str(payload["path"]),
                operation=str(payload.get("operation", "read")),
            )
            data = asdict(policy)
            data["export_allowed"] = policy.export_allowed
            return data

        if action == "knowledge.export":
            return asdict(
                knowledge_export_decision(
                    str(payload["path"]),
                    frontmatter=payload.get("frontmatter"),
                )
            )

        if action == "web.query":
            return asdict(web_query_decision(context_privacy=str(payload["context_privacy"])))

        if action == "external.answer":
            return asdict(
                prepare_external_answer(
                    payload["vault_path"],
                    source_path=str(payload["source_path"]),
                    question=str(payload["question"]),
                    projection=(
                        str(payload["projection"])
                        if payload.get("projection") is not None
                        else None
                    ),
                )
            )

        raise ValueError(f"unsupported security action: {action}")
