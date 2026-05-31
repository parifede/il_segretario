# Claude Code — Task 3b-1: HTTP Server stub-equivalent in Python (drop-in replacement)

## Contesto

zarsOS (Node.js) chiama `il_segretario` via HTTP locale per due tipi di
richieste:

- `POST /context` → richiesta di "context projection" (privacy-safe context da
  vault locale)
- `POST /task` → richiesta di esecuzione di task da parte dell'agente locale

Oggi zarsOS chiama uno **stub Node** (`scripts/zarsos-secretary-stub.mjs` lato
zarsOS) che risponde con payload hardcoded. Per Task 3b-1 dobbiamo scrivere
**l'equivalente in Python** che risponde con payload **bit-equivalent allo stub
Node**, niente logica reale ancora (quella arriva in Task 3b-2).

Una volta che Task 3b-1 è verde, zarsOS può fare smoke test S6 contro il
server Python invece dello stub Node — questo è esattamente quello che il
piano di zarsOS richiede.

**Repository:** `e:\il_segretario`. Lavora in un worktree dedicato:

```powershell
cd e:\il_segretario
git worktree add .worktrees/task3b1-http-server -b feature/task3b1-http-server
cd .worktrees/task3b1-http-server
```

## Stato attuale repository

- Master ha Task 1 (commit `43b4533`)
- Task 2 chiuso, su branch `feature/task2-recall-semantic` (commits `516b44a` + `08f9e09`), NON ancora mergeato su master
- Task 3b-1 deve partire da master (Task 2 non è prerequisito per il drop-in stub)

## Riferimenti

I file lato zarsOS che definiscono il contratto sono:

- **`secretaryClient.js`** — client HTTP zarsOS che chiama il_segretario.
  Definisce schema payload, headers, validazione.
- **`zarsos-secretary-stub.mjs`** — stub Node che oggi risponde alle chiamate.
  Il Python deve essere bit-equivalent per response body.

Te li ho incollati come allegati nella conversation. Leggili PRIMA di scrivere
codice.

Decisioni di design già prese:

- **Stack HTTP:** FastAPI (Pydantic già nel progetto via `pydantic-settings`)
- **Porta:** 8722 (su `127.0.0.1`, local-only)
- **Auth:** Bearer token dedicato a il_segretario, env var (non condiviso con
  Gateway zarsOS)
- **Approccio:** stub-first → risposte hardcoded bit-equivalent al Node stub.
  Logica reale arriva in Task 3b-2.

## Cosa fare

### STEP 1 — Aggiungere dipendenze

In `pyproject.toml`, aggiungi:

```toml
dependencies = [
    # ... esistenti ...
    "fastapi>=0.115",
    "uvicorn[standard]>=0.32",
]
```

Esegui `uv sync` per installarle.

### STEP 2 — Configurazione

Aggiungi a `src/segretario/config/settings.py` una sezione `HTTPServerSettings`:

```python
class HTTPServerSettings(BaseSettings):
    enabled: bool = False  # OPT-IN, default OFF
    host: str = "127.0.0.1"
    port: int = 8722
    auth_token_env: str = "IL_SEGRETARIO_HTTP_TOKEN"
    # In Task 3b-1: validate that bind is local-only
    # (127.0.0.1 or localhost), reject any other bind
```

Aggiungila al `Settings` principale come campo `http_server: HTTPServerSettings`.

Aggiungi un esempio nel `segretario.yaml.example`:

```yaml
http_server:
  enabled: false
  host: "127.0.0.1"
  port: 8722
  auth_token_env: "IL_SEGRETARIO_HTTP_TOKEN"
```

### STEP 3 — Modulo HTTP server

Crea `src/segretario/http_server/` (nuovo package), con:

- `__init__.py`
- `app.py` — applicazione FastAPI principale
- `models.py` — Pydantic models per request/response
- `auth.py` — middleware Bearer token validation
- `stub_responses.py` — payload hardcoded equivalenti a `zarsos-secretary-stub.mjs`

#### models.py

Modelli Pydantic per validare/serializzare i payload. Il punto chiave è il
contratto closed-schema imposto da `secretaryClient.js`:

- Body richiesta **deve** avere esattamente UNO di questi root keys:
  - `secretary_context_request` (oggetto non vuoto)
  - `secretary_task_request` (oggetto non vuoto)
- Niente campi extra al root
- Niente chiavi che iniziano con `rawPrivate` / `raw_private` / `raw-private`
  (vedi `hasRawPrivateKey` nel client) → response 400

