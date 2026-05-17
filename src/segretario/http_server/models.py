from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, Field, model_validator


_SAFE_REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9_.:-]{1,160}$")


def _has_raw_private_key(obj: Any) -> bool:
    """Recursive check mirroring hasRawPrivateKey() in secretaryClient.js."""
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
    """Mirror of requireSafeRequestId in zarsos-secretary-stub.mjs."""
    if not isinstance(value, str):
        raise ValueError("request_id must be a string")
    if not _SAFE_REQUEST_ID_RE.match(value):
        raise ValueError("request_id must match pattern [A-Za-z0-9_.:-]{1,160}")
    return value


class ContextRequestBody(BaseModel):
    secretary_context_request: dict[str, Any] = Field(...)

    model_config = {"extra": "forbid"}

    @model_validator(mode="after")
    def validate_envelope(self) -> "ContextRequestBody":
        if not self.secretary_context_request:
            raise ValueError("secretary_context_request must be a non-empty object")
        if _has_raw_private_key(self.secretary_context_request):
            raise ValueError("raw-private keys are not allowed")
        return self


class TaskRequestBody(BaseModel):
    secretary_task_request: dict[str, Any] = Field(...)

    model_config = {"extra": "forbid"}

    @model_validator(mode="after")
    def validate_envelope(self) -> "TaskRequestBody":
        if not self.secretary_task_request:
            raise ValueError("secretary_task_request must be a non-empty object")
        if _has_raw_private_key(self.secretary_task_request):
            raise ValueError("raw-private keys are not allowed")
        return self
