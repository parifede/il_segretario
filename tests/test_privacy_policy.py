from segretario.policies.privacy import (
    knowledge_export_decision,
    project_private_context,
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


def test_project_private_context_tokenizes_sensitive_identifiers_and_generalizes_details():
    raw = (
        "Mario Rossi ha 37 anni, email mario.rossi@example.com, telefono +39 333 123 4567, "
        "CF RSSMRA80A01H501U, IBAN IT60X0542811101000000123456, targa AB123CD. "
        "Vive in Via Roma 10, Milano, guadagna 42000 euro, lavora come senior backend engineer "
        "presso Acme S.p.A. e ha diabete tipo 2."
    )

    projected = project_private_context(raw)

    for leaked in (
        "Mario Rossi",
        "mario.rossi@example.com",
        "+39 333 123 4567",
        "RSSMRA80A01H501U",
        "IT60X0542811101000000123456",
        "AB123CD",
        "Via Roma 10",
        "42000",
        "senior backend engineer",
        "Acme S.p.A.",
        "diabete tipo 2",
    ):
        assert leaked not in projected.text

    assert "PERSON_TOKEN_A" in projected.text
    assert "EMAIL_TOKEN_A" in projected.text
    assert "PHONE_TOKEN_A" in projected.text
    assert "ID_TOKEN_A" in projected.text
    assert "BANK_TOKEN_A" in projected.text
    assert "VEHICLE_TOKEN_A" in projected.text
    assert "area urbana di Milano" in projected.text
    assert "30-39 age band" in projected.text
    assert "income band 40k-60k" in projected.text
    assert "technical role band" in projected.text
    assert "ORG_TOKEN_A" in projected.text
    assert "broad health category" in projected.text