```python
from pydantic import BaseModel, Field, model_validator
from typing import Any


class ContextRequestBody(BaseModel):
    """Body for POST /context."""
    secretary_context_request: dict[str, Any] = Field(
        ...,
        description="Closed envelope with at least request_id"
    )

    model_config = {"extra": "forbid"}  # rifiuta campi extra al root

    @model_validator(mode="after")
    def validate_envelope(self):
        if not self.secretary_context_request:
            raise ValueError("secretary_context_request must be a non-empty object")
        if _has_raw_private_key(self.secretary_context_request):
            raise ValueError("raw-private keys are not allowed")
        return self


class TaskRequestBody(BaseModel):
    """Body for POST /task."""
    secretary_task_request: dict[str, Any] = Field(
        ...,
        description="Closed envelope with at least request.request_id"
    )

    model_config = {"extra": "forbid"}

    @model_validator(mode="after")
    def validate_envelope(self):
        if not self.secretary_task_request:
            raise ValueError("secretary_task_request must be a non-empty object")
        if _has_raw_private_key(self.secretary_task_request):
            raise ValueError("raw-private keys are not allowed")
        return self


def _has_raw_private_key(obj: Any) -> bool:
    """Recursive check for any key starting with 'rawprivate' (case insensitive,
    ignoring - and _). Mirrors hasRawPrivateKey in secretaryClient.js.
    """
    if isinstance(obj, dict):
        for key, value in obj.items():
            normalized = key.replace("-", "").replace("_", "").lower()
            if normalized.startswith("rawprivate"):
                return True
            if _has_raw_private_key(value):
                return True
    elif isinstance(obj, list):
        for item in obj:
            if _has_raw_private_key(item):
                return True
    return False


def validate_safe_request_id(value: Any) -> str:
    """Mirror of requireSafeRequestId in stub Node.
    Pattern: /^[A-Za-z0-9_.:-]{1,160}$/
    """
    if not isinstance(value, str):
        raise ValueError("request_id must be a string")
    import re
    if not re.match(r"^[A-Za-z0-9_.:-]{1,160}$", value):
        raise ValueError("request_id must match safe pattern")
    return value
```

#### auth.py

Middleware/dependency FastAPI per validazione Bearer token:

```python
import os
from fastapi import HTTPException, Header, status
from typing import Annotated

from segretario.config.settings import HTTPServerSettings


def _get_expected_token(settings: HTTPServerSettings) -> str | None:
    """Leggi il token atteso dalla env var configurata."""
    token = os.getenv(settings.auth_token_env, "")
    return token if token else None


def require_bearer_token(
    authorization: Annotated[str | None, Header(alias="Authorization")] = None,
    # In real implementation, settings will be injected via FastAPI Depends
):
    """Valida Authorization: Bearer <token>.

    Rules:
    - Se nessun token configurato in env: auth disabilitata (dev mode).
      Logga warning al boot.
    - Se token configurato: header DEVE essere "Bearer <token_atteso>".
    - Niente cookie, niente query, niente body fields.
    """
    # In Task 3b-1, settings viene presa dal global app state.
    # Vedi app.py per il pattern Dependency.
    expected = _get_current_expected_token()

    if expected is None:
        # Dev mode: auth disabled
        return

    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error_code": "invalid_auth"},
        )

    token = authorization[len("Bearer "):]
    if token != expected:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error_code": "invalid_auth"},
        )
```

#### stub_responses.py

Risposte hardcoded bit-equivalent allo stub Node. Leggi
`zarsos-secretary-stub.mjs` righe 95-161 per i payload esatti.

