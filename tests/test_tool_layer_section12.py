from __future__ import annotations

import ast
from pathlib import Path
import sqlite3

from typer.testing import CliRunner

from segretario.cli import app


def test_required_tool_classes_are_importable():
    from segretario.tools.calendar_tool import CalendarTool
    from segretario.tools.filesystem_tool import FilesystemTool
    from segretario.tools.gmail_tool import GmailTool
    from segretario.tools.markdown_tool import MarkdownTool
    from segretario.tools.ollama_tool import OllamaTool
    from segretario.tools.search_tool import SearchTool
    from segretario.tools.vault_tool import VaultTool
    from segretario.tools.web_tool import WebTool

    assert {
        VaultTool.__name__,
        MarkdownTool.__name__,
        SearchTool.__name__,
        WebTool.__name__,
        GmailTool.__name__,
        CalendarTool.__name__,
        FilesystemTool.__name__,
        OllamaTool.__name__,
    } == {
        "VaultTool",
        "MarkdownTool",
        "SearchTool",
        "WebTool",
        "GmailTool",
        "CalendarTool",
        "FilesystemTool",
        "OllamaTool",
    }


def test_agent_modules_do_not_perform_direct_side_effect_calls():
    forbidden_attrs = {"write_text", "open", "mkdir", "unlink", "rmdir"}
    agents_root = Path("src/segretario/agents")
    violations: list[str] = []

    for path in sorted(agents_root.glob("*_agent.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                if node.func.attr in forbidden_attrs:
                    violations.append(f"{path}:{node.lineno}:{node.func.attr}")

    assert violations == []


def test_agent_runner_records_tool_audit_events_around_side_effect(tmp_path: Path, monkeypatch):
    config = _write_config(tmp_path)
    monkeypatch.setenv("SEGRETARIO_CONFIG", str(config))
    runner = CliRunner()
    archive = runner.invoke(app, ["mail", "archive", "msg_tool_audit"])
    task_id = _latest_task_id(tmp_path)
    runner.invoke(app, ["approve", str(task_id)])

    run = runner.invoke(app, ["agents", "run-once"])

    assert archive.exit_code == 1
    assert run.exit_code == 0
    event_types = (tmp_path / "state" / "audit" / "events.jsonl").read_text(
        encoding="utf-8"
    )
    assert '"event_type":"tool.requested"' in event_types
    assert '"event_type":"tool.completed"' in event_types


def _write_config(tmp_path: Path) -> Path:
    vault = tmp_path / "vault"
    vault.mkdir()
    config = tmp_path / "segretario.yaml"
    config.write_text(
        f"""
project_name: section12_tool_layer
vault:
  path: "{vault.as_posix()}"
taskboard:
  sqlite_path: "{(tmp_path / 'state' / 'taskboard.sqlite').as_posix()}"
audit:
  events_path: "{(tmp_path / 'state' / 'audit' / 'events.jsonl').as_posix()}"
  hash_chain_path: "{(tmp_path / 'state' / 'audit' / 'hash_chain.jsonl').as_posix()}"
google:
  enabled: false
  credentials_path: "{(tmp_path / 'secrets' / 'google' / 'credentials.json').as_posix()}"
  token_path: "{(tmp_path / 'secrets' / 'google' / 'token.json').as_posix()}"
""".strip(),
        encoding="utf-8",
    )
    return config


def _latest_task_id(tmp_path: Path) -> int:
    db = sqlite3.connect(tmp_path / "state" / "taskboard.sqlite")
    return db.execute("select id from tasks order by id desc limit 1").fetchone()[0]
