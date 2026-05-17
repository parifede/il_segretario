from __future__ import annotations

import logging
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from segretario.config.settings import Settings
from segretario.http_server.auth import make_bearer_dependency
from segretario.http_server.models import ContextRequestBody, TaskRequestBody
from segretario.http_server.stub_responses import build_context_response, build_task_response

logger = logging.getLogger(__name__)


def _err(error: str, status_code: int) -> JSONResponse:
    return JSONResponse({"ok": False, "error": error}, status_code=status_code)


def create_app(settings: Settings) -> FastAPI:
    """FastAPI app factory. Rejects non-local bind at construction time."""
    if settings.http_server.host not in ("127.0.0.1", "localhost"):
        raise RuntimeError(
            f"http_server.host must be 127.0.0.1 or localhost (local-only); "
            f"got {settings.http_server.host!r}"
        )

    app = FastAPI(
        title="il_segretario HTTP",
        version="3b-1-stub",
        docs_url=None,
        redoc_url=None,
    )

    auth_dep = make_bearer_dependency(settings.http_server)

    # ---------------------------------------------------------------------------
    # Custom exception handlers to mirror Node stub error format
    # ---------------------------------------------------------------------------

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        if exc.status_code == 405:
            return _err("method_not_allowed", 405)
        if exc.status_code == 404:
            return _err("not_found", 404)
        if exc.status_code == 401:
            detail = exc.detail
            if isinstance(detail, dict):
                return JSONResponse(detail, status_code=401)
            return _err("invalid_auth", 401)
        return JSONResponse({"ok": False, "error": str(exc.detail)}, status_code=exc.status_code)

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
        return _err("invalid_request", 422)

    # ---------------------------------------------------------------------------
    # Routes
    # ---------------------------------------------------------------------------

    @app.get("/health")
    async def health() -> dict[str, Any]:
        return {"status": "ok"}

    @app.post("/context")
    async def context(
        body: ContextRequestBody,
        _auth: None = Depends(auth_dep),
    ) -> JSONResponse:
        try:
            return JSONResponse(build_context_response(body.model_dump()))
        except ValueError as exc:
            return _err("invalid_request", status.HTTP_400_BAD_REQUEST)

    @app.post("/task")
    async def task(
        body: TaskRequestBody,
        _auth: None = Depends(auth_dep),
    ) -> JSONResponse:
        try:
            return JSONResponse(build_task_response(body.model_dump()))
        except ValueError:
            return _err("invalid_request", status.HTTP_400_BAD_REQUEST)

    return app