```python
def build_context_response(payload: dict) -> dict:
    """Mirror buildContextResponse() del Node stub. Bit-equivalent output."""
    root = payload["secretary_context_request"]
    request_id = validate_safe_request_id(root.get("request_id"))

    return {
        "secretary_context_response": {
            "request_id": request_id,
            "status": "allowed",
            "context_payload": {
                "summary": "Segretario locale di prova: projection disponibile.",
                "constraints": [
                    "projection only",
                    "no raw private data",
                ],
            },
            "privacy_level": "sanitized",
            "cloud_safe": True,
            "usage_constraints": ["projection only"],
            "requires_output_return": False,
            "raw_included": False,
        }
    }


def build_task_response(payload: dict) -> dict:
    """Mirror buildTaskResponse() del Node stub. Bit-equivalent output."""
    root = payload["secretary_task_request"]
    request = root.get("request", {})
    request_id = validate_safe_request_id(request.get("request_id"))

    return {
        "secretary_task_result": {
            "version": "1.0",
            "request": {"request_id": request_id},
            "status": {
                "state": "requires_confirmation",
                "reason": "stub_draft_ready_before_final_action",
            },
            "ownership": {
                "output_owner": "segretario",
                "zarsuit_processing_allowed": False,
                "zarsuit_editing_allowed": False,
            },
            "final_response": {
                "audience": "user",
                "content": "Segretario locale di prova: bozza preparata. Serve conferma prima dell'azione finale.",
            },
            "confirmation": {
                "required": True,
                "pending_action": "stub_confirm_final_action",
            },
            "privacy": {
                "raw_private_data_exposed_to_zarsuit": False,
                "output_sanitized_by_secretary": True,
            },
            "audit": {"stored": True},
        }
    }
```

#### app.py

```python
import logging
from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.responses import JSONResponse

from segretario.config.settings import Settings, HTTPServerSettings
from segretario.http_server.models import ContextRequestBody, TaskRequestBody, validate_safe_request_id
from segretario.http_server.auth import require_bearer_token
from segretario.http_server.stub_responses import build_context_response, build_task_response

logger = logging.getLogger(__name__)


def create_app(settings: Settings) -> FastAPI:
    """Factory per la app FastAPI. Local-only enforcement."""
    if settings.http_server.host not in ("127.0.0.1", "localhost"):
        raise RuntimeError(
            f"http_server.host must be 127.0.0.1 or localhost for Task 3b-1; "
            f"got {settings.http_server.host!r}. Network exposure is out of scope."
        )

    app = FastAPI(
        title="il_segretario HTTP",
        version="3b-1-stub",
        docs_url=None,  # disabilita /docs per ridurre attack surface
        redoc_url=None,
    )

    @app.get("/health")
    async def health():
        """Liveness probe, no auth."""
        return {"status": "ok"}

    @app.post("/context")
    async def context(
        body: ContextRequestBody,
        _auth: None = Depends(require_bearer_token),
    ):
        """POST /context — drop-in equivalent of zarsos-secretary-stub.mjs"""
        try:
            response_body = build_context_response(body.model_dump())
            return JSONResponse(content=response_body, status_code=200)
        except ValueError as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"error_code": "invalid_request", "message": str(e)},
            )

    @app.post("/task")
    async def task(
        body: TaskRequestBody,
        _auth: None = Depends(require_bearer_token),
    ):
        """POST /task — drop-in equivalent of zarsos-secretary-stub.mjs"""
        try:
            response_body = build_task_response(body.model_dump())
            return JSONResponse(content=response_body, status_code=200)
        except ValueError as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"error_code": "invalid_request", "message": str(e)},
            )

    return app
```

**Nota su 405 e 404:** FastAPI gestisce nativamente `Method Not Allowed` (es.
GET su /context → 405) e route inesistenti (es. POST /banana → 404). Verifica
nei test che il comportamento sia coerente con lo stub Node (che ritorna
`{"ok": false, "error": "method_not_allowed"}` o `not_found`). Se FastAPI
ritorna body diversi, potremmo voler customizzare gli handler per coerenza.
Decidi in base a quello che richiede il client Node.

### STEP 4 — CLI command per lanciare il server

In `src/segretario/cli.py`, aggiungi un comando `http-server`:

```python
@app.command("http-server")
def http_server_command(
    host: str = typer.Option(None, "--host", help="Override host"),
    port: int = typer.Option(None, "--port", help="Override port"),
    reload: bool = typer.Option(False, "--reload", help="Dev reload"),
):
    """Avvia il server HTTP del segretario (per ricevere richieste da zarsOS)."""
    import uvicorn
    from segretario.http_server.app import create_app

    settings = load_settings()

    if not settings.http_server.enabled:
        typer.echo("HTTP server is disabled in config (http_server.enabled=false).", err=True)
        raise typer.Exit(code=1)

    effective_host = host or settings.http_server.host
    effective_port = port or settings.http_server.port

    expected_token = os.getenv(settings.http_server.auth_token_env, "")
    if not expected_token:
        typer.echo(
            f"WARN: env var {settings.http_server.auth_token_env} is empty. "
            f"Auth is DISABLED. Set it for production use.",
            err=True,
        )

    app_instance = create_app(settings)
    uvicorn.run(
        app_instance,
        host=effective_host,
        port=effective_port,
        reload=reload,
        log_level="info",
    )
```

