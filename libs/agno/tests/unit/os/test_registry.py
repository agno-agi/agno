"""Two distinct components sharing an id resolve differently per surface.

The registry keeps the first one it sees, so Studio and registry-backed
dispatch resolve that one - while the AgentOS keeps serving the object it was
constructed with over HTTP. Nothing raises and nothing is discarded, so the
warning has to name both halves, or the reader assumes the second one lost.
"""

from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS
from agno.registry import Registry
from agno.team import Team


def _model():
    return OpenAIResponses(id="gpt-5.5")


def _agent(agent_id: str, name: str) -> Agent:
    return Agent(id=agent_id, name=name, model=_model())


def _team(team_id: str, name: str) -> Team:
    return Team(id=team_id, name=name, members=[_agent(f"{team_id}-member", "Member")], model=_model())


def _collisions(caplog, kind: str):
    return [r.message for r in caplog.records if f"multiple distinct {kind} share id" in r.message]


class TestDuplicateAgentIds:
    def test_the_registry_and_the_os_keep_different_objects(self, caplog):
        first, second = _agent("dup", "First"), _agent("dup", "Second")
        registry = Registry(name="R", agents=[first])

        with caplog.at_level("WARNING"):
            agent_os = AgentOS(agents=[second], registry=registry)

        # Both assertions hold before the message was reworded: they are the
        # regression guard proving the new wording describes what happens.
        assert registry.get_agent("dup") is first
        assert agent_os.agents is not None and agent_os.agents[0] is second

    def test_the_warning_names_both_surfaces(self, caplog):
        registry = Registry(name="R", agents=[_agent("dup", "First")])

        with caplog.at_level("WARNING"):
            AgentOS(agents=[_agent("dup", "Second")], registry=registry)

        messages = _collisions(caplog, "agents")
        assert messages, [r.message for r in caplog.records]
        assert any("registry keeps the first" in message for message in messages)
        assert any("keeps serving the one it was constructed with" in message for message in messages)

    def test_one_object_under_one_id_is_silent(self, caplog):
        shared = _agent("shared", "Shared")
        registry = Registry(name="R", agents=[shared])

        with caplog.at_level("WARNING"):
            AgentOS(agents=[shared], registry=registry)

        assert _collisions(caplog, "agents") == []


class TestDuplicateTeamIds:
    def test_the_registry_and_the_os_keep_different_objects(self, caplog):
        first, second = _team("dup", "First"), _team("dup", "Second")
        registry = Registry(name="R", teams=[first])

        with caplog.at_level("WARNING"):
            agent_os = AgentOS(teams=[second], registry=registry)

        assert registry.get_team("dup") is first
        assert agent_os.teams is not None and agent_os.teams[0] is second

    def test_the_warning_names_both_surfaces(self, caplog):
        registry = Registry(name="R", teams=[_team("dup", "First")])

        with caplog.at_level("WARNING"):
            AgentOS(teams=[_team("dup", "Second")], registry=registry)

        messages = _collisions(caplog, "teams")
        assert messages, [r.message for r in caplog.records]
        assert any("registry keeps the first" in message for message in messages)
        assert any("keeps serving the one it was constructed with" in message for message in messages)

    def test_one_object_under_one_id_is_silent(self, caplog):
        shared = _team("shared", "Shared")
        registry = Registry(name="R", teams=[shared])

        with caplog.at_level("WARNING"):
            AgentOS(teams=[shared], registry=registry)

        assert _collisions(caplog, "teams") == []
