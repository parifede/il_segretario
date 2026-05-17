from __future__ import annotations
import logging
from pathlib import Path

from segretario.config.settings import RecallSettings
from segretario.recall.models import RecallEngineState, RecallMode, RecallResult, WizardType
from segretario.recall.embedder import OllamaEmbedder
from segretario.recall.embedding_retriever import EmbeddingRetriever
from segretario.recall.keyword_search import keyword_search
from segretario.recall.sqlite_vec_store import SqliteVecStore
from segretario.recall.state_machine import RecallStateMachine

logger = logging.getLogger(__name__)


class RecallEngine:
    """L3: Semantic recall with 5-state machine.

    Facade: delegates to segretario.recall module. Exposes two API levels:
    - recall(query, ...): new structured API returning RecallResult.
      Use this from Task-3-aware callers that can handle wizards.
    - recall_simple(query, max_tokens): legacy str|None API for callers
      that cannot handle wizards (ContextBroker, CLI, batch jobs).
    - keyword_search(query, max_tokens): explicit keyword search,
      called by Task 3 wizard handlers ("Non ora" / "Procedi keyword").
    """

    def __init__(
        self,
        index_path: Path,
        recall_settings: RecallSettings | None = None,
    ) -> None:
        self._index_path = index_path
        self._settings = recall_settings or RecallSettings()

        self._embedder: OllamaEmbedder | None = None
        self._store: SqliteVecStore | None = None
        self._retriever: EmbeddingRetriever | None = None

        if self._settings.enabled:
            try:
                self._embedder = OllamaEmbedder(
                    model=self._settings.embedding_model,
                    base_url=self._settings.ollama_base_url,
                    timeout_seconds=60,
                )
                self._store = SqliteVecStore(
                    db_path=self._settings.db_path,
                    embedding_model=self._settings.embedding_model,
                )
                # index_path is meta/index.md → parent = meta/ → parent = vault root
                vault_path = index_path.parent.parent
                self._retriever = EmbeddingRetriever(
                    vault_path=vault_path,
                    store=self._store,
                    embedder=self._embedder,
                )
            except Exception as exc:
                logger.warning(
                    "RecallEngine: failed to initialize semantic components: %s. "
                    "Falling back to degraded mode.",
                    exc,
                )

        self._state_machine = RecallStateMachine(
            settings=self._settings,
            embedder=self._embedder,
            store=self._store,
        )

    def recall(
        self,
        query: str,
        override_mode: str | None = None,
        k: int | None = None,
        max_tokens: int = 4000,
    ) -> RecallResult:
        """Structured recall API. Returns RecallResult with state + optional content.

        Task-3-aware callers read wizard_required to decide whether to show a wizard.
        """
        effective_k = k or self._settings.default_k
        state, wizard, wizard_ctx = self._state_machine.evaluate(override_mode)

        # States that don't run semantic search
        if state in (
            RecallEngineState.SEMANTIC_DISABLED_PROMPT,
            RecallEngineState.SEMANTIC_DISABLED_DISMISSED,
            RecallEngineState.SEMANTIC_DISABLED_OVERRIDE,
        ):
            # DISMISSED and OVERRIDE → run keyword silently
            if state in (RecallEngineState.SEMANTIC_DISABLED_DISMISSED,
                         RecallEngineState.SEMANTIC_DISABLED_OVERRIDE):
                kw_content = keyword_search(self._index_path, query, max_tokens)
                return RecallResult(
                    state=state,
                    mode_used=RecallMode.KEYWORD,
                    content=kw_content,
                    wizard_required=wizard,
                    wizard_context=wizard_ctx,
                )
            # DISABLED_PROMPT → return with wizard (no content)
            return RecallResult(
                state=state,
                mode_used=RecallMode.NONE,
                content=None,
                wizard_required=wizard,
                wizard_context=wizard_ctx,
            )

        # UNAVAILABLE_TRANSIENT
        if state == RecallEngineState.SEMANTIC_UNAVAILABLE_TRANSIENT:
            if wizard is None:
                # override_mode="keyword_proceed": run keyword
                kw_content = keyword_search(self._index_path, query, max_tokens)
                return RecallResult(
                    state=state,
                    mode_used=RecallMode.KEYWORD,
                    content=kw_content,
                    wizard_required=None,
                    wizard_context={},
                )
            # wizard=DOWNGRADE: return with wizard (no content yet)
            return RecallResult(
                state=state,
                mode_used=RecallMode.NONE,
                content=None,
                wizard_required=wizard,
                wizard_context=wizard_ctx,
            )

        # SEMANTIC_READY → run semantic search
        try:
            hits = self._retriever.search(query, k=effective_k)  # type: ignore[union-attr]
            content = _hits_to_text(hits) if hits else None
            return RecallResult(
                state=state,
                mode_used=RecallMode.SEMANTIC,
                content=content,
                hits=hits,
                wizard_required=None,
                wizard_context={},
            )
        except Exception as exc:
            logger.warning("RecallEngine: semantic search failed: %s", exc)
            return RecallResult(
                state=RecallEngineState.SEMANTIC_UNAVAILABLE_TRANSIENT,
                mode_used=RecallMode.NONE,
                content=None,
                wizard_required=WizardType.DOWNGRADE,
                wizard_context={"failure_reason": str(exc)},
                error=str(exc),
            )

    def recall_simple(self, query: str, max_tokens: int = 4000) -> str | None:
        """Legacy str|None API. Does NOT trigger wizards.

        If the system requires a wizard, returns None silently.
        Use for: ContextBroker, CLI, batch jobs — anywhere without wizard UI.
        """
        result = self.recall(query, max_tokens=max_tokens)
        if result.wizard_required is not None:
            return None
        return result.content

    def keyword_search(self, query: str, max_tokens: int = 4000) -> str | None:
        """Explicit keyword search. Called by Task 3 when user chooses
        'Non ora' (ACTIVATION wizard) or 'Procedi keyword' (DOWNGRADE wizard).
        """
        return keyword_search(self._index_path, query, max_tokens)


def _hits_to_text(hits: list) -> str:
    """Format RecallHit list as text block for LLM context."""
    parts = []
    for hit in hits:
        section = f" [§ {hit.section_title}]" if hit.section_title else ""
        parts.append(f"### {hit.note_path}{section} (chunk {hit.chunk_index}, score: {hit.score:.3f})\n{hit.content_preview}")
    return "\n\n".join(parts)