### STEP 5 — Test

Aggiungi `tests/test_http_server.py` con questi test:

```python
import os
import json
import pytest
from fastapi.testclient import TestClient

from segretario.config.settings import Settings, HTTPServerSettings
from segretario.http_server.app import create_app


@pytest.fixture
def app_with_auth(monkeypatch):
    monkeypatch.setenv("IL_SEGRETARIO_HTTP_TOKEN", "test-token-123")
    settings = Settings(
        # ... default settings ...
        http_server=HTTPServerSettings(
            enabled=True,
            host="127.0.0.1",
            port=8722,
            auth_token_env="IL_SEGRETARIO_HTTP_TOKEN",
        ),
    )
    return create_app(settings)


@pytest.fixture
def app_no_auth(monkeypatch):
    monkeypatch.delenv("IL_SEGRETARIO_HTTP_TOKEN", raising=False)
    # ... settings con enabled=True ...
    settings = Settings(http_server=HTTPServerSettings(enabled=True))
    return create_app(settings)


def test_health_no_auth_required(app_with_auth):
    client = TestClient(app_with_auth)
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_context_happy_path(app_with_auth):
    client = TestClient(app_with_auth)
    response = client.post(
        "/context",
        headers={"Authorization": "Bearer test-token-123"},
        json={
            "secretary_context_request": {
                "request_id": "test-req-001",
                "some_field": "value",
            }
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert "secretary_context_response" in body
    resp = body["secretary_context_response"]
    assert resp["request_id"] == "test-req-001"
    assert resp["status"] == "allowed"
    assert resp["privacy_level"] == "sanitized"
    assert resp["cloud_safe"] is True
    # Verifica bit-equivalence con stub Node
    assert resp["context_payload"]["summary"] == "Segretario locale di prova: projection disponibile."


def test_task_happy_path(app_with_auth):
    client = TestClient(app_with_auth)
    response = client.post(
        "/task",
        headers={"Authorization": "Bearer test-token-123"},
        json={
            "secretary_task_request": {
                "request": {"request_id": "task-req-001"},
                "some_field": "value",
            }
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert "secretary_task_result" in body
    resp = body["secretary_task_result"]
    assert resp["request"]["request_id"] == "task-req-001"
    assert resp["status"]["state"] == "requires_confirmation"
    assert resp["ownership"]["output_owner"] == "segretario"


def test_auth_missing_token(app_with_auth):
    client = TestClient(app_with_auth)
    response = client.post(
        "/context",
        json={"secretary_context_request": {"request_id": "x"}},
    )
    assert response.status_code == 401


def test_auth_wrong_token(app_with_auth):
    client = TestClient(app_with_auth)
    response = client.post(
        "/context",
        headers={"Authorization": "Bearer wrong-token"},
        json={"secretary_context_request": {"request_id": "x"}},
    )
    assert response.status_code == 401


def test_auth_malformed_header(app_with_auth):
    client = TestClient(app_with_auth)
    response = client.post(
        "/context",
        headers={"Authorization": "NotBearer xxx"},
        json={"secretary_context_request": {"request_id": "x"}},
    )
    assert response.status_code == 401


def test_extra_root_field_rejected(app_with_auth):
    """Schema strict: extra fields al root vengono rifiutati."""
    client = TestClient(app_with_auth)
    response = client.post(
        "/context",
        headers={"Authorization": "Bearer test-token-123"},
        json={
            "secretary_context_request": {"request_id": "x"},
            "extra_field": "not allowed",
        },
    )
    assert response.status_code == 422  # Pydantic extra="forbid"


def test_empty_envelope_rejected(app_with_auth):
    client = TestClient(app_with_auth)
    response = client.post(
        "/context",
        headers={"Authorization": "Bearer test-token-123"},
        json={"secretary_context_request": {}},
    )
    assert response.status_code == 422


def test_raw_private_key_rejected(app_with_auth):
    """Chiavi rawPrivate* vietate."""
    client = TestClient(app_with_auth)
    response = client.post(
        "/context",
        headers={"Authorization": "Bearer test-token-123"},
        json={
            "secretary_context_request": {
                "request_id": "x",
                "raw_private_data": "leak attempt",
            }
        },
    )
    assert response.status_code == 422


def test_raw_private_key_nested_rejected(app_with_auth):
    """rawPrivate annidato deve essere bloccato."""
    client = TestClient(app_with_auth)
    response = client.post(
        "/context",
        headers={"Authorization": "Bearer test-token-123"},
        json={
            "secretary_context_request": {
                "request_id": "x",
                "nested": {"raw-private": "leak"},
            }
        },
    )
    assert response.status_code == 422


def test_invalid_request_id_pattern(app_with_auth):
    """request_id deve matchare /^[A-Za-z0-9_.:-]{1,160}$/"""
    client = TestClient(app_with_auth)
    response = client.post(
        "/context",
        headers={"Authorization": "Bearer test-token-123"},
        json={
            "secretary_context_request": {
                "request_id": "invalid with spaces",
            }
        },
    )
    assert response.status_code == 400


def test_get_on_context_is_405(app_with_auth):
    client = TestClient(app_with_auth)
    response = client.get("/context")
    assert response.status_code == 405


def test_unknown_path_is_404(app_with_auth):
    client = TestClient(app_with_auth)
    response = client.post(
        "/unknown",
        headers={"Authorization": "Bearer test-token-123"},
        json={},
    )
    assert response.status_code == 404


def test_auth_disabled_when_no_env_var(app_no_auth):
    """In dev mode (no env var), auth è disabilitata."""
    client = TestClient(app_no_auth)
    response = client.post(
        "/context",
        json={"secretary_context_request": {"request_id": "x"}},
    )
    assert response.status_code == 200


def test_non_local_host_rejected_at_boot():
    """Bind su host non-locale viene rifiutato."""
    settings = Settings(
        http_server=HTTPServerSettings(
            enabled=True,
            host="0.0.0.0",
        )
    )
    with pytest.raises(RuntimeError, match="local-only"):
        create_app(settings)
```

