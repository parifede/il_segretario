from __future__ import annotations

from enum import StrEnum

from segretario.app.models import RiskLevel


class PermissionDecision(StrEnum):
    ALLOW = "allow"
    CONFIRM = "confirm"
    DENY = "deny"
    PROJECT = "project"


class PermissionKernel:
    VAULT_READ = "vault.read"
    VAULT_SEARCH = "vault.search"
    KNOWLEDGE_WRITE = "knowledge.write"
    OUTPUT_WRITE = "output.write"
    META_INDEX_UPDATE = "meta.index.update"
    META_LOG_APPEND = "meta.log.append"
    GMAIL_READ = "gmail.read"
    GMAIL_DRAFT = "gmail.draft"
    SHELL_EXECUTE = "shell.execute"
    GMAIL_SEND = "gmail.send"
    GMAIL_DELETE = "gmail.delete"
    GMAIL_ARCHIVE = "gmail.archive"
    CALENDAR_READ = "calendar.read"
    CALENDAR_CREATE = "calendar.create"
    CALENDAR_SCHEDULE = "calendar.schedule"
    CALENDAR_CREATE_WITH_ATTENDEES = "calendar.create_with_attendees"
    CALENDAR_MODIFY = "calendar.modify"
    CALENDAR_DELETE = "calendar.delete"
    CALENDAR_ACCEPT = "calendar.accept"
    CALENDAR_DECLINE = "calendar.decline"
    WEB_PUBLIC_QUERY = "web.public_query"
    WEB_PRIVATE_CONTEXT_QUERY = "web.private_context_query"
    EXTERNAL_ANSWER = "external.answer"
    PRIVACY_MAP_READ = "privacy_map.read"
    SELF_PROFILE_WRITE = "self.profile.write"
    SELF_INTERESTS_WRITE = "self.interests.write"
    SELF_CHARACTER_WRITE = "self.character.write"
    SELF_SKILLS_WRITE = "self.skills.write"
    SELF_THOUGHTS_WRITE = "self.thoughts.write"
    SELF_WELLNESS_WRITE = "self.wellness.write"
    POLICY_MODIFY = "policy.modify"
    CONFIG_MODIFY = "config.modify"
    FILE_DELETE = "file.delete"

    DENY_BY_DEFAULT = frozenset({SHELL_EXECUTE})
    ALLOWED = frozenset(
        {
            VAULT_READ,
            VAULT_SEARCH,
            KNOWLEDGE_WRITE,
            OUTPUT_WRITE,
            META_INDEX_UPDATE,
            META_LOG_APPEND,
            GMAIL_READ,
            GMAIL_DRAFT,
            CALENDAR_READ,
            CALENDAR_CREATE,
            CALENDAR_SCHEDULE,
            WEB_PUBLIC_QUERY,
            EXTERNAL_ANSWER,
            PRIVACY_MAP_READ,
        }
    )
    REQUIRES_PROJECTION = frozenset({WEB_PRIVATE_CONTEXT_QUERY})
    REQUIRES_CONFIRMATION = frozenset(
        {
            GMAIL_SEND,
            GMAIL_DELETE,
            GMAIL_ARCHIVE,
            CALENDAR_CREATE_WITH_ATTENDEES,
            CALENDAR_MODIFY,
            CALENDAR_DELETE,
            CALENDAR_ACCEPT,
            CALENDAR_DECLINE,
            SELF_PROFILE_WRITE,
            SELF_INTERESTS_WRITE,
            SELF_CHARACTER_WRITE,
            SELF_SKILLS_WRITE,
            SELF_THOUGHTS_WRITE,
            SELF_WELLNESS_WRITE,
            POLICY_MODIFY,
            CONFIG_MODIFY,
            FILE_DELETE,
        }
    )

    @classmethod
    def decision_for(cls, action: str) -> PermissionDecision:
        if action in cls.ALLOWED:
            return PermissionDecision.ALLOW
        if action in cls.REQUIRES_CONFIRMATION:
            return PermissionDecision.CONFIRM
        if action in cls.REQUIRES_PROJECTION:
            return PermissionDecision.PROJECT
        return PermissionDecision.DENY


class RiskClassifier:
    LOW_RISK = PermissionKernel.ALLOWED
    MEDIUM_RISK = frozenset({PermissionKernel.WEB_PRIVATE_CONTEXT_QUERY})
    HIGH_RISK = PermissionKernel.REQUIRES_CONFIRMATION
    CRITICAL_RISK = frozenset({PermissionKernel.SHELL_EXECUTE})

    _ORDER = {
        RiskLevel.LOW.value: 0,
        RiskLevel.MEDIUM.value: 1,
        RiskLevel.HIGH.value: 2,
        RiskLevel.CRITICAL.value: 3,
    }

    @classmethod
    def risk_for(cls, action: str, *, requested_risk: str | None = None) -> str:
        classified = cls._classified_risk(action)
        if requested_risk is None:
            return classified
        if cls._ORDER.get(requested_risk, 0) > cls._ORDER[classified]:
            return requested_risk
        return classified

    @classmethod
    def _classified_risk(cls, action: str) -> str:
        if action in cls.CRITICAL_RISK:
            return RiskLevel.CRITICAL.value
        if action in cls.HIGH_RISK:
            return RiskLevel.HIGH.value
        if action in cls.MEDIUM_RISK:
            return RiskLevel.MEDIUM.value
        if action in cls.LOW_RISK:
            return RiskLevel.LOW.value
        return RiskLevel.CRITICAL.value
