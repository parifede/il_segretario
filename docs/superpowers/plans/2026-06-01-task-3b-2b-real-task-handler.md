# Task 3b-2b: `/task` Real Handler Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the hardcoded stub for `POST /task` with real classification + PermissionKernel gating + LLM content generation + Q4 output guard + auditable audit trail.

**Architecture:** Mirror `context_handler.py` — parse `secretary_task_request`, look up `(domain, action_type)` in an explicit table of PermissionKernel constants, call `_strictest(decision_for(c) for c in constants)` to get state, generate LLM content for allowed/confirm states, run the Q4 `guard_zarsuit_schema_leak` guard, write audit, return structured `secretary_task_result`. Three HTTP levels: 400 (invalid request_id), 200 (any outcome including `failed`), 503 (audit write failure).

**Tech Stack:** FastAPI, Pydantic, OllamaClient (sync Ollama), PermissionKernel, AuditLog, CharacterStore, `re`, Python `dataclasses`

**Baseline:** 469 tests green — must not regress.

**Design doc:** `docs/superpowers/specs/2026-06-01-task-3b-2b-design.md`

---

## File Map

| Action | File | Responsibility |
|--------|------|----------------|
| Modify | `src/segretario/config/settings.py` | Add `sync_model_keep_alive: int = -1` to `LLMSettings` |
| Modify | `src/segretario/connectors/ollama_client.py` | Add `keep_alive` constructor param; pass in generate payload |
| Modify | `src/segretario/policies/output_guard.py` | Add `GuardResult` dataclass + `guard_zarsuit_schema_leak` |
| Create | `src/segretario/http_server/task_handler.py` | All task logic: tables, decision, generation, guard, audit, response |
| Modify | `src/segretario/http_server/app.py` | Wire real handler; add CharacterStore; update OllamaClient; add 503 handler |
| Create | `tests/test_guard_q4.py` | Unit tests for `guard_zarsuit_schema_leak` |
| Modify | `tests/test_http_server.py` | Rewrite `test_task_happy_path`; add ~15 task integration tests |
| Modify | `tests/test_ollama_client.py` | Add `keep_alive` payload tests |

---

## Task 0: Setup — worktree + vault backup

**Files:** (no code changes)

- [ ] **Step 1: Create git worktree**

```powershell
git worktree add .worktrees/task3b2b -b feature/task3b2b-task-handler
```

All subsequent work happens inside `.worktrees/task3b2b/`.

- [ ] **Step 2: Backup vault**

```powershell
cd .worktrees/task3b2b
uv run segretario vault backup
```

Expected: backup completes without error.

- [ ] **Step 3: Confirm baseline**

```powershell
uv run pytest -q
```

Expected: `469 passed` (exact count may vary between sessions — record it).

---

## Task 1: Config + OllamaClient — `keep_alive`

**Files:**
- Modify: `src/segretario/config/settings.py`
- Modify: `src/segretario/connectors/ollama_client.py`
- Modify: `tests/test_ollama_client.py`

- [ ] **Step 1: Write failing tests for `keep_alive`**

Append to `tests/test_ollama_client.py`:

```python
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
```

- [ ] **Step 2: Run — expect FAIL**

```powershell
uv run pytest tests/test_ollama_client.py -v
```

Expected: `FAILED` — `OllamaClient.__init__() got an unexpected keyword argument 'keep_alive'`

- [ ] **Step 3: Add `keep_alive` to `LLMSettings` in `settings.py`**

In `src/segretario/config/settings.py`, inside `LLMSettings`, add after `timeout_seconds`:

```python
sync_model_keep_alive: int = -1  # -1 = always resident; coordinate with async model-swap in Phase 5
```

- [ ] **Step 4: Add `keep_alive` to `OllamaClient`**

In `src/segretario/connectors/ollama_client.py`, replace the `__init__` and `generate` methods:

```python
def __init__(
    self,
    *,
    model: str,
    base_url: str,
    timeout_seconds: float = 120,
    think: bool | None = None,
    keep_alive: int = -1,
    client: httpx.Client | None = None,
) -> None:
    self.model = model
    self.base_url = base_url.rstrip("/")
    self.timeout_seconds = timeout_seconds
    self.think = think
    self.keep_alive = keep_alive
    self._client = client or httpx.Client(timeout=timeout_seconds)

def generate(self, prompt: str, system: str | None = None) -> str:
    payload: dict[str, object] = {
        "model": self.model,
        "prompt": prompt,
        "stream": False,
        "keep_alive": self.keep_alive,
    }
    if system:
        payload["system"] = system
    if self.think is not None:
        payload["think"] = self.think

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
```

- [ ] **Step 5: Run — expect PASS**

```powershell
uv run pytest tests/test_ollama_client.py -v
```

Expected: all tests pass (existing + 2 new).

- [ ] **Step 6: Full regression**

```powershell
uv run pytest -q
```

Expected: same count as baseline (no regressions).

- [ ] **Step 7: Commit**

```powershell
git add src/segretario/config/settings.py src/segretario/connectors/ollama_client.py tests/test_ollama_client.py
git commit -m "feat(config,ollama): add sync_model_keep_alive setting and keep_alive to OllamaClient"
```

---

## Task 2: Guard Q4 tests (TDD red)

**Files:**
- Create: `tests/test_guard_q4.py`

