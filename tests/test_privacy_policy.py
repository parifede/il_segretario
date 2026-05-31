from segretario.policies.privacy import (
    knowledge_export_decision,
    project_private_context,
    web_query_decision,
)
from segretario.http_server.context_handler import _strip_recall_headers


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


# ---------------------------------------------------------------------------
# PHONE false-positive fix: ISO datetime protection
# ---------------------------------------------------------------------------

def test_iso_datetime_not_replaced_as_phone():
    """ISO date-time like '2026-05-08 18:53' must not become PHONE_TOKEN."""
    text = "Sessione del 2026-05-08 18:53 gestita localmente."
    projected = project_private_context(text)
    assert "PHONE_TOKEN" not in projected.text
    assert "2026-05-08" in projected.text
    assert "18:53" in projected.text


def test_iso_date_only_not_replaced_as_phone():
    """Plain ISO date '2026-05-08' must not become PHONE_TOKEN."""
    text = "Backup eseguito il 2026-05-08."
    projected = project_private_context(text)
    assert "PHONE_TOKEN" not in projected.text
    assert "2026-05-08" in projected.text


def test_standalone_time_not_replaced_as_phone():
    """Standalone time '18:23' must not become PHONE_TOKEN."""
    text = "L'appuntamento è alle 18:23 di domani."
    projected = project_private_context(text)
    assert "PHONE_TOKEN" not in projected.text
    assert "18:23" in projected.text


def test_real_phone_still_tokenized_after_datetime_fix():
    """Real phone numbers must still be replaced after the ISO date protection."""
    text = "Chiamami al +39 333 1234567 domani."
    projected = project_private_context(text)
    assert "PHONE_TOKEN_A" in projected.text
    assert "+39 333 1234567" not in projected.text


def test_phone_and_datetime_in_same_text():
    """Datetime is kept, phone is replaced, in the same text."""
    text = "Il 2026-05-08 18:53 ho chiamato il +39 06 12345678."
    projected = project_private_context(text)
    assert "2026-05-08" in projected.text
    assert "PHONE_TOKEN_A" in projected.text
    assert "+39 06 12345678" not in projected.text


# ---------------------------------------------------------------------------
# Header strip: _strip_recall_headers
# ---------------------------------------------------------------------------

_SAMPLE_RECALL = (
    "### knowledge\\zarsuit-capabilities.md [§ Backup] (chunk 10, score: 0.786)\n"
    "Backup locali in E:\\ZARSUIT_LOCAL_BACKUPS.\n"
    "\n"
    "### self\\zarsuit_profile\\conversation-log.md "
    "[§ 2026-05-08 18:53 | handled_by: local] (chunk 24, score: 0.744)\n"
    "del vault con 345 file accessibili a livello locale."
)


def test_strip_recall_headers_removes_hash_lines():
    stripped = _strip_recall_headers(_SAMPLE_RECALL)
    assert "###" not in stripped
    assert not any(line.startswith("#") for line in stripped.splitlines())


def test_strip_recall_headers_removes_vault_paths():
    stripped = _strip_recall_headers(_SAMPLE_RECALL)
    assert "knowledge\\" not in stripped
    assert "self\\" not in stripped


def test_strip_recall_headers_removes_chunk_and_score():
    stripped = _strip_recall_headers(_SAMPLE_RECALL)
    assert "chunk" not in stripped
    assert "score:" not in stripped.lower()


def test_strip_recall_headers_keeps_content():
    stripped = _strip_recall_headers(_SAMPLE_RECALL)
    assert "Backup locali" in stripped
    assert "del vault con 345 file" in stripped


def test_strip_recall_headers_strips_inline_markdown_headings():
    """Markdown headings inside content (### Opzione A) must also be stripped."""
    text = (
        "### knowledge\\info.md [§ Section] (chunk 0, score: 0.9)\n"
        "### Opzione A: testo A\n"
        "Prosa normale.\n"
        "## Opzione B: testo B\n"
        "Altra prosa."
    )
    stripped = _strip_recall_headers(text)
    assert "###" not in stripped
    assert "##" not in stripped
    # Content text must survive
    assert "testo A" in stripped
    assert "Prosa normale" in stripped
    assert "Altra prosa" in stripped


def test_strip_recall_headers_no_change_on_plain_text():
    plain = "Questo è testo normale senza intestazioni recall."
    assert _strip_recall_headers(plain) == plain