### STEP 6 — Smoke test reale

DOPO i test verdi:

```powershell
cd e:\il_segretario\.worktrees\task3b1-http-server

# 1. Avvia il server con auth
$env:IL_SEGRETARIO_HTTP_TOKEN="smoke-test-token-abc123"
# Abilita nel config (modifica segretario.yaml o usa override)
uv run segretario http-server

# In un altro terminale:

# 2. Health (no auth)
curl http://127.0.0.1:8722/health
# Atteso: {"status":"ok"}

# 3. Context endpoint happy path
curl -X POST http://127.0.0.1:8722/context `
  -H "Authorization: Bearer smoke-test-token-abc123" `
  -H "Content-Type: application/json" `
  -d '{\"secretary_context_request\":{\"request_id\":\"smoke-test-001\"}}'
# Atteso: 200 con body equivalente allo stub Node

# 4. Task endpoint happy path
curl -X POST http://127.0.0.1:8722/task `
  -H "Authorization: Bearer smoke-test-token-abc123" `
  -H "Content-Type: application/json" `
  -d '{\"secretary_task_request\":{\"request\":{\"request_id\":\"smoke-task-001\"}}}'
# Atteso: 200 con body equivalente allo stub Node

# 5. Auth missing
curl -X POST http://127.0.0.1:8722/context `
  -H "Content-Type: application/json" `
  -d '{\"secretary_context_request\":{\"request_id\":\"x\"}}'
# Atteso: 401

# 6. Auth wrong
curl -X POST http://127.0.0.1:8722/context `
  -H "Authorization: Bearer wrong-token" `
  -H "Content-Type: application/json" `
  -d '{\"secretary_context_request\":{\"request_id\":\"x\"}}'
# Atteso: 401

# 7. Body comparison: lancia ANCHE lo stub Node, fai stessa chiamata
# e verifica byte-by-byte che il response body è identico:
cd E:\zarsOS
node scripts/zarsos-secretary-stub.mjs --host 127.0.0.1 --port 4317
# In altro terminale:
curl -X POST http://127.0.0.1:4317/context `
  -H "Content-Type: application/json" `
  -d '{\"secretary_context_request\":{\"request_id\":\"compare-001\"}}' > stub-node.json

# Fai stessa chiamata al server Python:
curl -X POST http://127.0.0.1:8722/context `
  -H "Authorization: Bearer smoke-test-token-abc123" `
  -H "Content-Type: application/json" `
  -d '{\"secretary_context_request\":{\"request_id\":\"compare-001\"}}' > stub-python.json

