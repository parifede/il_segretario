"""Tests for segretario.http_server — Task 3b-1 stub server."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from segretario.config.settings import HTTPServerSettings, Settings
from segretario.http_server.app import create_app


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def app_with_auth(monkeypatch):
    monkeypatch.setenv("IL_SEGRETARIO_HTTP_TOKEN", "test-token-123")
    settings = Settings(http_server=HTTPServerSettings(enabled=True, host="127.0.0.1", port=8722))
    return create_app(settings)


@pytest.fixture
def app_no_auth(monkeypatch):
    monkeypatch.delenv("IL_SEGRETARIO_HTTP_TOKEN", raising=False)
    settings = Settings(http_server=HTTPServerSettings(enabled=True, host="127.0.0.1", port=8722))
    return create_app(settings)


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

def test_health_no_auth_required(app_with_auth):
    client = TestClient(app_with_auth)
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_health_no_auth_no_token_env(app_no_auth):
    client = TestClient(app_no_auth)
    r = client.get("/health")
    assert r.status_code == 200


# ---------------------------------------------------------------------------
# Context happy path
# ---------------------------------------------------------------------------

def test_context_happy_path(app_with_auth):
    client = TestClient(app_with_auth)
    r = client.post(
        "/context",
        headers={"Authorization": "Bearer test-token-123"},
        json={"secretary_context_request": {"request_id": "req-001", "extra": "data"}},
    )
    assert r.status_code == 200
    body = r.json()
    resp = body["secretary_context_response"]
    assert resp["request_id"] == "req-001"
    assert resp["status"] == "allowed"
    assert resp["privacy_level"] == "sanitized"
    assert resp["cloud_safe"] is True
    assert resp["requires_output_return"] is False
    assert resp["raw_included"] is False
    assert resp["context_payload"]["summary"] == "Segretario locale di prova: projection disponibile."
    assert resp["context_payload"]["constraints"] == ["projection only", "no raw private data"]
    assert resp["usage_constraints"] == ["projection only"]


# ---------------------------------------------------------------------------
# Task happy path
# ---------------------------------------------------------------------------

def test_task_happy_path(app_with_auth):
    client = TestClient(app_with_auth)
    r = client.post(
        "/task",
        headers={"Authorization": "Bearer test-token-123"},
        json={"secretary_task_request": {"request": {"request_id": "task-001"}, "extra": "ok"}},
    )
    assert r.status_code == 200
    body = r.json()
    resp = body["secretary_task_result"]
    assert resp["version"] == "1.0"
    assert resp["request"]["request_id"] == "task-001"
    assert resp["status"]["state"] == "requires_confirmation"
    assert resp["status"]["reason"] == "stub_draft_ready_before_final_action"
    assert resp["ownership"]["output_owner"] == "segretario"
    assert resp["ownership"]["zarsuit_processing_allowed"] is False
    assert resp["ownership"]["zarsuit_editing_allowed"] is False
    assert resp["final_response"]["audience"] == "user"
    assert "bozza preparata" in resp["final_response"]["content"]
    assert resp["confirmation"]["required"] is True
    assert resp["confirmation"]["pending_action"] == "stub_confirm_final_action"
    assert resp["privacy"]["raw_private_data_exposed_to_zarsuit"] is False
    assert resp["privacy"]["output_sanitized_by_secretary"] is True
    assert resp["audit"]["stored"] is True


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

def test_auth_missing_token_returns_401(app_with_auth):
    client = TestClient(app_with_auth)
    r = client.post("/context", json={"secretary_context_request": {"request_id": "x"}})
    assert r.status_code == 401


def test_auth_wrong_token_returns_401(app_with_auth):
    client = TestClient(app_with_auth)
    r = client.post(
        "/context",
        headers={"Authorization": "Bearer wrong-token"},
        json={"secretary_context_request": {"request_id": "x"}},
    )
    assert r.status_code == 401


def test_auth_malformed_header_returns_401(app_with_auth):
    client = TestClient(app_with_auth)
    r = client.post(
        "/context",
        headers={"Authorization": "NotBearer xxx"},
        json={"secretary_context_request": {"request_id": "x"}},
    )
    assert r.status_code == 401


def test_auth_disabled_when_no_env_var(app_no_auth):
    """Dev mode: no env var → auth disabled → 200 with no Authorization header."""
    client = TestClient(app_no_auth)
    r = client.post(
        "/context",
        json={"secretary_context_request": {"request_id": "x"}},
    )
    assert r.status_code == 200


# ---------------------------------------------------------------------------
# Schema validation
# ---------------------------------------------------------------------------

def test_extra_root_field_rejected(app_with_auth):
    client = TestClient(app_with_auth)
    r = client.post(
        "/context",
        headers={"Authorization": "Bearer test-token-123"},
        json={
            "secretary_context_request": {"request_id": "x"},
            "extra_field": "not allowed",
        },
    )
    assert r.status_code == 422


def test_empty_envelope_rejected(app_with_auth):
    client = TestClient(app_with_auth)
    r = client.post(
        "/context",
        headers={"Authorization": "Bearer test-token-123"},
        json={"secretary_context_request": {}},
    )
    assert r.status_code == 422


def test_raw_private_key_rejected(app_with_auth):
    client = TestClient(app_with_auth)
    r = client.post(
        "/context",
        headers={"Authorization": "Bearer test-token-123"},
        json={"secretary_context_request": {"request_id": "x", "raw_private_data": "leak"}},
    )
    assert r.status_code == 422


def test_raw_private_key_nested_rejected(app_with_auth):
    client = TestClient(app_with_auth)
    r = client.post(
        "/context",
        headers={"Authorization": "Bearer test-token-123"},
        json={"secretary_context_request": {"request_id": "x", "nested": {"raw-private": "leak"}}},
    )
    assert r.status_code == 422


def test_raw_private_key_camel_rejected(app_with_auth):
    """rawPrivateKey (camelCase) must also be blocked."""
    client = TestClient(app_with_auth)
    r = client.post(
        "/context",
        headers={"Authorization": "Bearer test-token-123"},
        json={"secretary_context_request": {"request_id": "x", "rawPrivateKey": "leak"}},
    )
    assert r.status_code == 422


def test_invalid_request_id_pattern_returns_400(app_with_auth):
    """request_id with spaces fails validate_safe_request_id → 400."""
    client = TestClient(app_with_auth)
    r = client.post(
        "/context",
        headers={"Authorization": "Bearer test-token-123"},
        json={"secretary_context_request": {"request_id": "invalid with spaces"}},
    )
    assert r.status_code == 400


def test_invalid_request_id_too_long_returns_400(app_with_auth):
    """request_id > 160 chars → 400."""
    client = TestClient(app_with_auth)
    r = client.post(
        "/context",
        headers={"Authorization": "Bearer test-token-123"},
        json={"secretary_context_request": {"request_id": "a" * 161}},
    )
    assert r.status_code == 400


# ---------------------------------------------------------------------------
# HTTP method / path routing
# ---------------------------------------------------------------------------

def test_get_on_context_is_405(app_with_auth):
    client = TestClient(app_with_auth)
    r = client.get("/context")
    assert r.status_code == 405


def test_get_on_task_is_405(app_with_auth):
    client = TestClient(app_with_auth)
    r = client.get("/task")
    assert r.status_code == 405


def test_unknown_path_is_404(app_with_auth):
    client = TestClient(app_with_auth)
    r = client.post(
        "/unknown",
        headers={"Authorization": "Bearer test-token-123"},
        json={},
    )
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# Local-only enforcement
# ---------------------------------------------------------------------------

def test_non_local_host_rejected_at_boot():
    settings = Settings(
        http_server=HTTPServerSettings(enabled=True, host="0.0.0.0")
    )
    with pytest.raises(RuntimeError, match="local-only"):
        create_app(settings)


def test_localhost_string_accepted():
    settings = Settings(
        http_server=HTTPServerSettings(enabled=True, host="localhost")
    )
    app = create_app(settings)
    assert app is not None
