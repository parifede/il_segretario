from __future__ import annotations

from dataclasses import asdict
import json
from pathlib import Path

from segretario.app.models import TaskRequest


class TaskPayloadStore:
    def __init__(self, state_dir: str | Path):
        self.state_dir = Path(state_dir)
        self.payload_dir = self.state_dir / "task_payloads"

    def save(self, task_id: int, request: TaskRequest) -> str:
        self.payload_dir.mkdir(parents=True, exist_ok=True)
        relative_path = Path("task_payloads") / f"task-{task_id}.json"
        path = self.state_dir / relative_path
        path.write_text(
            json.dumps(asdict(request), sort_keys=True, indent=2, default=str),
            encoding="utf-8",
        )
        return relative_path.as_posix()

    def load(self, input_ref: str) -> TaskRequest:
        if not input_ref.startswith("task_payloads/"):
            raise ValueError("task has no executable payload")
        path = self.state_dir / input_ref
        data = json.loads(path.read_text(encoding="utf-8"))
        return TaskRequest(
            command=str(data["command"]),
            payload=dict(data.get("payload") or {}),
            risk=str(data.get("risk") or "low"),
            action=data.get("action"),
            source=str(data.get("source") or "cli"),
            requested_by=str(data.get("requested_by") or "owner"),
        )
