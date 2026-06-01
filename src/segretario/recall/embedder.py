from __future__ import annotations

import logging

import ollama

logger = logging.getLogger(__name__)


class EmbedderError(Exception):
    """Raised when embedding fails. Message should be suitable for wizard_context["failure_reason"]."""


class EmbedderContextTooLongError(EmbedderError):
    """Raised when text exceeds the embedder's context window (Ollama 400 response)."""


class OllamaEmbedder:
    """Ollama embedding client using mxbai-embed-large (1024-dim by default)."""

    def __init__(
        self,
        model: str = "mxbai-embed-large",
        base_url: str = "http://127.0.0.1:11434",
        timeout_seconds: int = 60,
    ) -> None:
        self._model: str = model
        self._base_url: str = base_url
        self._timeout_seconds: int = timeout_seconds
        self._client: ollama.Client = ollama.Client(host=base_url, timeout=timeout_seconds)

    def embed(self, text: str) -> list[float]:
        """Return embedding vector. Raises EmbedderError on any failure."""
        if len(text) > 8000:
            logger.warning(
                "Text length %d chars exceeds 8000; mxbai-embed-large may truncate.",
                len(text),
            )
        try:
            response = self._client.embed(model=self._model, input=text)
            # ollama Python client >= 0.4: response.embeddings is Sequence[Sequence[float]]
            if not response.embeddings:
                raise EmbedderError("Ollama returned empty embedding response")
            return list(response.embeddings[0])
        except ollama.ResponseError as exc:
            if exc.status_code == 400:
                raise EmbedderContextTooLongError(f"Ollama context exceeded (400): {exc}") from exc
            raise EmbedderError(f"Ollama model error: {exc}") from exc
        except Exception as exc:
            raise EmbedderError(
                f"Ollama not reachable at {self._base_url}: {exc}"
            ) from exc

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Embed each text individually. Skips (with WARNING) on single-item failure.

        Idempotent: safe to retry. Returns only successful embeddings in order.
        Items that fail are logged at WARNING level and skipped (caller recovers via indexer hash diff).
        """
        results: list[list[float]] = []
        for i, text in enumerate(texts):
            try:
                results.append(self.embed(text))
            except EmbedderError as exc:
                logger.warning("embed_batch: item %d failed, skipping: %s", i, exc)
        return results

    def health_check(self) -> bool:
        """Return True if Ollama is reachable and the model responds. False on any error.

        Uses a short timeout (~5s) to avoid blocking the state machine.
        """
        try:
            hc_client = ollama.Client(host=self._base_url, timeout=5)
            resp = hc_client.embed(model=self._model, input="test")
            return bool(resp.embeddings)
        except Exception:
            return False
