from __future__ import annotations

from enum import StrEnum


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
    CALENDAR_CREATE_WITH_ATTENDEES = "calendar.create_with_attendees"
    CALENDAR_MODIFY = "calendar.modify"
    CALENDAR_DELETE = "calendar.delete"
    WEB_PUBLIC_QUERY = "web.public_query"
    WEB_PRIVATE_CONTEXT_QUERY = "web.private_context_query"
    SELF_PROFILE_WRITE = "self.profile.write"
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
            WEB_PUBLIC_QUERY,
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
            SELF_PROFILE_WRITE,
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
