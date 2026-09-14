"""Agent and Team hosts bind Prompt objects on ``instructions`` and ``system_message``.

Binding copies the Prompt, keeps the copy privately on the host, and leaves the
usable text in the public field the message builders already read. The host
config stores an identity-only reference. An unresolved reference-only Prompt
fails before the model runs, before run registration, and before any write.
"""

from typing import Any, AsyncIterator, Iterator, List, Optional
from unittest.mock import AsyncMock, MagicMock

import pytest

from agno.agent import Agent
from agno.db.base import SessionType
from agno.db.sqlite import SqliteDb
from agno.models.base import Model
from agno.models.message import Message, MessageMetrics
from agno.models.response import ModelResponse
from agno.prompt import Prompt
from agno.team import Team

BLOCKS = ["Be concise.", "Never expose private customer data."]


@pytest.fixture
def db(tmp_path):
    return SqliteDb(id="hosts-db", db_file=str(tmp_path / "hosts.db"))


class StubModel(Model):
    """Offline model that records the messages each call was asked to answer."""

    def __init__(self):
        super().__init__(id="stub", name="stub", provider="test")
        self.instructions = None
        self.calls: List[List[Message]] = []
        self._response = ModelResponse(content="ok", role="assistant", response_usage=MessageMetrics())

    def get_instructions_for_model(self, *args, **kwargs):
        return None

    def get_system_message_for_model(self, *args, **kwargs):
        return None

    async def aget_instructions_for_model(self, *args, **kwargs):
        return None

    async def aget_system_message_for_model(self, *args, **kwargs):
        return None

    def parse_args(self, *args, **kwargs):
        return {}

    def _record(self, kwargs) -> None:
        self.calls.append(list(kwargs.get("messages") or []))

    def invoke(self, *args, **kwargs) -> ModelResponse:
        self._record(kwargs)
        return self._response

    async def ainvoke(self, *args, **kwargs) -> ModelResponse:
        self._record(kwargs)
        return self._response

    def invoke_stream(self, *args, **kwargs) -> Iterator[ModelResponse]:
        self._record(kwargs)
        yield self._response

    async def ainvoke_stream(self, *args, **kwargs) -> AsyncIterator[ModelResponse]:
        self._record(kwargs)
        yield self._response
        return

    def _parse_provider_response(self, response: Any, **kwargs) -> ModelResponse:
        return self._response

    def _parse_provider_response_delta(self, response: Any) -> ModelResponse:
        return self._response


def _system_content(model: StubModel) -> Optional[str]:
    for message in model.calls[-1]:
        if message.role == "system":
            return message.content
    return None


def _member() -> Agent:
    return Agent(id="member", name="Member", model=StubModel(), instructions="Help the team.")


