"""Tests for segretario.recall.embedder (OllamaEmbedder)."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from segretario.recall.embedder import EmbedderError, OllamaEmbedder


def _make_embed_response(dims: int = 1024) -> MagicMock:
    resp = MagicMock()
    resp.embeddings = [[float(i % 10) / 10 for i in range(dims)]]
    return resp


# ---------------------------------------------------------------------------
# test 1
# ---------------------------------------------------------------------------

def test_embedder_embeds_text():
    """Mock ollama.Client.embed; verify returns list[float] of 1024 dims."""
    embedder = OllamaEmbedder()
    with patch.object(embedder._client, "embed", return_value=_make_embed_response(1024)) as mock_embed:
        result = embedder.embed("hello world")

    mock_embed.assert_called_once()
    assert isinstance(result, list)
    assert len(result) == 1024
    assert all(isinstance(v, float) for v in result)


# ---------------------------------------------------------------------------
# test 2
# ---------------------------------------------------------------------------

def test_embedder_handles_ollama_down():
    """Mock embed to raise ConnectionError; verify EmbedderError is raised."""
    embedder = OllamaEmbedder()
    with patch.object(embedder._client, "embed", side_effect=ConnectionError("refused")):
        with pytest.raises(EmbedderError):
            embedder.embed("hello")


# ---------------------------------------------------------------------------
# test 3
# ---------------------------------------------------------------------------

def test_embedder_health_check_true_when_ok():
    """Mock embed returns valid response; health_check() → True."""
    embedder = OllamaEmbedder()
    with patch("ollama.Client.embed", return_value=_make_embed_response(1024)):
        result = embedder.health_check()
    assert result is True


# ---------------------------------------------------------------------------
# test 4
# ---------------------------------------------------------------------------

def test_embedder_health_check_false_on_error():
    """Mock raises ConnectionError; health_check() → False."""
    embedder = OllamaEmbedder()
    with patch("ollama.Client.embed", side_effect=ConnectionError("refused")):
        result = embedder.health_check()
    assert result is False


# ---------------------------------------------------------------------------
# test: context-length error detection
# ---------------------------------------------------------------------------

def test_embedder_raises_context_too_long_on_400():
    """Ollama 400 ResponseError → EmbedderContextTooLongError raised."""
    import ollama
    from segretario.recall.embedder import EmbedderContextTooLongError

    embedder = OllamaEmbedder()
    error = ollama.ResponseError("context length exceeded", 400)
    with patch.object(embedder._client, "embed", side_effect=error):
        with pytest.raises(EmbedderContextTooLongError):
            embedder.embed("some text")


def test_embedder_non_400_raises_plain_embedder_error():
    """Non-400 Ollama error → EmbedderError but NOT EmbedderContextTooLongError."""
    import ollama
    from segretario.recall.embedder import EmbedderContextTooLongError

    embedder = OllamaEmbedder()
    error = ollama.ResponseError("model not found", 404)
    with patch.object(embedder._client, "embed", side_effect=error):
        with pytest.raises(EmbedderError) as exc_info:
            embedder.embed("some text")
    assert not isinstance(exc_info.value, EmbedderContextTooLongError)
