from pathlib import Path

from typer.testing import CliRunner

from segretario.cli import app
from segretario.policies.output_guard import sanitize_user_output
from segretario.taskboard import TaskboardStore


def test_output_guard_removes_traceback_unless_debug():
    text = 'Traceback (most recent call last):\n  File "E:\\secret\\app.py", line 1\nValueError: boom'

    sanitized = sanitize_user_output(text)

    assert "Traceback" not in sanitized
    assert "File " not in sanitized
    assert sanitized == "error: ValueError: boom"
    assert "Traceback" in sanitize_user_output(text, debug=True)


def test_output_guard_redacts_oauth_tokens_and_sensitive_local_paths():
    text = (
        "access_token=ya29.SECRET_TOKEN "
        "Bearer abc.def.ghi "
        "E:\\il_segretario\\secrets\\google\\token.json "
        "E:\\il_segretario\\vault_dev\\self\\profile\\profile.md"
    )

    sanitized = sanitize_user_output(text)

    assert "ya29.SECRET_TOKEN" not in sanitized
    assert "abc.def.ghi" not in sanitized
    assert "secrets\\google\\token.json" not in sanitized
    assert "self\\profile\\profile.md" not in sanitized
    assert "[REDACTED_OAUTH_TOKEN]" in sanitized
    assert "[LOCAL_PRIVATE_PATH]" in sanitized


def test_output_guard_redacts_privacy_map_contents():
    text = 'meta/privacy_map.local.json {"PERSON_TOKEN_A": "Mario Rossi"}'

    sanitized = sanitize_user_output(text)

    assert "Mario Rossi" not in sanitized
    assert "PERSON_TOKEN_A" not in sanitized
    assert sanitized == "meta/privacy_map.local.json: [REDACTED_LOCAL_PRIVACY_MAP]"


def test_cli_task_show_filters_user_facing_output(tmp_path: Path, monkeypatch):
    vault = tmp_path / "vault"
    (vault / "meta").mkdir(parents=True)
    (vault / "AGENTS.md").write_text("# AGENTS\n", encoding="utf-8")
    (vault / "meta" / "index.md").write_text("# Index\n", encoding="utf-8")
    (vault / "meta" / "log.md").write_text("# Log\n", encoding="utf-8")
    config = tmp_path / "segretario.yaml"
    config.write_text(
        f"""
project_name: section19
vault:
  path: "{vault.as_posix()}"
taskboard:
  sqlite_path: "{(tmp_path / 'state' / 'taskboard.sqlite').as_posix()}"
audit:
  events_path: "{(tmp_path / 'state' / 'audit' / 'events.jsonl').as_posix()}"
  hash_chain_path: "{(tmp_path / 'state' / 'audit' / 'hash_chain.jsonl').as_posix()}"
""".strip(),
        encoding="utf-8",
    )
    monkeypatch.setenv("SEGRETARIO_CONFIG", str(config))
    taskboard = TaskboardStore(tmp_path / "state" / "taskboard.sqlite")
    taskboard.initialize()
    task = taskboard.create_task(
        source="cli",
        requested_by="owner",
        command="section19.output.guard",
        risk="low",
        input_ref="manual",
    )
    taskboard.cancel_task(
        int(task["id"]),
        reason=(
            "Traceback (most recent call last):\n"
            '  File "E:\\il_segretario\\secrets\\google\\token.json", line 1\n'
            "RuntimeError: access_token=ya29.SECTION19_SECRET"
        ),
    )

    result = CliRunner().invoke(app, ["task", "show", str(task["id"])])

    assert result.exit_code == 0
    assert "Traceback" not in result.output
    assert "ya29.SECTION19_SECRET" not in result.output
    assert "secrets\\google\\token.json" not in result.output
    assert "error: RuntimeError: access_token=[REDACTED_OAUTH_TOKEN]" in result.output


def test_output_guard_preserves_error_context_when_privacy_map_is_redacted():
    text = (
        'Traceback (most recent call last):\n  File "x", line 1\n'
        'RuntimeError: access_token=ya29.SECRET meta/privacy_map.local.json {"PERSON_TOKEN_A":"Mario"}'
    )

    sanitized = sanitize_user_output(text)

    assert sanitized.startswith("error: RuntimeError: access_token=[REDACTED_OAUTH_TOKEN]")
    assert "meta/privacy_map.local.json: [REDACTED_LOCAL_PRIVACY_MAP]" in sanitized
    assert "PERSON_TOKEN_A" not in sanitized
    assert "Mario" not in sanitized
