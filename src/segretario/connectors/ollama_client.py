from __future__ import annotations

import httpx


class LocalModelUnavailable(RuntimeError):
    """Raised when the configured local model backend cannot be reached."""


class OllamaClient:
    def __init__(
        self,
        *,
        model: str,
        base_url: str,
        timeout_seconds: float = 120,
        client: httpx.Client | None = None,
    ) -> None:
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self._client = client or httpx.Client(timeout=timeout_seconds)

    def generate(self, prompt: str, system: str | None = None) -> str:
        payload: dict[str, object] = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
        }
        if system:
            payload["system"] = system

        try:
            response = self._client.post(f"{self.base_url}/api/generate", json=payload)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise LocalModelUnavailable(
                f"Ollama is unreachable at {self.base_url}"
            ) from exc

        data = response.json()
        generated = data.get("response", "")
        if not isinstance(generated, str):
            raise LocalModelUnavailable("Ollama returned an invalid response payload")
        return generated
