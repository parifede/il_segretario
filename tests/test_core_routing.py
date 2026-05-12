import hashlib
import json
from pathlib import Path

from segretario.app.core import SegretarioCore
from segretario.app.models import TaskRequest
from segretario.app.router import TaskRouter
from segretario.audit import AuditLog
from segretario.taskboard import TaskStatus, TaskboardStore


class RecordingAgent:
    def __init__(self) -> None:
        self.requests = []

    def run(self, request: TaskRequest):
        self.requests.append(request)
        return {"message": "agent result", "path": "knowledge/topic.md"}


def test_core_creates_task_dispatches_agent_and_audits_success(tmp_path: Path):
    taskboard = TaskboardStore(tmp_path / "taskboard.sqlite")
    taskboard.initialize()
    audit = AuditLog(tmp_path / "audit")
    agent = RecordingAgent()
    core = SegretarioCore(
        taskboard=taskboard,
        audit=audit,
        router=TaskRouter({"search": agent}),
    )

    result = core.handle(
        TaskRequest(
            command="search",
            payload={"query": "alpha"},
            risk="low",
            action="vault.search",
        )
    )

    assert result.ok is True
    assert result.output["message"] == "agent result"
    assert len(agent.requests) == 1
    task = taskboard.get_task(result.task_id)
    assert task["status"] == TaskStatus.COMPLETED.value
    expected_input_ref = hashlib.sha256(
        json.dumps(
            {"query": "alpha"},
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    assert task["input_ref"] == f"sha256:{expected_input_ref}"
    assert audit.verify() is True


def test_core_confirmation_required_task_does_not_dispatch(tmp_path: Path):
    taskboard = TaskboardStore(tmp_path / "taskboard.sqlite")
    taskboard.initialize()
    audit = AuditLog(tmp_path / "audit")
    agent = RecordingAgent()
    core = SegretarioCore(
        taskboard=taskboard,
        audit=audit,
        router=TaskRouter({"delete": agent}),
    )

    result = core.handle(
        TaskRequest(
            command="delete",
            payload={"path": "knowledge/topic.md"},
            risk="high",
            action="file.delete",
        )
    )

    assert result.ok is False
    assert "requires confirmation" in result.message
    assert agent.requests == []
    task = taskboard.get_task(result.task_id)
    assert task["status"] == TaskStatus.WAITING_CONFIRMATION.value
    assert audit.verify() is True


def test_core_denied_task_does_not_dispatch(tmp_path: Path):
    taskboard = TaskboardStore(tmp_path / "taskboard.sqlite")
    taskboard.initialize()
    audit = AuditLog(tmp_path / "audit")
    agent = RecordingAgent()
    core = SegretarioCore(
        taskboard=taskboard,
        audit=audit,
        router=TaskRouter({"shell": agent}),
    )

    result = core.handle(
        TaskRequest(
            command="shell",
            payload={"command": "whoami"},
            risk="critical",
            action="shell.execute",
        )
    )

    assert result.ok is False
    assert "denied" in result.message
    assert agent.requests == []
    task = taskboard.get_task(result.task_id)
    assert task["status"] == TaskStatus.DENIED.value
    assert audit.verify() is True


def test_core_projection_required_task_waits_for_confirmation_not_queue(tmp_path: Path):
    taskboard = TaskboardStore(tmp_path / "taskboard.sqlite")
    taskboard.initialize()
    audit = AuditLog(tmp_path / "audit")
    agent = RecordingAgent()
    core = SegretarioCore(
        taskboard=taskboard,
        audit=audit,
        router=TaskRouter({"web": agent}),
    )

    result = core.handle(
        TaskRequest(
            command="web",
            payload={"query": "private"},
            risk="medium",
            action="web.private_context_query",
        )
    )

    assert result.ok is False
    assert "projection" in result.message
    assert agent.requests == []
    task = taskboard.get_task(result.task_id)
    assert task["status"] == TaskStatus.WAITING_CONFIRMATION.value
    assert task["requires_confirmation"] is True
    assert taskboard.acquire_lease(owner="worker", lease_seconds=30) is None
