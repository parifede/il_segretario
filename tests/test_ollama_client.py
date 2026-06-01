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


def test_ollama_client_includes_keep_alive_in_payload():
    """keep_alive is sent in the /api/generate payload."""
    import json as _json
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["payload"] = _json.loads(request.read())
        return httpx.Response(200, json={"response": "ok", "done": True})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    ollama = OllamaClient(model="m", base_url="http://127.0.0.1:11434",
                          keep_alive=300, client=client)
    ollama.generate("prompt")
    assert captured["payload"]["keep_alive"] == 300


def test_ollama_client_keep_alive_default_is_minus_one():
    """Default keep_alive is -1 (always resident)."""
    import json as _json
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["payload"] = _json.loads(request.read())
        return httpx.Response(200, json={"response": "ok", "done": True})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    ollama = OllamaClient(model="m", base_url="http://127.0.0.1:11434", client=client)
    ollama.generate("prompt")
    assert captured["payload"]["keep_alive"] == -1


def test_ollama_client_includes_num_predict_when_set():
    """num_predict is sent in the payload when configured."""
    import json as _json
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["payload"] = _json.loads(request.read())
        return httpx.Response(200, json={"response": "ok", "done": True})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    ollama = OllamaClient(model="m", base_url="http://127.0.0.1:11434",
                          num_predict=350, client=client)
    ollama.generate("prompt")
    assert captured["payload"]["num_predict"] == 350


def test_ollama_client_omits_num_predict_by_default():
    """num_predict is absent from payload when not configured (avoids Ollama default override)."""
    import json as _json
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["payload"] = _json.loads(request.read())
        return httpx.Response(200, json={"response": "ok", "done": True})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    ollama = OllamaClient(model="m", base_url="http://127.0.0.1:11434", client=client)
    ollama.generate("prompt")
    assert "num_predict" not in captured["payload"]


def test_ollama_client_includes_num_ctx_in_options_when_set():
    """num_ctx is sent inside payload['options']['num_ctx'] when configured."""
    import json as _json
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["payload"] = _json.loads(request.read())
        return httpx.Response(200, json={"response": "ok", "done": True})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    ollama = OllamaClient(model="m", base_url="http://127.0.0.1:11434",
                          num_ctx=8192, client=client)
    ollama.generate("prompt")
    assert captured["payload"].get("options", {}).get("num_ctx") == 8192


def test_ollama_client_omits_options_num_ctx_by_default():
    """options.num_ctx is absent from payload when num_ctx not configured."""
    import json as _json
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["payload"] = _json.loads(request.read())
        return httpx.Response(200, json={"response": "ok", "done": True})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    ollama = OllamaClient(model="m", base_url="http://127.0.0.1:11434", client=client)
    ollama.generate("prompt")
    assert "num_ctx" not in captured["payload"].get("options", {})
