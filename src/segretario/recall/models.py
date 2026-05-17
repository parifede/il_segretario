from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any


class RecallEngineState(str, Enum):
    """Stato osservabile del RecallEngine per una specifica query.

    Cinque valori coprono tutti i casi reali:
    - SEMANTIC_READY: tutto ok, query eseguita semanticamente
    - SEMANTIC_DISABLED_PROMPT: semantico disabilitato in config, utente non
      ha ancora visto/rifiutato il wizard. Task 3 mostrerà wizard ATTIVAZIONE.
    - SEMANTIC_DISABLED_DISMISSED: utente ha rifiutato il wizard ("Non più
      chiedermelo"). Nessun wizard, keyword silenzioso permanente.
    - SEMANTIC_UNAVAILABLE_TRANSIENT: semantico abilitato ma in runtime non
      risponde (Ollama down, embedder errore, indice corrotto). Task 3
      mostrerà wizard DOWNGRADE.
    - SEMANTIC_DISABLED_OVERRIDE: utente ha scelto "Non ora" in questo turno;
      vale solo per questa query, wizard riapparirà al prossimo trigger.
    """
    SEMANTIC_READY = "semantic_ready"
    SEMANTIC_DISABLED_PROMPT = "semantic_disabled_prompt"
    SEMANTIC_DISABLED_DISMISSED = "semantic_disabled_dismissed"
    SEMANTIC_UNAVAILABLE_TRANSIENT = "semantic_unavailable_transient"
    SEMANTIC_DISABLED_OVERRIDE = "semantic_disabled_override"


class RecallMode(str, Enum):
    """Modalità effettivamente usata per la query."""
    SEMANTIC = "semantic"
    KEYWORD = "keyword"
    NONE = "none"  # nessuna ricerca eseguita (es. wizard required prima)


class WizardType(str, Enum):
    """Tipo di wizard che Task 3 dovrà mostrare. None se nessuno."""
    ACTIVATION = "activation"   # wizard A: "Vuoi attivare il semantico?"
    DOWNGRADE = "downgrade"     # wizard B: "Semantico non risponde, procedi keyword?"


@dataclass
class RecallHit:
    """Singolo match restituito dal retriever."""
    note_path: str
    score: float
    content_preview: str


@dataclass
class RecallResult:
    """Risultato strutturato di una chiamata a RecallEngine.recall().

    CONTRACT TOWARD TASK 3: All existing fields must remain stable.
    Adding new fields is OK; removing or renaming existing ones is not.

    Task 3 leggerà questo oggetto e deciderà:
    - Se wizard_required è settato: mostrarlo all'utente, raccogliere risposta,
      richiamare RecallEngine con override appropriato.
    - Altrimenti: usare content come risultato finale del recall L3.
    """
    state: RecallEngineState
    mode_used: RecallMode
    content: str | None = None
    hits: list[RecallHit] = field(default_factory=list)
    wizard_required: WizardType | None = None
    wizard_context: dict[str, Any] = field(default_factory=dict)
    # wizard_context conterrà info per costruire il wizard:
    # ACTIVATION: { "description": "...", "performance_note": "...", ... }
    # DOWNGRADE: { "failure_reason": "...", "last_known_good": "...", ... }
    error: str | None = None  # eventuale messaggio di errore tecnico


@dataclass
class ReindexResult:
    """Result of a VaultIndexer.reindex() call."""
    indexed: int = 0
    deleted: int = 0
    skipped_unchanged: int = 0
    errors: list[str] = field(default_factory=list)

    @property
    def indexed_total(self) -> int:
        return self.indexed
