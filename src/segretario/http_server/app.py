from __future__ import annotations

import logging
from typing import Any

from fastapi import Depends, FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from segretario.audit.hash_chain import AuditLog
from segretario.config.settings import Settings
from segretario.connectors.ollama_client import OllamaClient
from segretario.flow02.recall_engine import RecallEngine
from segretario.http_server.auth import make_bearer_dependency
from segretario.http_server.context_handler import build_context_projection
from segretario.http_server.models import ContextRequestBody, TaskRequestBody
from segretario.flow02.character_store import CharacterStore
from segretario.http_server.task_handler import AuditUnavailableError, build_task_response_real

logger = logging.getLogger(__name__)


def _err(error: str, status_code: int) -> JSONResponse:
    return JSONResponse({"ok": False, "error": error}, status_code=status_code)


def create_app(
    settings: Settings,
    *,
    recall_engine: RecallEngine | None = None,
    audit_log: AuditLog | None = None,
    llm_client: OllamaClient | None = None,
) -> FastAPI:
    """FastAPI app factory. Rejects non-local bind at construction time.

    recall_engine, audit_log, and llm_client are injectable for testing;
    built from settings when not provided.
    """
    if settings.http_server.host not in ("127.0.0.1", "localhost"):
        raise RuntimeError(
            f"http_server.host must be 127.0.0.1 or localhost (local-only); "
            f"got {settings.http_server.host!r}"
        )

    _recall = recall_engine or RecallEngine(
        index_path=settings.vault.path / "meta" / "index.md",
        recall_settings=settings.recall,
    )
    _audit = audit_log or AuditLog(
        events_path=settings.audit.events_path,
        chain_path=settings.audit.hash_chain_path,
    )
    _llm = llm_client or OllamaClient(
        model=settings.llm.sync_model,
        base_url=settings.llm.base_url,
        timeout_seconds=settings.llm.timeout_seconds,
        think=False,
        keep_alive=settings.llm.sync_model_keep_alive,
    )
    _character = CharacterStore.from_config(settings.character.identity)

    app = FastAPI(
        title="il_segretario HTTP",
        version="3b-2",
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
            result = build_context_projection(body.secretary_context_request, _recall, _audit, _llm)
            return JSONResponse(result)
        except ValueError:
            return _err("invalid_request", status.HTTP_400_BAD_REQUEST)

    @app.post("/task")
    async def task(
        body: TaskRequestBody,
        _auth: None = Depends(auth_dep),
    ) -> JSONResponse:
        try:
            result = build_task_response_real(
                body.secretary_task_request,
                _audit,
                _llm,
                _character,
            )
            return JSONResponse(result)
        except ValueError:
            return _err("invalid_request", status.HTTP_400_BAD_REQUEST)
        except AuditUnavailableError:
            return _err("audit_unavailable", status.HTTP_503_SERVICE_UNAVAILABLE)

    return app
