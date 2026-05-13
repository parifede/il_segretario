from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
from typing import Any


class TaskStatus(Enum):
    QUEUED = "queued"
    RUNNING = "running"
    WAITING_CONFIRMATION = "waiting_confirmation"
    COMPLETED = "completed"
    FAILED = "failed"
    DENIED = "denied"
    CANCELLED = "cancelled"


TASK_COLUMNS = [
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


class TaskboardStore:
    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)

    def initialize(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS tasks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source TEXT NOT NULL,
                    requested_by TEXT NOT NULL,
                    command TEXT NOT NULL,
                    status TEXT NOT NULL,
                    risk TEXT NOT NULL,
                    assigned_agent TEXT,
                    requires_confirmation INTEGER NOT NULL DEFAULT 0,
                    confirmation_reason TEXT,
                    input_ref TEXT,
                    output_ref TEXT,
                    audit_ref TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    lease_owner TEXT,
                    lease_expires_at TEXT,
                    retries INTEGER NOT NULL DEFAULT 0,
                    last_error TEXT
                )
                """
            )

    def create_task(
        self,
        *,
        source: str,
        requested_by: str,
        command: str,
        risk: str,
        assigned_agent: str | None = None,
        requires_confirmation: bool = False,
        confirmation_reason: str | None = None,
        input_ref: str | None = None,
        output_ref: str | None = None,
        audit_ref: str | None = None,
    ) -> dict[str, Any]:
        now = _utc_now()
        must_confirm = requires_confirmation or risk in {"high", "critical"}
        initial_status = (
            TaskStatus.WAITING_CONFIRMATION.value
            if must_confirm
            else TaskStatus.QUEUED.value
        )
        with self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO tasks (
                    source, requested_by, command, status, risk, assigned_agent,
                    requires_confirmation, confirmation_reason, input_ref,
                    output_ref, audit_ref, created_at, updated_at, retries
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    source,
                    requested_by,
                    command,
                    initial_status,
                    risk,
                    assigned_agent,
                    int(must_confirm),
                    confirmation_reason,
                    input_ref,
                    output_ref,
                    audit_ref,
                    now,
                    now,
                    0,
                ),
            )
            task_id = cursor.lastrowid

        task = self.get_task(int(task_id))
        if task is None:
            raise RuntimeError("created task could not be loaded")
        return task

    def get_task(self, task_id: int) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                f"SELECT {', '.join(TASK_COLUMNS)} FROM tasks WHERE id = ?",
                (task_id,),
            ).fetchone()
        return _task_from_row(row) if row is not None else None

    def has_active_command(self, command: str) -> bool:
        active_statuses = (
            TaskStatus.QUEUED.value,
            TaskStatus.RUNNING.value,
            TaskStatus.WAITING_CONFIRMATION.value,
        )
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT 1 FROM tasks
                WHERE command = ?
                  AND status IN (?, ?, ?)
                LIMIT 1
                """,
                (command, *active_statuses),
            ).fetchone()
        return row is not None

    def list_tasks(
        self,
        *,
        limit: int = 20,
        status: str | TaskStatus | None = None,
    ) -> list[dict[str, Any]]:
        query = f"SELECT {', '.join(TASK_COLUMNS)} FROM tasks"
        parameters: tuple[Any, ...]
        if status is None:
            parameters = ()
        else:
            query += " WHERE status = ?"
            parameters = (_status_value(status),)
        query += " ORDER BY id DESC LIMIT ?"
        parameters = (*parameters, limit)
        with self._connect() as connection:
            rows = connection.execute(query, parameters).fetchall()
        return [_task_from_row(row) for row in rows]

    def update_task_status(self, task_id: int, status: str | TaskStatus) -> dict[str, Any]:
        status_value = _status_value(status)
        terminal_statuses = {
            TaskStatus.COMPLETED.value,
            TaskStatus.FAILED.value,
            TaskStatus.DENIED.value,
            TaskStatus.CANCELLED.value,
        }
        with self._connect() as connection:
            if status_value in terminal_statuses:
                connection.execute(
                    """
                    UPDATE tasks
                    SET status = ?,
                        lease_owner = NULL,
                        lease_expires_at = NULL,
                        updated_at = ?
                    WHERE id = ?
                    """,
                    (status_value, _utc_now(), task_id),
                )
            else:
                connection.execute(
                    "UPDATE tasks SET status = ?, updated_at = ? WHERE id = ?",
                    (status_value, _utc_now(), task_id),
                )
        task = self.get_task(task_id)
        if task is None:
            raise KeyError(f"unknown task id: {task_id}")
        return task

    def complete_task(
        self,
        task_id: int,
        *,
        output_ref: str | None = None,
    ) -> dict[str, Any]:
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE tasks
                SET status = ?,
                    output_ref = COALESCE(?, output_ref),
                    lease_owner = NULL,
                    lease_expires_at = NULL,
                    updated_at = ?
                WHERE id = ?
                """,
                (TaskStatus.COMPLETED.value, output_ref, _utc_now(), task_id),
            )
        return self._require_task(task_id)

    def update_input_ref(self, task_id: int, input_ref: str) -> dict[str, Any]:
        with self._connect() as connection:
            connection.execute(
                "UPDATE tasks SET input_ref = ?, updated_at = ? WHERE id = ?",
                (input_ref, _utc_now(), task_id),
            )
        return self._require_task(task_id)

    def approve_task(self, task_id: int, audit_ref: str | None = None) -> dict[str, Any]:
        task = self._require_task(task_id)
        if (
            task["status"] != TaskStatus.WAITING_CONFIRMATION.value
            or not task["requires_confirmation"]
        ):
            raise ValueError(f"task {task_id} is not waiting for confirmation")
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE tasks
                SET status = ?,
                    requires_confirmation = 0,
                    confirmation_reason = NULL,
                    audit_ref = COALESCE(?, audit_ref),
                    updated_at = ?
                WHERE id = ?
                """,
                (TaskStatus.QUEUED.value, audit_ref, _utc_now(), task_id),
            )
        return self._require_task(task_id)

    def deny_task(self, task_id: int, reason: str | None = None) -> dict[str, Any]:
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE tasks
                SET status = ?,
                    requires_confirmation = 0,
                    lease_owner = NULL,
                    lease_expires_at = NULL,
                    last_error = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (TaskStatus.DENIED.value, reason, _utc_now(), task_id),
            )
        return self._require_task(task_id)

    def acquire_lease(
        self,
        *,
        owner: str,
        lease_seconds: int,
    ) -> dict[str, Any] | None:
        now = _utc_now()
        expires_at = _utc_now_plus(seconds=lease_seconds)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                f"""
                SELECT {', '.join(TASK_COLUMNS)}
                FROM tasks
                WHERE status = ?
                   OR (
                        status = ?
                        AND lease_expires_at IS NOT NULL
                        AND lease_expires_at <= ?
                   )
                ORDER BY id
                LIMIT 1
                """,
                (TaskStatus.QUEUED.value, TaskStatus.RUNNING.value, now),
            ).fetchone()
            if row is None:
                return None

            task_id = row["id"]
            connection.execute(
                """
                UPDATE tasks
                SET status = ?,
                    assigned_agent = ?,
                    lease_owner = ?,
                    lease_expires_at = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (
                    TaskStatus.RUNNING.value,
                    owner,
                    owner,
                    expires_at,
                    now,
                    task_id,
                ),
            )
            updated = connection.execute(
                f"SELECT {', '.join(TASK_COLUMNS)} FROM tasks WHERE id = ?",
                (task_id,),
            ).fetchone()

        return _task_from_row(updated)

    def acquire_lease_for_commands(
        self,
        *,
        owner: str,
        lease_seconds: int,
        commands: set[str],
    ) -> dict[str, Any] | None:
        if not commands:
            return None
        now = _utc_now()
        expires_at = _utc_now_plus(seconds=lease_seconds)
        placeholders = ", ".join("?" for _ in commands)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                f"""
                SELECT {', '.join(TASK_COLUMNS)}
                FROM tasks
                WHERE command IN ({placeholders})
                  AND (
                    status = ?
                    OR (
                        status = ?
                        AND lease_expires_at IS NOT NULL
                        AND lease_expires_at <= ?
                    )
                  )
                ORDER BY id
                LIMIT 1
                """,
                (
                    *sorted(commands),
                    TaskStatus.QUEUED.value,
                    TaskStatus.RUNNING.value,
                    now,
                ),
            ).fetchone()
            if row is None:
                return None

            task_id = row["id"]
            connection.execute(
                """
                UPDATE tasks
                SET status = ?,
                    assigned_agent = ?,
                    lease_owner = ?,
                    lease_expires_at = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (
                    TaskStatus.RUNNING.value,
                    owner,
                    owner,
                    expires_at,
                    now,
                    task_id,
                ),
            )
            updated = connection.execute(
                f"SELECT {', '.join(TASK_COLUMNS)} FROM tasks WHERE id = ?",
                (task_id,),
            ).fetchone()

        return _task_from_row(updated)

    def start_queued_task(
        self,
        task_id: int,
        *,
        owner: str,
        lease_seconds: int,
    ) -> dict[str, Any]:
        task = self._require_task(task_id)
        if task["status"] != TaskStatus.QUEUED.value:
            raise ValueError(f"task {task_id} is not queued")
        if task["requires_confirmation"]:
            raise ValueError(f"task {task_id} still requires confirmation")
        now = _utc_now()
        expires_at = _utc_now_plus(seconds=lease_seconds)
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE tasks
                SET status = ?,
                    assigned_agent = ?,
                    lease_owner = ?,
                    lease_expires_at = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (
                    TaskStatus.RUNNING.value,
                    owner,
                    owner,
                    expires_at,
                    now,
                    task_id,
                ),
            )
        return self._require_task(task_id)

    def force_expire_lease(self, task_id: int) -> dict[str, Any]:
        with self._connect() as connection:
            connection.execute(
                "UPDATE tasks SET lease_expires_at = ?, updated_at = ? WHERE id = ?",
                (_utc_now_plus(seconds=-1), _utc_now(), task_id),
            )
        return self._require_task(task_id)

    def record_failure(
        self,
        task_id: int,
        *,
        error: str,
        max_retries: int,
    ) -> dict[str, Any]:
        task = self._require_task(task_id)
        retries = int(task["retries"]) + 1
        status = (
            TaskStatus.FAILED.value
            if retries >= max_retries
            else TaskStatus.QUEUED.value
        )
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE tasks
                SET status = ?,
                    retries = ?,
                    last_error = ?,
                    lease_owner = NULL,
                    lease_expires_at = NULL,
                    updated_at = ?
                WHERE id = ?
                """,
                (status, retries, error, _utc_now(), task_id),
            )
        return self._require_task(task_id)

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        return connection

    def _require_task(self, task_id: int) -> dict[str, Any]:
        task = self.get_task(task_id)
        if task is None:
            raise KeyError(f"unknown task id: {task_id}")
        return task


def _status_value(status: str | TaskStatus) -> str:
    if isinstance(status, TaskStatus):
        return status.value
    values = {candidate.value for candidate in TaskStatus}
    if status not in values:
        raise ValueError(f"unknown task status: {status}")
    return status


def _task_from_row(row: sqlite3.Row) -> dict[str, Any]:
    task = dict(row)
    task["requires_confirmation"] = bool(task["requires_confirmation"])
    return task


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _utc_now_plus(*, seconds: int) -> str:
    return (datetime.now(timezone.utc) + timedelta(seconds=seconds)).isoformat()