- [ ] **Step 1: Create `tests/test_guard_q4.py` with all guard unit tests**

```python
"""Unit tests for guard_zarsuit_schema_leak — Q4 pattern coverage.

Anti-drift: keyword lists are pinned to docs/secretary_bridge_contract.md §Q4.
A test failure here means the Python guard has drifted from the Node outputGuard.
"""
from segretario.policies.output_guard import (
    GuardResult,
    _SCHEMA_KEYS_GENERIC,
    _SCHEMA_KEYS_UNAMBIGUOUS,
    guard_zarsuit_schema_leak,
)


# ---------------------------------------------------------------------------
# Anti-drift: pin to Q4 contract
# ---------------------------------------------------------------------------

def test_schema_keys_unambiguous_match_q4_contract():
    """Unambiguous key list must match secretary_bridge_contract.md §Q4 exactly."""
    expected = {
        "secretary_task_request",
        "secretary_context_request",
        "risk_attestation",
        "zarsuit_task_output_for_secretary",
        "zarsuit_execution_input",
        "secretary_routing_directive",
    }
    assert set(_SCHEMA_KEYS_UNAMBIGUOUS) == expected


def test_schema_keys_generic_match_q4_contract():
    """Generic key list must match secretary_bridge_contract.md §Q4 exactly."""
    expected = {"tool_call", "function_call", "arguments", "internal_tool"}
    assert set(_SCHEMA_KEYS_GENERIC) == expected


# ---------------------------------------------------------------------------
# Clean content — no false positives
# ---------------------------------------------------------------------------

def test_guard_clean_content_does_not_fire():
    result = guard_zarsuit_schema_leak("Hai ricevuto 3 email oggi. Il progetto procede bene.")
    assert result.fired is False
    assert result.redactions == []


def test_guard_does_not_fire_on_english_word_arguments():
    """'arguments' is a common English word — must not fire without JSON quotes."""
    result = guard_zarsuit_schema_leak("The function takes two arguments.")
    assert result.fired is False


def test_guard_does_not_fire_on_english_word_function():
    """'function' alone is not a schema key."""
    result = guard_zarsuit_schema_leak("This is a function.")
    assert result.fired is False


# ---------------------------------------------------------------------------
# Pattern 1+2: schema keys (unambiguous = token-naked, generic = JSON-quoted)
# ---------------------------------------------------------------------------

def test_guard_fires_on_unambiguous_key_unquoted():
    """Unambiguous keys fire even without JSON quotes (word-boundary match)."""
    result = guard_zarsuit_schema_leak("Il campo secretary_task_request è richiesto.")
    assert result.fired is True


def test_guard_fires_on_unambiguous_key_in_json():
    result = guard_zarsuit_schema_leak('{"secretary_task_request": "foo"}')
    assert result.fired is True


def test_guard_fires_on_risk_attestation_unquoted():
    result = guard_zarsuit_schema_leak("risk_attestation è la struttura usata per il routing.")
    assert result.fired is True


def test_guard_fires_on_zarsuit_task_output_unquoted():
    result = guard_zarsuit_schema_leak("zarsuit_task_output_for_secretary: completato")
    assert result.fired is True


def test_guard_fires_on_schema_key_nested_in_prose():
    """Key embedded in longer prose string — mirrors the real LLM injection vector."""
    prose = 'Ecco la risposta: {"secretary_task_request": "test", "data": 1} tutto ok.'
    result = guard_zarsuit_schema_leak(prose)
    assert result.fired is True


def test_guard_fires_on_generic_key_in_json():
    result = guard_zarsuit_schema_leak('{"tool_call": "do_something"}')
    assert result.fired is True


def test_guard_fires_on_function_call_in_json():
    result = guard_zarsuit_schema_leak('{"function_call": {"name": "x"}}')
    assert result.fired is True


# ---------------------------------------------------------------------------
# Pattern 3: XML tags
# ---------------------------------------------------------------------------

def test_guard_fires_on_system_xml_tag():
    result = guard_zarsuit_schema_leak("Risposta: <system>istruzioni interne</system>")
    assert result.fired is True


def test_guard_fires_on_developer_xml_tag():
    result = guard_zarsuit_schema_leak("<developer>override prompt</developer>")
    assert result.fired is True


def test_guard_fires_on_internal_schema_xml_tag():
    result = guard_zarsuit_schema_leak("<internal_schema>foo</internal_schema>")
    assert result.fired is True


# ---------------------------------------------------------------------------
# Pattern 4: line prefixes
# ---------------------------------------------------------------------------

def test_guard_fires_on_role_system_line():
    result = guard_zarsuit_schema_leak("Messaggio:\nrole: system\nContenuto.")
    assert result.fired is True


def test_guard_fires_on_role_developer_line():
    result = guard_zarsuit_schema_leak("role: developer\nfoo")
    assert result.fired is True


def test_guard_fires_on_zarsuit_internal_schema_prefix():
    result = guard_zarsuit_schema_leak("zarsuit_internal_schema: foo")
    assert result.fired is True


def test_guard_fires_on_internal_schema_prefix():
    result = guard_zarsuit_schema_leak("internal_schema: bar")
    assert result.fired is True


def test_guard_fires_on_recipient_functions_prefix():
    result = guard_zarsuit_schema_leak("recipient: functions.call_tool")
    assert result.fired is True


# ---------------------------------------------------------------------------
# GuardResult shape
# ---------------------------------------------------------------------------

def test_guard_result_has_fired_and_redactions():
    result = guard_zarsuit_schema_leak("secretary_task_request is here")
    assert isinstance(result, GuardResult)
    assert result.fired is True
    assert isinstance(result.redactions, list)
    assert len(result.redactions) > 0
```