class TestAgentBinding:
    def test_instructions_string_lands_in_the_public_field(self):
        agent = Agent(instructions=Prompt(id="support", content="Be concise."))
        assert agent.instructions == "Be concise."

    def test_instructions_blocks_land_in_the_public_field(self):
        agent = Agent(instructions=Prompt(id="support", content=list(BLOCKS)))
        assert agent.instructions == BLOCKS

    def test_system_message_string_lands_in_the_public_field(self):
        agent = Agent(system_message=Prompt(id="sm", content="Custom system message"))
        assert agent.system_message == "Custom system message"

    def test_system_message_rejects_blocks(self):
        with pytest.raises(ValueError, match="`system_message`"):
            Agent(system_message=Prompt(id="sm", content=list(BLOCKS)))

    def test_system_message_rejects_block_fallback(self):
        with pytest.raises(ValueError, match="`system_message`"):
            Agent(system_message=Prompt(id="sm", fallback=list(BLOCKS)))

    def test_hosts_get_independent_copies(self):
        shared = Prompt(id="support", content=list(BLOCKS))
        first = Agent(instructions=shared)
        second = Agent(instructions=shared)
        first.instructions.append("Added on the first host only.")
        assert second.instructions == BLOCKS
        assert shared.content == BLOCKS

    def test_config_stores_an_identity_only_reference(self):
        agent = Agent(
            instructions=Prompt(id="support", content=list(BLOCKS), version="latest", fallback=["Answer safely."]),
            system_message=Prompt(id="sm", content="Custom wording", version=3),
        )
        config = agent.to_dict()
        assert config["instructions"] == {"prompt_id": "support", "version": "latest"}
        assert config["system_message"] == {"prompt_id": "sm", "version": 3}
        serialized = repr(config)
        assert "Be concise" not in serialized
        assert "Answer safely" not in serialized
        assert "Custom wording" not in serialized

    def test_plain_values_are_unchanged(self):
        assert Agent(instructions="plain").to_dict()["instructions"] == "plain"
        assert Agent(instructions=list(BLOCKS)).to_dict()["instructions"] == BLOCKS
        assert "instructions" not in Agent(instructions=lambda: "dynamic").to_dict()
        assert Agent(system_message="typed").to_dict()["system_message"] == "typed"
        assert "system_message" not in Agent(system_message=Message(role="system", content="x")).to_dict()

    def test_reassigning_the_field_drops_the_reference(self):
        agent = Agent(
            instructions=Prompt(id="support", content="Be concise."),
            system_message=Prompt(id="sm", content="Custom wording"),
        )
        agent.instructions = "typed by hand"
        agent.system_message = lambda: "dynamic"
        config = agent.to_dict()
        assert config["instructions"] == "typed by hand"
        assert "system_message" not in config

    def test_deep_copy_keeps_untouched_references(self):
        agent = Agent(instructions=Prompt(id="support", content=list(BLOCKS)))
        clone = agent.deep_copy()
        assert clone.instructions == BLOCKS
        assert clone.to_dict()["instructions"] == {"prompt_id": "support"}
        clone.instructions.append("clone only")
        assert agent.instructions == BLOCKS
        assert agent.to_dict()["instructions"] == {"prompt_id": "support"}

    def test_deep_copy_override_drops_the_reference(self):
        agent = Agent(instructions=Prompt(id="support", content="Be concise."))
        assert agent.deep_copy(update={"instructions": "override"}).to_dict()["instructions"] == "override"

    def test_deep_copy_override_with_a_prompt_binds_it(self):
        agent = Agent(instructions=Prompt(id="support", content="Be concise."))
        clone = agent.deep_copy(update={"instructions": Prompt(id="other", content="Other text")})
        assert clone.instructions == "Other text"
        assert clone.to_dict()["instructions"] == {"prompt_id": "other"}
        assert agent.to_dict()["instructions"] == {"prompt_id": "support"}

    def test_bound_text_reaches_the_model(self):
        model = StubModel()
        agent = Agent(model=model, instructions=Prompt(id="support", content=list(BLOCKS)))
        assert agent.run("hi").content == "ok"
        assert "Never expose private customer data." in _system_content(model)

    def test_bound_system_message_replaces_the_generated_one(self):
        model = StubModel()
        agent = Agent(model=model, description="ignored", system_message=Prompt(id="sm", content="Only this text."))
        agent.run("hi")
        assert _system_content(model) == "Only this text."

    def test_unresolved_reference_fails_before_registration_and_writes(self, db, monkeypatch):
        import agno.agent._run as agent_run

        spy = MagicMock()
        monkeypatch.setattr(agent_run, "register_run", spy)
        model = StubModel()
        agent = Agent(model=model, db=db, instructions=Prompt(id="missing"))
        with pytest.raises(ValueError, match="missing"):
            agent.run("hi")
        assert model.calls == []
        spy.assert_not_called()
        assert db.get_sessions(session_type=SessionType.AGENT) == []

    async def test_unresolved_reference_fails_before_registration_and_writes_async(self, db, monkeypatch):
        import agno.agent._run as agent_run

        spy = AsyncMock()
        monkeypatch.setattr(agent_run, "aregister_run", spy)
        model = StubModel()
        agent = Agent(model=model, db=db, system_message=Prompt(id="missing"))
        with pytest.raises(ValueError, match="missing"):
            await agent.arun("hi")
        assert model.calls == []
        spy.assert_not_called()
        assert db.get_sessions(session_type=SessionType.AGENT) == []