# Compara:
# (Powershell)
$nodeBody = Get-Content stub-node.json -Raw | ConvertFrom-Json
$pythonBody = Get-Content stub-python.json -Raw | ConvertFrom-Json
Compare-Object ($nodeBody | ConvertTo-Json -Depth 100) ($pythonBody | ConvertTo-Json -Depth 100)
# Atteso: nessuna differenza
```

### Criteri di successo

1. **Tutti i test passano** (~15 nuovi test, +existing ~420 = ~435 totali)
2. **Smoke test passa tutti i 7 step** (health, context happy, task happy, 2x
   auth fail, comparison vs stub Node)
3. **Bit-equivalence con stub Node verificata** (step 7 dello smoke test)
4. **Server bound solo su 127.0.0.1** (verifica con `netstat -an | findstr 8722`)
5. **Niente regressioni** sui test esistenti di Task 1 e Task 2

### STEP 7 — Documentazione

Aggiorna `README.md` aggiungendo una sezione "HTTP Server":

```markdown
## HTTP Server (opt-in)

`il_segretario` può esporre un server HTTP locale per ricevere richieste da
zarsOS. È **disabilitato di default**.

### Configurazione

In `segretario.yaml`:

\`\`\`yaml
http_server:
  enabled: true
  host: "127.0.0.1"   # SOLO local (127.0.0.1 o localhost)
  port: 8722
  auth_token_env: "IL_SEGRETARIO_HTTP_TOKEN"
\`\`\`

### Avvio

\`\`\`powershell
$env:IL_SEGRETARIO_HTTP_TOKEN = "<token-segreto>"
uv run segretario http-server
\`\`\`

### Endpoints

- `GET /health` — liveness (no auth)
- `POST /context` — secretary context request (auth required)
- `POST /task` — secretary task request (auth required)

### Auth

Bearer token in header `Authorization`. Il token viene letto dalla env var
configurata in `auth_token_env`. Se la env var è vuota, l'auth è disabilitata
(modalità dev, WARN al boot).
```

### STEP 8 — Commit

SOLO se i criteri di successo passano:

```
feat(http_server): add stub-equivalent HTTP server for zarsOS integration

Task 3b-1: drop-in Python replacement for zarsos-secretary-stub.mjs.

- New package src/segretario/http_server/ with FastAPI app
- Endpoints: GET /health, POST /context, POST /task
- Bearer token auth via env var (configurable name)
- Pydantic schemas with closed-envelope validation (mirrors secretaryClient.js)
- Bit-equivalent response payloads to the Node stub
- Local-only enforcement: bind on 127.0.0.1/localhost rejected at boot
- New CLI command: segretario http-server
- ~15 new tests for endpoints, auth, schema validation, raw-private blocking
- Manual smoke test: bit-equivalence with Node stub verified via curl + diff

zarsOS can now do its S6 smoke test against this server in place of the Node
stub. Task 3b-2 will replace the hardcoded responses with real logic from
RecallEngine + brokers.

Closes Task 3b-1 of il_segretario completion plan.
```

### STEP 9 — Aggiornamento note progetto

Dopo commit, aggiorna `docs/project-notes-consolidated.md`:

- Sezione 1: Task 3b-1 marcato come ✅ chiuso. Resta da fare Task 3b-2 (logica reale).
- Sezione 2: aggiungi cronologia Task 3b-1 con le decisioni di design
  (FastAPI, stub-first, bit-equivalence)
- Sezione 4: bug noti vuota
- Sezione 5: eventuali nuove lezioni apprese durante l'implementazione

## Cosa NON fare

- NON implementare logica vera per /context o /task (è Task 3b-2)
- NON aggiungere middleware extra (rate limit, CORS, logging custom) — sono out of scope
- NON esporre il server su 0.0.0.0 o IP LAN. Solo `127.0.0.1`/`localhost`
- NON committare il token in chiaro mai (env var only)
- NON modificare il codice di Task 1 o Task 2
- NON tentare di mergeare Task 2 su master come parte di questo task

## Stop and ask

Fermati se:

- FastAPI ha problemi a installarsi con Python 3.12
- Lo schema Pydantic non riesce a esprimere il vincolo "esattamente uno tra
  due root keys" (alternative: validazione manuale con custom validator)
- Il comportamento di FastAPI su `extra="forbid"` differisce da quello che
  ci si aspetta da `secretaryClient.js`
- Lo smoke test step 7 (bit-equivalence) fallisce per differenze non banali
  (es. ordering delle chiavi JSON, encoding, escape characters)
- I test esistenti di Task 1/Task 2 si rompono per qualche ragione
- Emergono regressioni nel `cli.py` durante l'aggiunta del comando
  `http-server`
