import json
import sys
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from segretario.audit import AuditLog


def read_jsonl(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_append_event_writes_redacted_payload_and_hash_chain(tmp_path):
    audit = AuditLog(tmp_path)

    first = audit.append_event(
        "task.created",
        {
            "task_id": 1,
            "command": "echo hello",
            "secret": "do-not-store",
            "token": "also-sensitive",
        },
    )
    second = audit.append_event("task.completed", {"task_id": 1, "status": "completed"})

    events = read_jsonl(tmp_path / "events.jsonl")
    chain = read_jsonl(tmp_path / "hash_chain.jsonl")

    assert first["sequence"] == 1
    assert second["sequence"] == 2
    assert events[0]["payload"]["secret"] == "[REDACTED]"
    assert events[0]["payload"]["token"] == "[REDACTED]"
    assert events[0]["payload"]["secret_hash"].startswith("sha256:")
    assert events[0]["payload"]["token_hash"].startswith("sha256:")
    assert "do-not-store" not in (tmp_path / "events.jsonl").read_text(
        encoding="utf-8"
    )
    assert chain[0]["previous_hash"] is None
    assert chain[1]["previous_hash"] == chain[0]["entry_hash"]
    assert audit.verify() is True


def test_verify_detects_tampered_event_payload(tmp_path):
    audit = AuditLog(tmp_path)
    audit.append_event("task.created", {"task_id": 1, "command": "safe"})

    events_path = tmp_path / "events.jsonl"
    event = read_jsonl(events_path)[0]
    event["payload"]["command"] = "changed"
    events_path.write_text(json.dumps(event, sort_keys=True) + "\n", encoding="utf-8")

    assert audit.verify() is False


def test_audit_log_accepts_configured_file_paths(tmp_path):
    events_path = tmp_path / "custom-events.jsonl"
    chain_path = tmp_path / "custom-chain.jsonl"
    audit = AuditLog(events_path=events_path, chain_path=chain_path)

    audit.append_event("task.created", {"task_id": 1})

    assert events_path.exists()
    assert chain_path.exists()
    assert audit.verify() is True


def test_redacts_common_secret_key_variants(tmp_path):
    audit = AuditLog(tmp_path)

    audit.append_event(
        "credentials.loaded",
        {
            "access_token": "secret-token",
            "refreshToken": "refresh-secret",
            "client_secret": "client-secret",
            "Authorization": "Bearer abc",
            "apiKey": "api-key",
        },
    )

    raw = (tmp_path / "events.jsonl").read_text(encoding="utf-8")
    assert "secret-token" not in raw
    assert "refresh-secret" not in raw
    assert "client-secret" not in raw
    assert "Bearer abc" not in raw
    assert "api-key" not in raw


def test_redacts_private_content_keys_with_hashes(tmp_path):
    audit = AuditLog(tmp_path)

    audit.append_event(
        "protected.file.read",
        {
            "source_path": "self/profile.md",
            "body": "full private profile body",
            "raw_text": "raw self note",
            "nested": {"content": "protected nested content"},
        },
    )

    event = read_jsonl(tmp_path / "events.jsonl")[0]
    payload = event["payload"]
    raw = (tmp_path / "events.jsonl").read_text(encoding="utf-8")
    assert "full private profile body" not in raw
    assert "raw self note" not in raw
    assert "protected nested content" not in raw
    assert payload["body"] == "[REDACTED]"
    assert payload["body_hash"].startswith("sha256:")
    assert payload["raw_text"] == "[REDACTED]"
    assert payload["raw_text_hash"].startswith("sha256:")
    assert payload["nested"]["content"] == "[REDACTED]"
    assert payload["nested"]["content_hash"].startswith("sha256:")


def test_concurrent_appends_keep_hash_chain_valid(tmp_path):
    audit_dir = tmp_path / "audit"

    def append(index: int) -> None:
        AuditLog(audit_dir).append_event("task.concurrent", {"task_id": index})

    with ThreadPoolExecutor(max_workers=8) as executor:
        list(executor.map(append, range(32)))

    events = read_jsonl(audit_dir / "events.jsonl")
    assert [event["sequence"] for event in events] == list(range(1, 33))
    assert AuditLog(audit_dir).verify() is True