class TestTeamBinding:
    def test_instructions_blocks_land_in_the_public_field(self):
        team = Team(members=[_member()], instructions=Prompt(id="support", content=list(BLOCKS)))
        assert team.instructions == BLOCKS

    def test_instructions_string_lands_in_the_public_field(self):
        team = Team(members=[_member()], instructions=Prompt(id="support", content="Be concise."))
        assert team.instructions == "Be concise."

    def test_system_message_string_lands_in_the_public_field(self):
        team = Team(members=[_member()], system_message=Prompt(id="sm", content="Custom wording"))
        assert team.system_message == "Custom wording"

    def test_system_message_rejects_blocks(self):
        with pytest.raises(ValueError, match="`system_message`"):
            Team(members=[_member()], system_message=Prompt(id="sm", content=list(BLOCKS)))

    def test_hosts_get_independent_copies(self):
        shared = Prompt(id="support", content=list(BLOCKS))
        agent = Agent(instructions=shared)
        team = Team(members=[_member()], instructions=shared)
        team.instructions.append("Team only.")
        assert agent.instructions == BLOCKS
        assert shared.content == BLOCKS

    def test_config_stores_an_identity_only_reference(self):
        team = Team(
            members=[_member()],
            instructions=Prompt(id="support", content=list(BLOCKS), version="latest", fallback=["Answer safely."]),
            system_message=Prompt(id="sm", content="Custom wording", version=3),
        )
        config = team.to_dict()
        assert config["instructions"] == {"prompt_id": "support", "version": "latest"}
        assert config["system_message"] == {"prompt_id": "sm", "version": 3}
        serialized = repr(config)
        assert "Be concise" not in serialized
        assert "Answer safely" not in serialized
        assert "Custom wording" not in serialized

    def test_plain_values_are_unchanged(self):
        assert Team(members=[_member()], instructions="plain").to_dict()["instructions"] == "plain"
        assert "instructions" not in Team(members=[_member()], instructions=lambda: "dynamic").to_dict()
        assert Team(members=[_member()], system_message="typed").to_dict()["system_message"] == "typed"

    def test_reassigning_the_field_drops_the_reference(self):
        team = Team(members=[_member()], instructions=Prompt(id="support", content="Be concise."))
        team.instructions = "typed by hand"
        assert team.to_dict()["instructions"] == "typed by hand"

    def test_deep_copy_keeps_untouched_references(self):
        team = Team(members=[_member()], instructions=Prompt(id="support", content=list(BLOCKS)))
        clone = team.deep_copy()
        assert clone.to_dict()["instructions"] == {"prompt_id": "support"}
        clone.instructions.append("clone only")
        assert team.instructions == BLOCKS

    def test_deep_copy_override_drops_the_reference(self):
        team = Team(members=[_member()], instructions=Prompt(id="support", content="Be concise."))
        assert team.deep_copy(update={"instructions": "override"}).to_dict()["instructions"] == "override"

    def test_custom_system_message_is_a_total_replacement(self):
        model = StubModel()
        team = Team(model=model, members=[_member()], system_message=Prompt(id="sm", content="Only this text."))
        team.run("hi")
        assert _system_content(model) == "Only this text."

    def test_instructions_reach_the_generated_system_message(self):
        model = StubModel()
        team = Team(model=model, members=[_member()], instructions=Prompt(id="support", content=list(BLOCKS)))
        team.run("hi")
        assert "Never expose private customer data." in _system_content(model)

    def test_unresolved_reference_fails_before_registration_and_writes(self, db, monkeypatch):
        import agno.team._run as team_run

        spy = MagicMock()
        monkeypatch.setattr(team_run, "register_run", spy)
        model = StubModel()
        team = Team(model=model, members=[_member()], db=db, instructions=Prompt(id="missing"))
        with pytest.raises(ValueError, match="missing"):
            team.run("hi")
        assert model.calls == []
        spy.assert_not_called()
        assert db.get_sessions(session_type=SessionType.TEAM) == []

    async def test_unresolved_reference_fails_before_registration_and_writes_async(self, db, monkeypatch):
        import agno.team._run as team_run

        spy = AsyncMock()
        monkeypatch.setattr(team_run, "aregister_run", spy)
        model = StubModel()
        team = Team(model=model, members=[_member()], db=db, system_message=Prompt(id="missing"))
        with pytest.raises(ValueError, match="missing"):
            await team.arun("hi")
        assert model.calls == []
        spy.assert_not_called()
        assert db.get_sessions(session_type=SessionType.TEAM) == []
