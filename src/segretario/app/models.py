from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class RiskLevel(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass(frozen=True)
class TaskRequest:
    command: str
    payload: dict[str, Any] = field(default_factory=dict)
    risk: str = RiskLevel.LOW.value
    action: str | None = None
    source: str = "cli"
    requested_by: str = "owner"


@dataclass(frozen=True)
class CoreResult:
    ok: bool
    task_id: int
    message: str
    output: Any = None
