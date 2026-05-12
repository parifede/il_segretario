from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from segretario.tools.search_tool import SearchResult, search_vault
from segretario.vault.frontmatter import parse_frontmatter


class LocalLLM(Protocol):
    def generate(self, prompt: str, system: str | None = None) -> str:
        """Generate a local-model response."""


@dataclass(frozen=True)
class QueryResult:
    answer: str
    sources: list[str]


def query_vault(
    vault_path: Path | str,
    question: str,
    *,
    llm: LocalLLM,
    max_pages: int = 5,
) -> QueryResult:
    vault = Path(vault_path)
    matches = search_vault(vault, question)
    if not matches:
        return QueryResult(
            answer=(
                "No relevant vault pages found. Ingest sources first; "
                "I will not answer this vault query from generic model knowledge."
            ),
            sources=[],
        )

    pages = _unique_pages(matches)[:max_pages]
    contexts: list[str] = []
    sources: list[str] = []
    for relative in pages:
        path = vault / relative
        title, body = _read_page_title_and_body(path)
        citation = f"[[{title}]]"
        sources.append(citation)
        contexts.append(f"Source: {citation}\nPath: {relative}\n\n{body}")

    prompt = _build_prompt(question, contexts)
    answer = llm.generate(prompt, system=_SYSTEM_PROMPT).strip()
    answer = _ensure_sources(answer, sources)
    return QueryResult(answer=answer, sources=sources)


_SYSTEM_PROMPT = (
    "You are il_segretario, a local-only Obsidian vault custodian. "
    "Answer only from the provided vault context. If the context is insufficient, say so. "
    "Cite sources using Obsidian wikilinks."
)


def _unique_pages(matches: list[SearchResult]) -> list[str]:
    pages: list[str] = []
    seen: set[str] = set()
    for match in matches:
        if match.path not in seen:
            seen.add(match.path)
            pages.append(match.path)
    return pages


def _read_page_title_and_body(path: Path) -> tuple[str, str]:
    text = path.read_text(encoding="utf-8")
    metadata, body = parse_frontmatter(text)
    title = metadata.get("title")
    if isinstance(title, str) and title.strip():
        return title.strip(), body
    return path.stem, body


def _build_prompt(question: str, contexts: list[str]) -> str:
    joined_context = "\n\n---\n\n".join(contexts)
    return (
        "Vault context follows. Use only this context.\n\n"
        f"{joined_context}\n\n"
        f"Question: {question}\n"
        "Answer with concise prose and cite relevant pages as [[Page]]."
    )


def _ensure_sources(answer: str, sources: list[str]) -> str:
    missing = [source for source in sources if source not in answer]
    if not missing:
        return answer
    return f"{answer}\n\nSources: {', '.join(sources)}"
