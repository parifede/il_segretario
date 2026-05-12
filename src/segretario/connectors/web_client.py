from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlparse

import httpx


class PrivacyProjectionRequired(ValueError):
    """Raised when a web query depends on private context without projection."""


@dataclass(frozen=True)
class WebResponse:
    url: str
    text: str
    content_type: str


class WebConnector:
    """Controlled local web connector.

    The connector accepts public HTTP(S) URLs and privacy-safe query payloads only.
    It does not receive raw private vault context.
    """

    def fetch_url(self, url: str, *, timeout_seconds: float = 20.0) -> WebResponse:
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"}:
            raise ValueError("web connector only supports http and https URLs")

        response = httpx.get(url, timeout=timeout_seconds, follow_redirects=True)
        response.raise_for_status()
        return WebResponse(
            url=str(response.url),
            text=response.text,
            content_type=response.headers.get("content-type", ""),
        )

    def prepare_query(
        self,
        query: str,
        *,
        context_privacy: str = "public",
        projection: str | None = None,
    ) -> dict[str, object]:
        clean_query = query.strip()
        clean_projection = projection.strip() if isinstance(projection, str) else None

        if context_privacy == "private":
            if not clean_projection:
                raise PrivacyProjectionRequired("private web query requires privacy projection")
            _reject_no_export_markers(clean_projection)
            return {
                "query": clean_projection,
                "context_privacy": "projected",
                "projection_applied": True,
            }

        _reject_no_export_markers(clean_query)
        return {
            "query": clean_query,
            "context_privacy": "public",
            "projection_applied": False,
        }


def _reject_no_export_markers(text: str) -> None:
    normalized = text.replace("\\", "/").casefold()
    blocked = ("self/", "meta/privacy_map.local.json")
    if any(marker in normalized for marker in blocked):
        raise ValueError("web query payload contains no-export path markers")