- [ ] **Step 2: Run — expect FAIL (ImportError)**

```powershell
uv run pytest tests/test_guard_q4.py -v
```

Expected: `ImportError: cannot import name 'guard_zarsuit_schema_leak' from 'segretario.policies.output_guard'`

---

## Task 3: Implement `guard_zarsuit_schema_leak` (TDD green)

**Files:**
- Modify: `src/segretario/policies/output_guard.py`

- [ ] **Step 1: Add `GuardResult` and guard function to `output_guard.py`**

At the top of `src/segretario/policies/output_guard.py`, add after existing imports:

```python
from dataclasses import dataclass, field
```

After the existing imports block, add before `class ExternalAnswerDecision`:

```python
# ---------------------------------------------------------------------------
# Q4 guard — mirrors Node outputGuard.js pattern list exactly
# (source of truth: docs/secretary_bridge_contract.md §Q4)
# ---------------------------------------------------------------------------

@dataclass
class GuardResult:
    fired: bool
    redactions: list[str] = field(default_factory=list)


# Unambiguous identifiers: never appear in legitimate user output.
# Matched as bare tokens (word-boundary) — no JSON quoting required.
_SCHEMA_KEYS_UNAMBIGUOUS: tuple[str, ...] = (
    "secretary_task_request",
    "secretary_context_request",
    "risk_attestation",
    "zarsuit_task_output_for_secretary",
    "zarsuit_execution_input",
    "secretary_routing_directive",
)

# Generic keys: common English words — require JSON-quoting context to avoid false positives.
_SCHEMA_KEYS_GENERIC: tuple[str, ...] = (
    "tool_call",
    "function_call",
    "arguments",
    "internal_tool",
)

# Patterns generated from lists (no hand-written per-token regex → no typo risk)
_PAT_UNAMBIGUOUS = re.compile(
    "|".join(r"\b" + re.escape(k) + r"\b" for k in _SCHEMA_KEYS_UNAMBIGUOUS)
)
_PAT_GENERIC_JSON = re.compile(
    "|".join(r'"' + re.escape(k) + r'"' for k in _SCHEMA_KEYS_GENERIC)
)
_PAT_XML_TAGS = re.compile(
    r"<(system|developer|internal_schema|zarsuit_internal_schema|tool_schema|function_schema)\b",
    re.IGNORECASE,
)
_PAT_LINE_PREFIX = re.compile(
    r"^(role:\s*(system|developer)"
    r"|zarsuit_internal_schema:"
    r"|schema_internal:"
    r"|internal_schema:"
    r"|tool_schema:"
    r"|function_schema:"
    r"|recipient:\s*functions)",
    re.MULTILINE | re.IGNORECASE,
)


def guard_zarsuit_schema_leak(content: str) -> GuardResult:
    """Check output for Zarsuit internal schema leaks.

    Mirrors Node outputGuard.js Q4 patterns semantically.
    Returns GuardResult(fired=True, redactions=[...]) if any pattern matches.
    Caller must fail-closed on fired=True — do NOT emit redacted/partial content.
    """
    redactions: list[str] = []
    if _PAT_UNAMBIGUOUS.search(content):
        redactions.append("schema_key_unambiguous")
    if _PAT_GENERIC_JSON.search(content):
        redactions.append("schema_key_generic_json")
    if _PAT_XML_TAGS.search(content):
        redactions.append("xml_tag")
    if _PAT_LINE_PREFIX.search(content):
        redactions.append("line_prefix")
    return GuardResult(fired=bool(redactions), redactions=redactions)
```

- [ ] **Step 2: Run guard tests — expect PASS**

```powershell
uv run pytest tests/test_guard_q4.py -v
```

Expected: all tests pass.

- [ ] **Step 3: Full regression**

```powershell
uv run pytest -q
```

Expected: baseline + new guard tests pass.

- [ ] **Step 4: Commit**

```powershell
git add src/segretario/policies/output_guard.py tests/test_guard_q4.py
git commit -m "feat(guard): add guard_zarsuit_schema_leak with Q4 pattern coverage"
```

---

## Task 4: Write task integration tests (TDD red)

**Files:**
- Modify: `tests/test_http_server.py`

- [ ] **Step 1: Add helpers and `_FakeAuditLogRaises` to `tests/test_http_server.py`**

After the existing `_FakeAuditLog` class, add:

```python
class _FakeAuditLogRaises:
    """Audit log that always raises — simulates disk/lock failure."""
    def append_event(self, event_type: str, payload: dict) -> dict:
        raise RuntimeError("audit down")
```

After the existing `_make_app_with_recall` helper, add:

```python
def _task_body(
    domain: str,
    action_type: str,
    action_name: str = "",
    request_id: str = "task-001",
) -> dict:
    return {
        "secretary_task_request": {
            "version": "1.0",
            "request": {"request_id": request_id},
            "task": {
                "domain": domain,
                "action_type": action_type,
                "action_name": action_name,
            },
        }
    }


def _make_app_for_task(
    monkeypatch,
    *,
    llm_response: str | None = None,
    llm_raises: bool = False,
) -> tuple[TestClient, _FakeAuditLog]:
    monkeypatch.setenv("IL_SEGRETARIO_HTTP_TOKEN", "test-token-123")
    settings = Settings(http_server=HTTPServerSettings(enabled=True, host="127.0.0.1", port=8722))
    audit = _FakeAuditLog()
    app = create_app(
        settings,
        recall_engine=_FakeRecallEngine(None),
        audit_log=audit,
        llm_client=_FakeLLMClient(
            raises=llm_raises,
            response=llm_response if llm_response is not None else "risposta di test",
        ),
    )
    return TestClient(app), audit
```

- [ ] **Step 2: Add all task integration tests to `tests/test_http_server.py`**

Append after the existing context tests section:

```python
# ---------------------------------------------------------------------------
# Task: real handler (Task 3b-2b)
# ---------------------------------------------------------------------------

def test_task_happy_path(monkeypatch):
    """Shape + real values for completed state (gmail/read_only)."""
    client, audit = _make_app_for_task(monkeypatch, llm_response="Email lette correttamente.")
    r = client.post(
        "/task",
        headers=AUTH_HEADER,
        json=_task_body("gmail", "read_only", request_id="task-001"),
    )
    assert r.status_code == 200
    resp = r.json()["secretary_task_result"]
    assert resp["version"] == "1.0"
    assert resp["request"]["request_id"] == "task-001"
    assert resp["status"]["state"] == "completed"
    assert resp["ownership"]["output_owner"] == "segretario"
    assert resp["ownership"]["zarsuit_processing_allowed"] is False
    assert resp["ownership"]["zarsuit_editing_allowed"] is False
    assert resp["final_response"]["audience"] == "user"
    assert isinstance(resp["final_response"]["content"], str)
    assert len(resp["final_response"]["content"]) > 0
    assert resp["confirmation"]["required"] is False
    assert resp["privacy"]["raw_private_data_exposed_to_zarsuit"] is False
    assert resp["privacy"]["output_sanitized_by_secretary"] is True
    assert resp["audit"]["stored"] is True
    assert any(e[0] == "secretary_task_request" for e in audit.events)


def test_task_action_map_constants_exist_in_kernel():
    """All kernel constants referenced in _ACTION_MAP are real PermissionKernel attributes."""
    from segretario.http_server.task_handler import _ACTION_MAP
    from segretario.policies.permissions import PermissionKernel

    kernel_values = frozenset(
        v for k, v in vars(PermissionKernel).items()
        if isinstance(v, str) and not k.startswith("_")
    )
    all_map_constants = {c for constants in _ACTION_MAP.values() for c in constants}
    for constant in all_map_constants:
        assert constant in kernel_values, f"Kernel constant not found: {constant!r}"


def test_task_allow_returns_completed(monkeypatch):
    client, _ = _make_app_for_task(monkeypatch)
    r = client.post("/task", headers=AUTH_HEADER, json=_task_body("gmail", "read_only"))
    assert r.status_code == 200
    assert r.json()["secretary_task_result"]["status"]["state"] == "completed"


def test_task_confirm_returns_requires_confirmation(monkeypatch):
    client, _ = _make_app_for_task(monkeypatch)
    r = client.post("/task", headers=AUTH_HEADER, json=_task_body("gmail", "external_effect"))
    assert r.status_code == 200
    resp = r.json()["secretary_task_result"]
    assert resp["status"]["state"] == "requires_confirmation"
    assert resp["confirmation"]["required"] is True


def test_task_split_cell_returns_strictest_confirm(monkeypatch):
    """calendar/write has ALLOW+CONFIRM constants — strictest wins → requires_confirmation."""
    client, _ = _make_app_for_task(monkeypatch)
    r = client.post("/task", headers=AUTH_HEADER, json=_task_body("calendar", "write"))
    assert r.status_code == 200
    assert r.json()["secretary_task_result"]["status"]["state"] == "requires_confirmation"


def test_task_refused_domain_returns_refused(monkeypatch):
    client, audit = _make_app_for_task(monkeypatch)
    r = client.post("/task", headers=AUTH_HEADER, json=_task_body("secret_or_forbidden", "anything"))
    assert r.status_code == 200
    resp = r.json()["secretary_task_result"]
    assert resp["status"]["state"] == "refused"
    assert resp["confirmation"]["required"] is False
    task_evt = next(e[1] for e in audit.events if e[0] == "secretary_task_request")
    assert task_evt["audit_reason"] == "refused_domain"


def test_task_unmapped_action_returns_refused(monkeypatch):
    client, audit = _make_app_for_task(monkeypatch)
    r = client.post("/task", headers=AUTH_HEADER, json=_task_body("pippo", "pluto"))
    assert r.status_code == 200
    resp = r.json()["secretary_task_result"]
    assert resp["status"]["state"] == "refused"
    task_evt = next(e[1] for e in audit.events if e[0] == "secretary_task_request")
    assert task_evt["audit_reason"] == "unmapped_action"


def test_task_confirmation_coherence(monkeypatch):
    """confirmation.required is true only for requires_confirmation state."""
    client, _ = _make_app_for_task(monkeypatch)
    cases = [
        ("gmail", "read_only", "completed", False),
        ("gmail", "external_effect", "requires_confirmation", True),
        ("secret_or_forbidden", "x", "refused", False),
    ]
    for domain, action_type, expected_state, expected_req in cases:
        r = client.post("/task", headers=AUTH_HEADER, json=_task_body(domain, action_type))
        resp = r.json()["secretary_task_result"]
        assert resp["status"]["state"] == expected_state, f"{domain}/{action_type}"
        assert resp["confirmation"]["required"] is expected_req, f"{domain}/{action_type}"


def test_task_content_always_non_empty(monkeypatch):
    """final_response.content is a non-empty string for every state."""
    client, _ = _make_app_for_task(monkeypatch)
    for domain, action_type in [
        ("gmail", "read_only"),
        ("gmail", "external_effect"),
        ("secret_or_forbidden", "x"),
    ]:
        r = client.post("/task", headers=AUTH_HEADER, json=_task_body(domain, action_type))
        content = r.json()["secretary_task_result"]["final_response"]["content"]
        assert isinstance(content, str) and len(content) > 0, f"{domain}/{action_type}"


def test_task_audit_called_on_every_200(monkeypatch):
    client, audit = _make_app_for_task(monkeypatch)
    r = client.post("/task", headers=AUTH_HEADER, json=_task_body("gmail", "read_only"))
    assert r.status_code == 200
    assert any(e[0] == "secretary_task_request" for e in audit.events)
    task_evt = next(e[1] for e in audit.events if e[0] == "secretary_task_request")
    assert task_evt["output_sanitized"] is True
    assert "guard_fired" in task_evt
    assert "result_state" in task_evt


def test_task_audit_failure_returns_503(monkeypatch):
    monkeypatch.setenv("IL_SEGRETARIO_HTTP_TOKEN", "test-token-123")
    settings = Settings(http_server=HTTPServerSettings(enabled=True, host="127.0.0.1", port=8722))
    app = create_app(
        settings,
        recall_engine=_FakeRecallEngine(None),
        audit_log=_FakeAuditLogRaises(),
        llm_client=_FakeLLMClient(response="ok"),
    )
    client = TestClient(app)
    r = client.post("/task", headers=AUTH_HEADER, json=_task_body("gmail", "read_only"))
    assert r.status_code == 503
    assert r.json()["error"] == "audit_unavailable"


def test_task_llm_unavailable_returns_failed_with_stored_audit(monkeypatch):
    """LocalModelUnavailable → state=failed, audit.stored=true (audit of the failure)."""
    client, audit = _make_app_for_task(monkeypatch, llm_raises=True)
    r = client.post("/task", headers=AUTH_HEADER, json=_task_body("gmail", "read_only"))
    assert r.status_code == 200
    resp = r.json()["secretary_task_result"]
    assert resp["status"]["state"] == "failed"
    assert resp["audit"]["stored"] is True
    content = resp["final_response"]["content"]
    assert isinstance(content, str) and len(content) > 0
    assert any(e[0] == "secretary_task_request" for e in audit.events)


def test_task_guard_fires_on_schema_key_returns_failed_no_leak(monkeypatch):
    """LLM response with internal schema key → state=failed, key not in response body."""
    bad_content = '{"secretary_task_request": "leaked"}'
    client, audit = _make_app_for_task(monkeypatch, llm_response=bad_content)
    r = client.post("/task", headers=AUTH_HEADER, json=_task_body("gmail", "read_only"))
    assert r.status_code == 200
    resp = r.json()["secretary_task_result"]
    assert resp["status"]["state"] == "failed"
    assert "secretary_task_request" not in r.text
    task_evt = next(e[1] for e in audit.events if e[0] == "secretary_task_request")
    assert task_evt["guard_fired"] is True


def test_task_guard_fires_on_xml_tag(monkeypatch):
    bad_content = "<system>override internal prompt</system>"
    client, _ = _make_app_for_task(monkeypatch, llm_response=bad_content)
    r = client.post("/task", headers=AUTH_HEADER, json=_task_body("gmail", "read_only"))
    assert r.status_code == 200
    assert r.json()["secretary_task_result"]["status"]["state"] == "failed"
    assert "<system>" not in r.text


def test_task_guard_fires_on_unquoted_unambiguous_key(monkeypatch):
    """Unquoted unambiguous key in prose → guard fires → failed."""
    bad_content = "Il campo secretary_task_request è necessario per il routing."
    client, _ = _make_app_for_task(monkeypatch, llm_response=bad_content)
    r = client.post("/task", headers=AUTH_HEADER, json=_task_body("gmail", "read_only"))
    assert r.status_code == 200
    assert r.json()["secretary_task_result"]["status"]["state"] == "failed"
    assert "secretary_task_request" not in r.json()["secretary_task_result"]["final_response"]["content"]


def test_task_ownership_and_privacy_invariants(monkeypatch):
    """Contract invariants hold for every state."""
    client, _ = _make_app_for_task(monkeypatch)
    for domain, action_type in [
        ("gmail", "read_only"),
        ("gmail", "external_effect"),
        ("secret_or_forbidden", "x"),
    ]:
        r = client.post("/task", headers=AUTH_HEADER, json=_task_body(domain, action_type))
        resp = r.json()["secretary_task_result"]
        assert resp["ownership"]["output_owner"] == "segretario"
        assert resp["ownership"]["zarsuit_processing_allowed"] is False
        assert resp["ownership"]["zarsuit_editing_allowed"] is False
        assert resp["final_response"]["audience"] == "user"
        assert resp["privacy"]["raw_private_data_exposed_to_zarsuit"] is False
        assert resp["privacy"]["output_sanitized_by_secretary"] is True
```

