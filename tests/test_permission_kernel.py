from segretario.app.models import RiskLevel
from segretario.policies.permissions import (
    PermissionDecision,
    PermissionKernel,
    RiskClassifier,
)


def test_low_risk_actions_are_allowed():
    for action in (
        PermissionKernel.VAULT_READ,
        PermissionKernel.VAULT_SEARCH,
        PermissionKernel.KNOWLEDGE_WRITE,
        PermissionKernel.OUTPUT_WRITE,
        PermissionKernel.META_INDEX_UPDATE,
        PermissionKernel.META_LOG_APPEND,
        PermissionKernel.GMAIL_READ,
        PermissionKernel.GMAIL_DRAFT,
        PermissionKernel.CALENDAR_READ,
        PermissionKernel.CALENDAR_CREATE,
        PermissionKernel.WEB_PUBLIC_QUERY,
        PermissionKernel.EXTERNAL_ANSWER,
        PermissionKernel.PRIVACY_MAP_READ,
    ):
        assert PermissionKernel.decision_for(action) == PermissionDecision.ALLOW


def test_shell_execution_is_denied_by_default():
    assert PermissionKernel.decision_for(PermissionKernel.SHELL_EXECUTE) == PermissionDecision.DENY


def test_gmail_sensitive_actions_require_confirmation():
    for action in (
        PermissionKernel.GMAIL_SEND,
        PermissionKernel.GMAIL_DELETE,
        PermissionKernel.GMAIL_ARCHIVE,
    ):
        assert PermissionKernel.decision_for(action) == PermissionDecision.CONFIRM


def test_calendar_mutations_require_confirmation():
    for action in (
        PermissionKernel.CALENDAR_MODIFY,
        PermissionKernel.CALENDAR_DELETE,
        PermissionKernel.CALENDAR_CREATE_WITH_ATTENDEES,
        PermissionKernel.CALENDAR_ACCEPT,
        PermissionKernel.CALENDAR_DECLINE,
    ):
        assert PermissionKernel.decision_for(action) == PermissionDecision.CONFIRM


def test_web_private_context_query_requires_projection():
    assert (
        PermissionKernel.decision_for(PermissionKernel.WEB_PRIVATE_CONTEXT_QUERY)
        == PermissionDecision.PROJECT
    )


def test_profile_policy_config_and_file_delete_require_confirmation():
    for action in (
        PermissionKernel.SELF_PROFILE_WRITE,
        PermissionKernel.SELF_INTERESTS_WRITE,
        PermissionKernel.SELF_CHARACTER_WRITE,
        PermissionKernel.SELF_SKILLS_WRITE,
        PermissionKernel.SELF_THOUGHTS_WRITE,
        PermissionKernel.SELF_WELLNESS_WRITE,
        PermissionKernel.POLICY_MODIFY,
        PermissionKernel.CONFIG_MODIFY,
        PermissionKernel.FILE_DELETE,
    ):
        assert PermissionKernel.decision_for(action) == PermissionDecision.CONFIRM


def test_unknown_actions_are_denied_by_default():
    assert PermissionKernel.decision_for("unknown.action") == PermissionDecision.DENY


def test_risk_classifier_assigns_spec_risk_levels():
    assert RiskClassifier.risk_for(PermissionKernel.VAULT_SEARCH) == RiskLevel.LOW.value
    assert (
        RiskClassifier.risk_for(PermissionKernel.WEB_PRIVATE_CONTEXT_QUERY)
        == RiskLevel.MEDIUM.value
    )
    assert RiskClassifier.risk_for(PermissionKernel.GMAIL_SEND) == RiskLevel.HIGH.value
    assert RiskClassifier.risk_for(PermissionKernel.SHELL_EXECUTE) == RiskLevel.CRITICAL.value


def test_risk_classifier_keeps_more_conservative_requested_risk():
    assert (
        RiskClassifier.risk_for(
            PermissionKernel.VAULT_SEARCH,
            requested_risk=RiskLevel.HIGH.value,
        )
        == RiskLevel.HIGH.value
    )
    assert (
        RiskClassifier.risk_for(
            PermissionKernel.GMAIL_SEND,
            requested_risk=RiskLevel.LOW.value,
        )
        == RiskLevel.HIGH.value
    )
