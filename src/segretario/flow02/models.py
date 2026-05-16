from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class IntentType(StrEnum):
    CONVERSATIONAL = "conversational"
    TASK = "task"
    MEMORY_LOOKUP = "memory_lookup"


class OutputPolicy(StrEnum):
    BOOLEAN_ONLY = "boolean_only"
    SUMMARIZED = "summarized"
    PRIVACY_PROJECTION = "privacy_projection"
    FREE = "free"


class DetailLevel(StrEnum):
    MINIMUM_NECESSARY = "minimum_necessary"
    SUMMARY = "summary"
    TECHNICAL = "technical"
    OPERATIONAL = "operational"


class RetryReason(StrEnum):
    GOAL_MISMATCH = "goal_mismatch"
    INCOMPLETE_OUTPUT = "incomplete_output"
    OUTPUT_MALFORMED = "output_malformed"
    PROMPT_INJECTION_DETECTED = "prompt_injection_detected"
    CONTRACT_VIOLATION = "contract_violation"


class RetryOutcome(StrEnum):
    ACCEPTED = "accepted"
    NEEDS_REFINEMENT = "needs_refinement"
    REJECTED = "rejected"


class WorkingMemoryTurn(BaseModel):
    role: str
    content: str
    timestamp: datetime
    tokens: int


class RiskAttestation(BaseModel):
    attestation_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    request_id: str
    internal_request_id: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    approved_context_projection: list[str]
    output_policy: OutputPolicy
    max_detail_level: DetailLevel
    allowed_next_steps: list[str]
    user_visible_goal: str


class SecretaryContextRequest(BaseModel):
    request_id: str
    internal_request_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    session_id: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    character_identity: str
    working_memory: list[WorkingMemoryTurn]
    working_memory_tokens: int
    recall_context: str | None
    recall_tokens: int
    attestation: RiskAttestation
    total_tokens: int


class SecretaryTaskRequest(BaseModel):
    context: SecretaryContextRequest
    user_message: str
    intent_type: IntentType
    user_visible_goal: str


class ZarsuitOutput(BaseModel):
    internal_request_id: str
    content: str
    cited_fields: list[str]
    suggested_next_steps: list[str]
    detail_level: DetailLevel
    raw_json: dict[str, Any] | None = None


class RetryAuditEvent(BaseModel):
    request_id: str
    internal_request_id: str
    attempt: int
    outcome: RetryOutcome
    reason: RetryReason | None
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