- [ ] **Step 3: Run — expect FAIL**

```powershell
uv run pytest tests/test_http_server.py -k "task" -v
```

Expected: failures because `task_handler` module doesn't exist yet and the stub is still wired.

---

## Task 5: Create `task_handler.py`

**Files:**
- Create: `src/segretario/http_server/task_handler.py`

- [ ] **Step 1: Create the file**

Create `src/segretario/http_server/task_handler.py` with the full content:

```python
"""Real /task handler: classification + LLM generation + Q4 guard + audit for zarsOS bridge."""
from __future__ import annotations

import logging
from typing import Any, Iterable

from segretario.audit.hash_chain import AuditLog
from segretario.connectors.ollama_client import LocalModelUnavailable, OllamaClient
from segretario.flow02.character_store import CharacterStore
from segretario.http_server.models import validate_safe_request_id
from segretario.policies.output_guard import guard_zarsuit_schema_leak, sanitize_user_output
from segretario.policies.permissions import PermissionDecision, PermissionKernel as PK

logger = logging.getLogger(__name__)


class AuditUnavailableError(RuntimeError):
    """Raised when audit.append_event fails; signals HTTP 503 to the caller."""


# ---------------------------------------------------------------------------
# Decision tables
# ---------------------------------------------------------------------------

_REFUSED_DOMAINS: frozenset[str] = frozenset({
    "private_context_lookup",  # territory of /context, not /task
    "secret_or_forbidden",
    "dangerous_action",        # shell.execute is DENY_BY_DEFAULT
    "agent_activation",        # no remote capability
    "system_diagnostic",       # Zarsuit-handled (codex §14)
    "bacheca",                 # Taskboard not exposed via HTTP (GAP #6)
    "mixed",                   # ambiguous; clarification deferred
    "unknown",
})

# Explicit mapping (domain, action_type) → kernel constants.
# Values use PermissionKernel symbols — a wrong name is AttributeError at import,
# not a silent runtime misclassification.
# Split cells list every relevant constant; _strictest picks the tightest class.
# classifiers.js line refs from docs/secretary_bridge_contract.md §3.
_ACTION_MAP: dict[tuple[str, str], tuple[str, ...]] = {
    ("gmail", "read_only"):           (PK.GMAIL_READ,),                                                    # L164
    ("gmail", "draft"):               (PK.GMAIL_DRAFT,),                                                   # L171
    ("gmail", "external_effect"):     (PK.GMAIL_SEND, PK.GMAIL_DELETE, PK.GMAIL_ARCHIVE),                 # L170
    ("calendar", "read_only"):        (PK.CALENDAR_READ,),                                                 # L164
    ("calendar", "schedule"):         (PK.CALENDAR_SCHEDULE,),                                             # L168
    ("calendar", "write"):            (PK.CALENDAR_CREATE, PK.CALENDAR_CREATE_WITH_ATTENDEES, PK.CALENDAR_MODIFY),  # L172; split → CONFIRM
    ("calendar", "external_effect"):  (PK.CALENDAR_DELETE, PK.CALENDAR_ACCEPT, PK.CALENDAR_DECLINE),      # L170
    ("vault", "read_only"):           (PK.VAULT_READ, PK.VAULT_SEARCH),                                    # L164
    ("vault", "write"):               (PK.KNOWLEDGE_WRITE, PK.SELF_PROFILE_WRITE),                        # L172; split → CONFIRM
    ("memory", "read_only"):          (PK.VAULT_SEARCH,),                                                  # L164
    ("memory", "write"):              (PK.KNOWLEDGE_WRITE, PK.SELF_THOUGHTS_WRITE),                       # L172; split → CONFIRM
    ("web_research", "read_only"):    (PK.WEB_PUBLIC_QUERY,),                                              # L173-174
    ("vault_commands", "write"):      (PK.KNOWLEDGE_WRITE, PK.SELF_PROFILE_WRITE),                        # L172; split → CONFIRM
}

# Strictness order: highest number = most restrictive
_DECISION_ORDER: dict[str, int] = {
    PermissionDecision.ALLOW: 0,
    PermissionDecision.CONFIRM: 1,
    PermissionDecision.DENY: 2,
    PermissionDecision.PROJECT: 2,
}

# ---------------------------------------------------------------------------
# Content templates — never replaced by LLM on error paths
# ---------------------------------------------------------------------------

_FAILED_CONTENT_TEMPLATE = "Non è stato possibile completare il task. Riprova più tardi."
_REFUSED_CONTENT_TEMPLATE = "Mi dispiace, non posso eseguire questo tipo di operazione."
_TASK_SYSTEM_FRAMING = "Prepara la risposta per il task utente richiesto."


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _strictest(decisions: Iterable[PermissionDecision]) -> PermissionDecision:
    return max(decisions, key=lambda d: _DECISION_ORDER.get(d, 2))


def _decide(domain: str, action_type: str) -> tuple[str, str, str, str]:
    """Return (state, audit_reason, mapped_action, kernel_decision)."""
    if domain in _REFUSED_DOMAINS:
        return "refused", "refused_domain", "none", "none"

    constants = _ACTION_MAP.get((domain, action_type))
    if constants is None:
        return "refused", "unmapped_action", "none", "none"

    decision = _strictest(PK.decision_for(c) for c in constants)
    mapped_action = constants[0]
    kernel_decision = str(decision)

    if decision == PermissionDecision.ALLOW:
        return "completed", "ok", mapped_action, kernel_decision
    if decision == PermissionDecision.CONFIRM:
        return "requires_confirmation", "ok", mapped_action, kernel_decision
    # DENY or PROJECT → refused (defensive; no current cell reaches here)
    return "refused", "kernel_denied", mapped_action, kernel_decision


def _generate_content(
    llm_client: OllamaClient,
    character_store: CharacterStore,
    domain: str,
    action_type: str,
    action_name: str,
    state: str,
) -> str:
    system = character_store.identity() + "\n" + _TASK_SYSTEM_FRAMING
    task_desc = f"{domain}/{action_type}" + (f" ({action_name})" if action_name else "")
    if state == "requires_confirmation":
        prompt = (
            f"Task richiesto: {task_desc}\n"
            "Prepara una bozza e spiega che serve la conferma dell'utente prima di procedere."
        )
    else:
        prompt = f"Task richiesto: {task_desc}\nPrepara la risposta o il risultato del task."
    return llm_client.generate(prompt, system=system)


def _build_task_result(
    *,
    request_id: str,
    state: str,
    content: str,
    confirmation_required: bool,
) -> dict[str, Any]:
    return {
        "secretary_task_result": {
            "version": "1.0",
            "request": {"request_id": request_id},
            "status": {"state": state},
            "ownership": {
                "output_owner": "segretario",
                "zarsuit_processing_allowed": False,
                "zarsuit_editing_allowed": False,
            },
            "final_response": {
                "audience": "user",
                "content": content,
            },
            "confirmation": {"required": confirmation_required},
            "privacy": {
                "raw_private_data_exposed_to_zarsuit": False,
                "output_sanitized_by_secretary": True,
            },
            "audit": {"stored": True},
        }
    }


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def build_task_response_real(
    envelope: dict[str, Any],
    audit_log: AuditLog,
    llm_client: OllamaClient,
    character_store: CharacterStore,
) -> dict[str, Any]:
    """Build a real secretary_task_result from the secretary_task_request inner dict.

    envelope is body.secretary_task_request (the inner dict, not the outer wrapper).

    Raises:
        ValueError — invalid/missing request_id → caller maps to HTTP 400.
        AuditUnavailableError — audit write failed → caller maps to HTTP 503.
    """
    # Parse request_id — ValueError propagates to caller → HTTP 400
    request_id = validate_safe_request_id(
        envelope.get("request", {}).get("request_id")
    )

    # Defaults for audit fields (overwritten in try block on success)
    state = "failed"
    reason = "internal_error"
    mapped_action = "none"
    kernel_decision = "none"
    raw_content = _FAILED_CONTENT_TEMPLATE
    guard_fired = False

    try:
        task = envelope.get("task", {})
        domain = str(task.get("domain", "unknown")).strip() or "unknown"
        action_type = str(task.get("action_type", "unknown")).strip() or "unknown"
        action_name = str(task.get("action_name", "")).strip()

        state, reason, mapped_action, kernel_decision = _decide(domain, action_type)

        if state in ("completed", "requires_confirmation"):
            raw_content = _generate_content(
                llm_client, character_store, domain, action_type, action_name, state
            )
            guard_result = guard_zarsuit_schema_leak(raw_content)
            if guard_result.fired:
                guard_fired = True
                state = "failed"
                reason = "guard_fired"
                raw_content = _FAILED_CONTENT_TEMPLATE
        elif state == "refused":
            raw_content = _REFUSED_CONTENT_TEMPLATE
        # else: state=failed, raw_content already set to template

    except LocalModelUnavailable as exc:
        logger.warning("LLM unavailable for task %s: %s", request_id, exc)
        state = "failed"
        reason = "llm_unavailable"
        raw_content = _FAILED_CONTENT_TEMPLATE
    except Exception as exc:
        logger.error("task handler unexpected error for %s: %s", request_id, exc)
        # state/reason/raw_content remain at defaults set before the try

    content = sanitize_user_output(raw_content)

    # Audit — failure raises AuditUnavailableError → caller returns HTTP 503
    try:
        audit_log.append_event("secretary_task_request", {
            "request_id": request_id,
            "mapped_action": mapped_action,
            "kernel_decision": kernel_decision,
            "result_state": state,
            "output_sanitized": True,
            "guard_fired": guard_fired,
            "audit_reason": reason,
        })
    except Exception as exc:
        logger.error("audit write failed for task %s: %s", request_id, exc)
        raise AuditUnavailableError from exc

    return _build_task_result(
        request_id=request_id,
        state=state,
        content=content,
        confirmation_required=(state == "requires_confirmation"),
    )
```

