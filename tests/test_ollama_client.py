import httpx
import pytest

from segretario.connectors.ollama_client import LocalModelUnavailable, OllamaClient


def test_ollama_client_posts_non_streaming_generate_request():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["payload"] = request.read()
        return httpx.Response(200, json={"response": "Local answer", "done": True})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    ollama = OllamaClient(
        model="local-model",
        base_url="http://127.0.0.1:11434",
        client=client,
    )

    response = ollama.generate("Question?", system="System prompt")

    assert response == "Local answer"
    assert captured["url"] == "http://127.0.0.1:11434/api/generate"
    assert b'"model":"local-model"' in captured["payload"]
    assert b'"prompt":"Question?"' in captured["payload"]
    assert b'"system":"System prompt"' in captured["payload"]
    assert b'"stream":false' in captured["payload"]


def test_ollama_client_raises_clear_unavailable_error():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no listener", request=request)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    ollama = OllamaClient(
        model="local-model",
        base_url="http://127.0.0.1:11434",
        client=client,
    )

    with pytest.raises(LocalModelUnavailable, match="Ollama is unreachable"):
        ollama.generate("Question?")
