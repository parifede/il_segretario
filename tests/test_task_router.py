import pytest

from segretario.app.router import TaskRouter


class Agent:
    def run(self, request):
        return request.command


def test_task_router_returns_registered_agent():
    search_agent = Agent()
    router = TaskRouter({"search": search_agent})

    assert router.agent_for("search") is search_agent


def test_task_router_rejects_unknown_command():
    router = TaskRouter({})

    with pytest.raises(KeyError, match="unknown command"):
        router.agent_for("missing")