- [ ] **Step 2: Verify import is clean**

```powershell
uv run python -c "from segretario.http_server.task_handler import build_task_response_real, AuditUnavailableError; print('OK')"
```

Expected: `OK`

---

## Task 6: Wire `app.py` + rewrite `test_task_happy_path`

**Files:**
- Modify: `src/segretario/http_server/app.py`
- Modify: `tests/test_http_server.py`

- [ ] **Step 1: Update imports in `app.py`**

In `src/segretario/http_server/app.py`, replace:

```python
from segretario.http_server.stub_responses import build_task_response
```

with:

```python
from segretario.flow02.character_store import CharacterStore
from segretario.http_server.task_handler import AuditUnavailableError, build_task_response_real
```

- [ ] **Step 2: Add `CharacterStore` construction and update `OllamaClient` in `create_app`**

In `create_app`, replace the existing `_llm` block:

```python
    _llm = llm_client or OllamaClient(
        model=settings.llm.sync_model,
        base_url=settings.llm.base_url,
        timeout_seconds=settings.llm.timeout_seconds,
        think=False,
    )
```

with:

```python
    _llm = llm_client or OllamaClient(
        model=settings.llm.sync_model,
        base_url=settings.llm.base_url,
        timeout_seconds=settings.llm.timeout_seconds,
        think=False,
        keep_alive=settings.llm.sync_model_keep_alive,
    )
    _character = CharacterStore.from_config(settings.character.identity)
```

