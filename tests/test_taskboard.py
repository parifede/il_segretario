import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from segretario.taskboard import TaskStatus, TaskboardStore


EXPECTED_COLUMNS = [
    "id",
    "source",
    "requested_by",
    "command",
    "status",
    "risk",
    "assigned_agent",
    "requires_confirmation",
    "confirmation_reason",
    "input_ref",
    "output_ref",
    "audit_ref",
    "created_at",
    "updated_at",
    "lease_owner",
    "lease_expires_at",
    "retries",
    "last_error",
]


def test_initialize_creates_taskboard_schema(tmp_path):
    db_path = tmp_path / "taskboard.sqlite"

    store = TaskboardStore(db_path)
    store.initialize()

    with sqlite3.connect(db_path) as connection:
        columns = [
            row[1]
            for row in connection.execute("PRAGMA table_info(tasks)").fetchall()
        ]

    assert columns == EXPECTED_COLUMNS


def test_create_task_persists_defaults_and_valid_status(tmp_path):
    store = TaskboardStore(tmp_path / "taskboard.sqlite")
    store.initialize()

    task = store.create_task(
        source="cli",
        requested_by="operator",
        command="echo hello",
        risk="low",
        input_ref="input:1",
    )

    assert task["id"] == 1
    assert task["status"] == TaskStatus.QUEUED.value
    assert task["requires_confirmation"] is False
    assert task["retries"] == 0
    assert task["created_at"] == task["updated_at"]

    fetched = store.get_task(task["id"])
    assert fetched["command"] == "echo hello"
    assert fetched["input_ref"] == "input:1"


def test_update_task_rejects_unknown_status(tmp_path):
    store = TaskboardStore(tmp_path / "taskboard.sqlite")
    store.initialize()
    task = store.create_task(
        source="cli",
        requested_by="operator",
        command="run something",
        risk="medium",
    )

    try:
        store.update_task_status(task["id"], "mystery")
    except ValueError as exc:
        assert "unknown task status" in str(exc)
    else:
        raise AssertionError("expected ValueError for unknown task status")


def test_approve_task_moves_waiting_confirmation_back_to_queue(tmp_path):
    store = TaskboardStore(tmp_path / "taskboard.sqlite")
    store.initialize()
    task = store.create_task(
        source="cli",
        requested_by="operator",
        command="delete temp file",
        risk="high",
        requires_confirmation=True,
        confirmation_reason="destructive command",
    )
    task = store.get_task(task["id"])
    assert task["status"] == TaskStatus.WAITING_CONFIRMATION.value

    approved = store.approve_task(task["id"], audit_ref="audit:approve")

    assert approved["status"] == TaskStatus.QUEUED.value
    assert approved["requires_confirmation"] is False
    assert approved["confirmation_reason"] is None
    assert approved["audit_ref"] == "audit:approve"


def test_high_risk_task_waits_for_confirmation_by_default(tmp_path):
    store = TaskboardStore(tmp_path / "taskboard.sqlite")
    store.initialize()

    task = store.create_task(
        source="cli",
        requested_by="operator",
        command="delete file",
        risk="high",
    )

    assert task["status"] == TaskStatus.WAITING_CONFIRMATION.value
    assert task["requires_confirmation"] is True


def test_approve_task_rejects_non_confirmation_task(tmp_path):
    store = TaskboardStore(tmp_path / "taskboard.sqlite")
    store.initialize()
    task = store.create_task(
        source="cli",
        requested_by="operator",
        command="status",
        risk="low",
    )

    try:
        store.approve_task(task["id"])
    except ValueError as exc:
        assert "not waiting for confirmation" in str(exc)
    else:
        raise AssertionError("expected ValueError for non-confirmation task")


def test_deny_task_records_reason_and_terminal_status(tmp_path):
    store = TaskboardStore(tmp_path / "taskboard.sqlite")
    store.initialize()
    task = store.create_task(
        source="cli",
        requested_by="operator",
        command="send credentials",
        risk="high",
        requires_confirmation=True,
        confirmation_reason="sensitive output",
    )

    denied = store.deny_task(task["id"], reason="operator denied")

    assert denied["status"] == TaskStatus.DENIED.value
    assert denied["requires_confirmation"] is False
    assert denied["last_error"] == "operator denied"


def test_acquire_lease_claims_oldest_available_queued_task(tmp_path):
    store = TaskboardStore(tmp_path / "taskboard.sqlite")
    store.initialize()
    first = store.create_task(
        source="cli",
        requested_by="operator",
        command="first",
        risk="low",
    )
    store.create_task(
        source="cli",
        requested_by="operator",
        command="second",
        risk="low",
    )

    leased = store.acquire_lease(owner="worker-a", lease_seconds=30)

    assert leased is not None
    assert leased["id"] == first["id"]
    assert leased["status"] == TaskStatus.RUNNING.value
    assert leased["lease_owner"] == "worker-a"
    assert leased["assigned_agent"] == "worker-a"
    assert _is_future_timestamp(leased["lease_expires_at"])


def test_acquire_lease_skips_active_lease_and_reclaims_expired(tmp_path):
    store = TaskboardStore(tmp_path / "taskboard.sqlite")
    store.initialize()
    task = store.create_task(
        source="cli",
        requested_by="operator",
        command="work",
        risk="low",
    )

    first_lease = store.acquire_lease(owner="worker-a", lease_seconds=30)
    assert first_lease["id"] == task["id"]
    assert store.acquire_lease(owner="worker-b", lease_seconds=30) is None

    store.force_expire_lease(task["id"])
    reclaimed = store.acquire_lease(owner="worker-b", lease_seconds=30)

    assert reclaimed is not None
    assert reclaimed["id"] == task["id"]
    assert reclaimed["lease_owner"] == "worker-b"


def test_acquire_lease_for_commands_ignores_other_queued_tasks(tmp_path):
    store = TaskboardStore(tmp_path / "taskboard.sqlite")
    store.initialize()
    store.create_task(
        source="cli",
        requested_by="operator",
        command="mail.send",
        risk="low",
    )
    maintenance = store.create_task(
        source="scheduler",
        requested_by="segretario",
        command="maintenance.cycle",
        risk="low",
    )

    leased = store.acquire_lease_for_commands(
        owner="scheduler",
        lease_seconds=30,
        commands={"maintenance.cycle"},
    )

    assert leased["id"] == maintenance["id"]
    assert leased["command"] == "maintenance.cycle"
    assert store.get_task(1)["status"] == TaskStatus.QUEUED.value


def test_record_failure_requeues_until_max_retries_then_fails(tmp_path):
    store = TaskboardStore(tmp_path / "taskboard.sqlite")
    store.initialize()
    task = store.create_task(
        source="cli",
        requested_by="operator",
        command="flaky",
        risk="medium",
    )
    store.acquire_lease(owner="worker-a", lease_seconds=30)

    retry = store.record_failure(task["id"], error="temporary", max_retries=2)

    assert retry["status"] == TaskStatus.QUEUED.value
    assert retry["retries"] == 1
    assert retry["lease_owner"] is None
    assert retry["lease_expires_at"] is None
    assert retry["last_error"] == "temporary"

    leased_again = store.acquire_lease(owner="worker-a", lease_seconds=30)
    assert leased_again["id"] == task["id"]
    final = store.record_failure(task["id"], error="still broken", max_retries=2)

    assert final["status"] == TaskStatus.FAILED.value
    assert final["retries"] == 2
    assert final["last_error"] == "still broken"


def _is_future_timestamp(value):
    return datetime.fromisoformat(value) > datetime.now(timezone.utc)
