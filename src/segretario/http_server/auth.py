from __future__ import annotations

import os
from typing import Annotated

from fastapi import Header, HTTPException, status

from segretario.config.settings import HTTPServerSettings


def make_bearer_dependency(settings: HTTPServerSettings):
    """Returns a FastAPI dependency that validates Bearer token."""

    async def require_bearer_token(
        authorization: Annotated[str | None, Header(alias="Authorization")] = None,
    ) -> None:
        expected = os.getenv(settings.auth_token_env, "").strip()

        if not expected:
            # Dev mode: auth disabled
            return

        if not authorization or not authorization.startswith("Bearer "):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={"ok": False, "error": "invalid_auth"},
            )

        token = authorization[len("Bearer "):]
        if token != expected:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={"ok": False, "error": "invalid_auth"},
            )

    return require_bearer_token
