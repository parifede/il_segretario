from pathlib import Path

from typer.testing import CliRunner

from segretario.cli import app
from segretario.policies.output_guard import ExternalAnswerDecision, prepare_external_answer


def test_external_answer_allows_public_cloud_ok_knowledge_page(tmp_path: Path):
    vault = tmp_path / "vault"
    page = vault / "knowledge" / "public.md"
    page.parent.mkdir(parents=True)
    page.write_text(
        "---\ntitle: Public Note\nprivacy: public\ncloud_ok: true\n---\nPublic safe body.\n",
        encoding="utf-8",
    )

    result = prepare_external_answer(
        vault,
        source_path="knowledge/public.md",
        question="What can you share?",
    )

    assert result.decision == ExternalAnswerDecision.ALLOW
    assert "Public safe body." in result.answer


def test_external_answer_requires_projection_for_local_knowledge(tmp_path: Path):
    vault = tmp_path / "vault"
    page = vault / "knowledge" / "local.md"
    page.parent.mkdir(parents=True)
    page.write_text(
        "---\ntitle: Local Note\nprivacy: local\ncloud_ok: false\n---\nPRIVATE_RAW_BODY\n",
        encoding="utf-8",
    )

    result = prepare_external_answer(
        vault,
        source_path="knowledge/local.md",
        question="What can you share?",
    )

    assert result.decision == ExternalAnswerDecision.PROJECT
    assert "requires privacy projection" in result.answer
    assert "PRIVATE_RAW_BODY" not in result.answer


def test_external_answer_uses_projection_without_raw_local_body(tmp_path: Path):
    vault = tmp_path / "vault"
    page = vault / "knowledge" / "local.md"
    page.parent.mkdir(parents=True)
    page.write_text(
        "---\ntitle: Local Note\nprivacy: local\ncloud_ok: false\n---\nPRIVATE_RAW_BODY\n",
        encoding="utf-8",
    )

    result = prepare_external_answer(
        vault,
        source_path="knowledge/local.md",
        question="What can you share?",
        projection="A generic project note is available.",
    )

    assert result.decision == ExternalAnswerDecision.PROJECT
    assert result.answer == "A generic project note is available."
    assert "PRIVATE_RAW_BODY" not in result.answer


def test_external_answer_blocks_no_export_paths(tmp_path: Path):
    vault = tmp_path / "vault"
    page = vault / "self" / "profile.md"
    page.parent.mkdir(parents=True)
    page.write_text("PRIVATE_PROFILE_BODY\n", encoding="utf-8")

    result = prepare_external_answer(
        vault,
        source_path="self/profile.md",
        question="Who is the user?",
        projection="generic profile",
    )

    assert result.decision == ExternalAnswerDecision.BLOCK
    assert "blocked" in result.answer
    assert "PRIVATE_PROFILE_BODY" not in result.answer


def test_external_answer_blocks_raw_elaborati_without_reading_body(tmp_path: Path):
    vault = tmp_path / "vault"
    page = vault / "raw" / "elaborati" / "old.md"
    page.parent.mkdir(parents=True)
    page.write_text("ARCHIVED_RAW_BODY\n", encoding="utf-8")

    result = prepare_external_answer(
        vault,
        source_path="raw/elaborati/old.md",
        question="Can you share archived raw?",
        projection="generic archive note",
    )

    assert result.decision == ExternalAnswerDecision.BLOCK
    assert "blocked" in result.answer
    assert "ARCHIVED_RAW_BODY" not in result.answer


def test_external_answer_cli_records_task_and_audit_without_leaking_raw(
    tmp_path: Path,
    monkeypatch,
):
    vault = tmp_path / "vault"
    page = vault / "knowledge" / "local.md"
    page.parent.mkdir(parents=True)
    page.write_text(
        "---\ntitle: Local Note\nprivacy: local\ncloud_ok: false\n---\nPRIVATE_RAW_BODY\n",
        encoding="utf-8",
    )
    config = _write_config(tmp_path, vault)
    monkeypatch.setenv("SEGRETARIO_CONFIG", str(config))

    result = CliRunner().invoke(
        app,
        [
            "external",
            "answer",
            "What can another agent know?",
            "--source",
            "knowledge/local.md",
            "--projection",
            "A generic project note is available.",
        ],
    )

    assert result.exit_code == 0
    assert "A generic project note is available." in result.output
    assert "PRIVATE_RAW_BODY" not in result.output
    assert (tmp_path / "state" / "taskboard.sqlite").exists()
    assert (tmp_path / "state" / "audit" / "events.jsonl").exists()


def _write_config(tmp_path: Path, vault: Path) -> Path:
    config = tmp_path / "segretario.yaml"
    config.write_text(
        f"""
project_name: il_segretario
vault:
  path: "{vault.as_posix()}"
taskboard:
  sqlite_path: "{(tmp_path / 'state' / 'taskboard.sqlite').as_posix()}"
audit:
  events_path: "{(tmp_path / 'state' / 'audit' / 'events.jsonl').as_posix()}"
  hash_chain_path: "{(tmp_path / 'state' / 'audit' / 'hash_chain.jsonl').as_posix()}"
google:
  credentials_path: "{(tmp_path / 'secrets' / 'google' / 'credentials.json').as_posix()}"
  token_path: "{(tmp_path / 'secrets' / 'google' / 'token.json').as_posix()}"
""".strip(),
        encoding="utf-8",
    )
    return config
