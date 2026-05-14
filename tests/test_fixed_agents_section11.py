from pathlib import Path

import pytest

from segretario.agents.calendar_agent import CalendarAgent
from segretario.agents.ingest_agent import IngestAgent
from segretario.agents.mail_agent import MailAgent
from segretario.agents.maintenance_agent import MaintenanceAgent
from segretario.agents.research_agent import ResearchAgent
from segretario.agents.search_agent import SearchAgent
from segretario.agents.security_agent import SecurityAgent
from segretario.agents.wiki_maintainer_agent import WikiMaintainerAgent
from segretario.app.models import TaskRequest


def test_fixed_agents_declare_allowed_actions_and_tools():
    expectations = {
        SearchAgent: ({"search"}, {"SearchTool"}),
        IngestAgent: ({"ingest"}, {"MarkdownTool", "VaultTool"}),
        WikiMaintainerAgent: (
            {"meta.index.ensure", "meta.log.append"},
            {"MarkdownTool", "VaultTool"},
        ),
        ResearchAgent: ({"link", "web.query"}, {"WebTool", "IngestAgent"}),
        MailAgent: (
            {"mail.read", "mail.draft", "mail.send", "mail.archive", "mail.delete"},
            {"GmailTool"},
        ),
        CalendarAgent: (
            {
                "calendar.list",
                "calendar.read",
                "calendar.create",
                "calendar.schedule",
                "calendar.modify",
                "calendar.delete",
                "calendar.accept",
                "calendar.decline",
            },
            {"CalendarTool"},
        ),
        MaintenanceAgent: (
            {
                "stats",
                "lint.wiki",
                "relink.dry_run",
                "relink.apply",
                "repair.index.dry_run",
                "repair.index.apply",
                "repair.raw_plan",
            },
            {"MarkdownTool", "SearchTool", "VaultTool"},
        ),
        SecurityAgent: (
            {"classify_path", "security.path", "knowledge.export", "web.query", "external.answer"},
            {"SecurityPolicy", "OutputGuard"},
        ),
    }

    for agent_cls, (actions, tools) in expectations.items():
        assert agent_cls.allowed_actions == frozenset(actions)
        assert agent_cls.allowed_tools == frozenset(tools)


def test_mail_agent_rejects_action_outside_its_fixed_boundary(tmp_path: Path):
    agent = MailAgent()

    with pytest.raises(ValueError, match="MailAgent cannot handle action"):
        agent.run(
            TaskRequest(
                command="calendar.delete",
                payload={"state_dir": tmp_path},
            )
        )


def test_calendar_agent_rejects_action_outside_its_fixed_boundary(tmp_path: Path):
    agent = CalendarAgent()

    with pytest.raises(ValueError, match="CalendarAgent cannot handle action"):
        agent.run(
            TaskRequest(
                command="mail.send",
                payload={"state_dir": tmp_path},
            )
        )
