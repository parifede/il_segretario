from segretario.policies.privacy import (
    knowledge_export_decision,
    web_query_decision,
)


def test_knowledge_is_local_by_default_without_public_frontmatter():
    decision = knowledge_export_decision("knowledge/project.md", frontmatter={})

    assert decision.local_only is True
    assert decision.export_allowed is False


def test_knowledge_can_export_only_when_public_and_cloud_ok():
    decision = knowledge_export_decision(
        "knowledge/project.md",
        frontmatter={"privacy": "public", "cloud_ok": True},
    )

    assert decision.local_only is False
    assert decision.export_allowed is True


def test_public_privacy_without_cloud_ok_stays_local():
    decision = knowledge_export_decision(
        "knowledge/project.md",
        frontmatter={"privacy": "public"},
    )

    assert decision.local_only is True
    assert decision.export_allowed is False


def test_web_query_with_private_context_requires_projection():
    decision = web_query_decision(context_privacy="private")

    assert decision.allowed is False
    assert decision.requires_projection is True


def test_web_query_with_projected_context_is_allowed():
    decision = web_query_decision(context_privacy="projected")

    assert decision.allowed is True
    assert decision.requires_projection is False


def test_knowledge_export_rejects_parent_traversal():
    try:
        knowledge_export_decision(
            "knowledge/../self/profile.md",
            frontmatter={"privacy": "public", "cloud_ok": True},
        )
    except ValueError as exc:
        assert "parent traversal" in str(exc)
    else:
        raise AssertionError("expected ValueError for parent traversal")
