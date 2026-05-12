from pathlib import Path

from segretario.agents.ingest_agent import IngestAgent
from segretario.agents.maintenance_agent import MaintenanceAgent
from segretario.agents.search_agent import SearchAgent
from segretario.agents.security_agent import SecurityAgent
from segretario.agents.wiki_maintainer_agent import WikiMaintainerAgent
from segretario.app.models import TaskRequest


def test_search_agent_returns_search_matches(tmp_path: Path):
    vault = tmp_path / "vault"
    (vault / "knowledge").mkdir(parents=True)
    (vault / "knowledge" / "Topic.md").write_text("alpha beta\n", encoding="utf-8")
    agent = SearchAgent()

    result = agent.run(
        TaskRequest(command="search", payload={"vault_path": vault, "query": "alpha"})
    )

    assert result[0]["path"] == "knowledge/Topic.md"


def test_maintenance_agent_runs_stats_and_lint(tmp_path: Path):
    vault = tmp_path / "vault"
    (vault / "knowledge").mkdir(parents=True)
    (vault / "knowledge" / "Topic.md").write_text("# Topic\n", encoding="utf-8")
    agent = MaintenanceAgent()

    stats = agent.run(TaskRequest(command="stats", payload={"vault_path": vault, "action": "stats"}))
    lint = agent.run(
        TaskRequest(command="lint.wiki", payload={"vault_path": vault, "action": "lint.wiki"})
    )

    assert stats["total_markdown"] == 1
    assert lint["report_path"].startswith("output/lint-")


def test_ingest_agent_wraps_ingest_article(tmp_path: Path):
    vault = tmp_path / "vault"
    source = vault / "raw" / "articles" / "source.md"
    source.parent.mkdir(parents=True)
    source.write_text("# Source Topic\n\nAlpha.\n", encoding="utf-8")
    agent = IngestAgent()

    result = agent.run(
        TaskRequest(
            command="ingest",
            payload={
                "vault_path": vault,
                "source_path": "raw/articles/source.md",
                "auto": True,
            },
        )
    )

    assert result["path"] == "knowledge/source-topic.md"


def test_security_agent_classifies_path(tmp_path: Path):
    agent = SecurityAgent()

    result = agent.run(
        TaskRequest(
            command="security.path",
            payload={
                "action": "classify_path",
                "path": "self/profile.md",
                "operation": "write",
            },
        )
    )

    assert result["local_only"] is True
    assert result["requires_confirmation"] is True


def test_wiki_maintainer_agent_ensures_index_and_appends_log(tmp_path: Path):
    vault = tmp_path / "vault"
    agent = WikiMaintainerAgent()

    index = agent.run(
        TaskRequest(
            command="meta.index.ensure",
            payload={"vault_path": vault, "action": "meta.index.ensure"},
        )
    )
    log = agent.run(
        TaskRequest(
            command="meta.log.append",
            payload={
                "vault_path": vault,
                "action": "meta.log.append",
                "entry": "- maintained index",
            },
        )
    )

    assert index["path"] == "meta/index.md"
    assert (vault / "meta" / "index.md").exists()
    assert log["path"] == "meta/log.md"
    assert "- maintained index\n" in (vault / "meta" / "log.md").read_text(
        encoding="utf-8"
    )