- [ ] **Step 3: Replace the `/task` route**

In `create_app`, replace the entire `/task` route:

```python
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
```

- [ ] **Step 4: Rewrite `test_task_happy_path` to remove stub assertions**

In `tests/test_http_server.py`, find and **replace** the existing `test_task_happy_path` function (the one decorated with `app_with_auth` that checks stub values):

```python
# DELETE the old test_task_happy_path that uses app_with_auth fixture
# (it is now replaced by the new version added in Task 4 Step 2 above)
```

The new `test_task_happy_path` was already added in Task 4 Step 2. Just **delete** the old one (lines ~368-391 in the original file, inside the `# Task happy path (stub — unchanged)` section together with its section header comment).

- [ ] **Step 5: Run all task tests — expect PASS**

```powershell
uv run pytest tests/test_http_server.py -k "task" -v
```

Expected: all new task tests pass.

- [ ] **Step 6: Full regression — expect ≥ baseline**

```powershell
uv run pytest -q
```

Expected: baseline + new tests pass. Zero regressions.

- [ ] **Step 7: Commit**

```powershell
git add src/segretario/http_server/app.py src/segretario/http_server/task_handler.py tests/test_http_server.py
git commit -m "feat(task): replace stub /task with real PermissionKernel handler + Q4 guard + audit"
```

