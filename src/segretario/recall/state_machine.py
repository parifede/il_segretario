from __future__ import annotations
import logging
from typing import TYPE_CHECKING

from segretario.recall.models import RecallEngineState, WizardType
from segretario.recall.health import check_embedder, check_store

if TYPE_CHECKING:
    from segretario.recall.embedder import OllamaEmbedder
    from segretario.recall.vector_store import VectorStore
    from segretario.config.settings import RecallSettings

logger = logging.getLogger(__name__)


class RecallStateMachine:
    """Determines the recall state for a given query.

    Inputs:
    - settings: RecallSettings (enabled, user_dismissed_wizard, ...)
    - embedder + store: used for health checks when enabled=True
    - override_mode per call: "keyword_once" or "keyword_proceed"

    Output of evaluate(): tuple (state, wizard_required, wizard_context)
    """

    def __init__(
        self,
        settings: RecallSettings,
        embedder: OllamaEmbedder | None,
        store: VectorStore | None,
    ) -> None:
        self._settings = settings
        self._embedder = embedder
        self._store = store

    def evaluate(
        self, override_mode: str | None = None
    ) -> tuple[RecallEngineState, WizardType | None, dict]:
        """Determine state for a single query.

        Decision logic (in order):

        1. override_mode == "keyword_once"
           → SEMANTIC_DISABLED_OVERRIDE, wizard=None, ctx={}

        2. override_mode == "keyword_proceed"
           → SEMANTIC_UNAVAILABLE_TRANSIENT, wizard=None, ctx={}
           (caller will use keyword, no wizard needed)

        3. settings.enabled is False AND settings.user_dismissed_wizard is True
           → SEMANTIC_DISABLED_DISMISSED, wizard=None, ctx={}

        4. settings.enabled is False AND settings.user_dismissed_wizard is False
           → SEMANTIC_DISABLED_PROMPT, wizard=WizardType.ACTIVATION,
             ctx=_activation_context()

        5. settings.enabled is True:
           a. check_embedder + check_store: both ok
              → SEMANTIC_READY, wizard=None, ctx={}
           b. any health check fails
              → SEMANTIC_UNAVAILABLE_TRANSIENT, wizard=WizardType.DOWNGRADE,
                ctx=_downgrade_context(failure_reason)
        """
        # Step 1: per-call overrides
        if override_mode == "keyword_once":
            return RecallEngineState.SEMANTIC_DISABLED_OVERRIDE, None, {}

        if override_mode == "keyword_proceed":
            return RecallEngineState.SEMANTIC_UNAVAILABLE_TRANSIENT, None, {}

        # Step 2: semantic disabled
        if not self._settings.enabled:
            if self._settings.user_dismissed_wizard:
                return RecallEngineState.SEMANTIC_DISABLED_DISMISSED, None, {}
            return (
                RecallEngineState.SEMANTIC_DISABLED_PROMPT,
                WizardType.ACTIVATION,
                self._activation_context(),
            )

        # Step 3: semantic enabled — check health
        failure_reasons: list[str] = []

        if self._embedder is None:
            failure_reasons.append("Embedder not initialized")
        else:
            embedder_ok, embedder_reason = check_embedder(self._embedder)
            if not embedder_ok:
                failure_reasons.append(embedder_reason)

        if self._store is None:
            failure_reasons.append("Vector store not initialized")
        else:
            store_ok, store_reason = check_store(self._store)
            if not store_ok:
                failure_reasons.append(store_reason)

        if failure_reasons:
            combined = "; ".join(failure_reasons)
            logger.warning("Recall health check failed: %s", combined)
            return (
                RecallEngineState.SEMANTIC_UNAVAILABLE_TRANSIENT,
                WizardType.DOWNGRADE,
                self._downgrade_context(combined),
            )

        return RecallEngineState.SEMANTIC_READY, None, {}

    def _activation_context(self) -> dict:
        return {
            "description": (
                "Il recall semantico ti permette di cercare nella tua memoria "
                "con parafrasi e sinonimi, non solo parole esatte."
            ),
            "performance_note": (
                "La prima indicizzazione richiede ~5-10 minuti per il tuo vault."
            ),
            "model": self._settings.embedding_model,
        }

    def _downgrade_context(self, failure_reason: str) -> dict:
        return {
            "failure_reason": failure_reason,
            "diagnostic_hint": (
                "Verifica che Ollama sia in esecuzione. Comando: ollama list"
            ),
        }