---

## Task 7: Smoke test + final validation

**Files:** (no code changes)

- [ ] **Step 1: Start the server**

```powershell
$env:IL_SEGRETARIO_HTTP_TOKEN = "smoke-token"
uv run python -m uvicorn segretario.http_server.app:create_app --factory --host 127.0.0.1 --port 8722
```

Open a second terminal for the following curl commands.

- [ ] **Step 2: Smoke — ALLOW path (completed)**

```powershell
curl -s -X POST http://127.0.0.1:8722/task `
  -H "Authorization: Bearer smoke-token" `
  -H "Content-Type: application/json" `
  -d '{"secretary_task_request":{"version":"1.0","request":{"request_id":"smoke-001"},"task":{"domain":"gmail","action_type":"read_only","action_name":"leggi inbox"}}}' | python -m json.tool
```

Expected: `status.state == "completed"`, `confirmation.required == false`, `audit.stored == true`.

- [ ] **Step 3: Smoke — CONFIRM path (requires_confirmation)**

```powershell
curl -s -X POST http://127.0.0.1:8722/task `
  -H "Authorization: Bearer smoke-token" `
  -H "Content-Type: application/json" `
  -d '{"secretary_task_request":{"version":"1.0","request":{"request_id":"smoke-002"},"task":{"domain":"gmail","action_type":"external_effect","action_name":"invia risposta"}}}' | python -m json.tool
```

Expected: `status.state == "requires_confirmation"`, `confirmation.required == true`.

- [ ] **Step 4: Smoke — refused domain**

```powershell
curl -s -X POST http://127.0.0.1:8722/task `
  -H "Authorization: Bearer smoke-token" `
  -H "Content-Type: application/json" `
  -d '{"secretary_task_request":{"version":"1.0","request":{"request_id":"smoke-003"},"task":{"domain":"dangerous_action","action_type":"execute"}}}' | python -m json.tool
```

Expected: `status.state == "refused"`, `confirmation.required == false`.

- [ ] **Step 5: Smoke — guard injection**

```powershell
# This verifies the guard fires on a forged content scenario.
# Use a _FakeLLMClient in a test env; in real smoke just verify the guard
# unit tests pass for the forged-content cases.
uv run pytest tests/test_guard_q4.py tests/test_http_server.py -k "guard" -v
```

Expected: all guard tests pass.

- [ ] **Step 6: Verify audit events file received events**

```powershell
# Path depends on your settings — default is state/audit/events.jsonl
Get-Content state\audit\events.jsonl | Select-Object -Last 5
```

Expected: recent lines with `"event_type": "secretary_task_request"` entries.

- [ ] **Step 7: Final full test run**

```powershell
uv run pytest -q
```

Expected: ≥ 469 + new tests pass. Zero failures.

- [ ] **Step 8: Merge or push**

Only after smoke is green:

```powershell
git log --oneline -5
# Review commits, then:
git checkout master
git merge feature/task3b2b-task-handler --no-ff -m "feat(task3b2b): /task real handler with PermissionKernel + Q4 guard + audit"
```
