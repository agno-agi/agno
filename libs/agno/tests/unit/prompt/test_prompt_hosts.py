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
from agno.db.base import ComponentType, SessionType
from agno.db.sqlite import SqliteDb
from agno.exceptions import ComponentPinError, ComponentRehydrationError
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


def _plain_member() -> Agent:
    # Persistence tests need a member the catalog can rebuild; the stub model provider cannot be.
    return Agent(id="member", name="Member", instructions="Help the team.")


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


def _publish(db, prompt_id="support", content="one", **fields):
    return Prompt(id=prompt_id, content=content, **fields).save(db=db)


def _handle(host, field):
    # The retained relationship is private; the matrix tests read it to prove what was resolved.
    return host._prompt_handles[field]


def _state(host, field):
    handle = _handle(host, field)
    return (handle.requested_version, handle.resolved_version, handle.source, handle.fallback, handle.fallback_reason)


class TestAgentPersistence:
    @pytest.mark.parametrize("field, position", [("system_message", 0), ("instructions", 1)])
    @pytest.mark.parametrize("selector, stored, reference", [(None, 1, 1), (1, 1, 1), ("latest", None, "latest")])
    def test_round_trip(self, db, field, position, selector, stored, reference):
        _publish(db)
        agent = Agent(id="a", **{field: Prompt(id="support", version=selector)})
        assert agent.save(db=db) == 1
        [link] = db.get_links("a", version=1)
        assert (link["link_kind"], link["link_key"], link["child_component_id"]) == ("prompt", field, "support")
        assert (link["child_version"], link["position"]) == (stored, position)
        assert db.get_config("a", version=1)["config"][field] == {"prompt_id": "support", "version": reference}
        loaded = Agent.load("a", db=db)
        assert getattr(loaded, field) == "one"
        assert _state(loaded, field) == (stored, 1, "published", False, None)

    def test_instruction_blocks_round_trip(self, db):
        _publish(db, content=list(BLOCKS))
        Agent(id="a", instructions=Prompt(id="support")).save(db=db)
        assert Agent.load("a", db=db).instructions == BLOCKS

    def test_omitted_version_pins_the_current_version_for_good(self, db):
        _publish(db, content="one")
        agent = Agent(id="a", instructions=Prompt(id="support"))
        agent.save(db=db)
        assert agent.to_dict()["instructions"] == {"prompt_id": "support", "version": 1}
        _publish(db, content="two")
        assert Agent.load("a", db=db).instructions == "one"

    def test_latest_refreshes_only_on_the_next_load(self, db):
        _publish(db, content="one")
        Agent(id="a", instructions=Prompt(id="support", version="latest")).save(db=db)
        loaded = Agent.load("a", db=db)
        _publish(db, content="two")
        assert loaded.instructions == "one"
        assert _state(loaded, "instructions") == (None, 1, "published", False, None)
        reloaded = Agent.load("a", db=db)
        assert reloaded.instructions == "two"
        assert _state(reloaded, "instructions") == (None, 2, "published", False, None)
        assert db.get_links("a", version=1)[0]["child_version"] is None

    @pytest.mark.parametrize("run", [1, 2])
    def test_two_consumers_two_loads_no_leak(self, db, run):
        _publish(db, content="one")
        Agent(id="pinned", instructions=Prompt(id="support")).save(db=db)
        Agent(id="floating", instructions=Prompt(id="support", version="latest")).save(db=db)
        _publish(db, content="two")
        for _ in range(2):
            assert Agent.load("pinned", db=db).instructions == "one"
            assert Agent.load("floating", db=db).instructions == "two"

    def test_fallback_lives_in_link_meta_only(self, db):
        _publish(db)
        Agent(id="a", instructions=Prompt(id="support", version="latest", fallback=["Answer safely."])).save(db=db)
        [link] = db.get_links("a", version=1)
        assert link["meta"] == {"fallback": ["Answer safely."]}
        assert db.get_config("a", version=1)["config"]["instructions"] == {"prompt_id": "support", "version": "latest"}
        assert "Answer safely" not in repr(db.get_config("support", version=1))

    def test_host_save_never_publishes_prompt_content(self, db, monkeypatch):
        _publish(db, content="one")
        monkeypatch.setattr(Prompt, "save", MagicMock(side_effect=AssertionError("host saves must not publish")))
        Agent(id="a", instructions=Prompt(id="support", content="one")).save(db=db)
        assert db.get_component("support")["current_version"] == 1

    def test_conflicting_inline_content_is_refused_before_any_write(self, db):
        _publish(db, content="one")
        with pytest.raises(ValueError, match=r"Prompt\.save\(\)"):
            Agent(id="a", instructions=Prompt(id="support", content="different")).save(db=db)
        assert db.get_component("a") is None
        assert db.get_component("support")["current_version"] == 1

    @pytest.mark.parametrize(
        "prepare, selector, message",
        [
            (lambda db: None, None, "not an active Prompt"),
            (
                lambda db: (
                    db.upsert_component(component_id="support", component_type=ComponentType.PROMPT, name="support"),
                    db.upsert_config(component_id="support", config={"type": "prompt", "content": "draft"}),
                ),
                None,
                "no published version",
            ),
            (lambda db: (_publish(db), Prompt(id="support").delete(db=db)), None, "not an active Prompt"),
            (
                lambda db: db.create_component_with_config(
                    component_id="support",
                    component_type=ComponentType.AGENT,
                    name="support",
                    config={"instructions": "x"},
                    stage="published",
                ),
                None,
                "not an active Prompt",
            ),
            (lambda db: _publish(db), 7, "version 7"),
        ],
        ids=["missing", "draft-only", "archived", "wrong-type", "unpublished-pin"],
    )
    def test_save_rejects_unpublishable_targets_before_any_write(self, db, prepare, selector, message):
        prepare(db)
        with pytest.raises(ValueError, match=message):
            Agent(id="a", instructions=Prompt(id="support", version=selector)).save(db=db)
        assert db.get_component("a") is None


def _saved_agent(db, *, version=None, fallback=None):
    _publish(db, content="one")
    _publish(db, content="two")
    agent = Agent(id="a", instructions=Prompt(id="support", version=version, fallback=fallback))
    agent.save(db=db)
    return agent


def _drop_prompt(db, republish=None):
    # A hard delete also removes the consumer's link rows (catalog semantics), so it models a
    # replaced Prompt whose versions restart; archiving keeps the links and leaves no usable version.
    if republish is None:
        db.delete_component("support", require_no_dependents=False)
        return
    db.delete_component("support", hard_delete=True, require_no_dependents=False)
    Prompt(id="support", content=republish).save(db=db)


class TestResolutionMatrix:
    def test_pinned_exists(self, db):
        _saved_agent(db, version=1)
        for strict in (True, False):
            loaded = Agent.load("a", db=db, strict=strict)
            assert loaded.instructions == "one"
            assert _state(loaded, "instructions") == (1, 1, "published", False, None)

    def test_pinned_missing_current_exists(self, db):
        _saved_agent(db, version=2)
        _drop_prompt(db, republish="fresh")
        with pytest.raises(ComponentPinError, match="version 2"):
            Agent.load("a", db=db, strict=True)
        loaded = Agent.load("a", db=db, strict=False)
        assert loaded.instructions == "fresh"
        assert _state(loaded, "instructions") == (2, 1, "published", True, "pinned_version_missing")

    def test_pinned_missing_current_missing_inline_fallback(self, db):
        _saved_agent(db, version=2, fallback=["Answer safely."])
        _drop_prompt(db)
        with pytest.raises(ComponentPinError):
            Agent.load("a", db=db, strict=True)
        loaded = Agent.load("a", db=db, strict=False)
        assert loaded.instructions == ["Answer safely."]
        assert _state(loaded, "instructions") == (2, None, "inline", True, "pinned_version_missing")

    def test_pinned_missing_current_missing_no_fallback(self, db):
        _saved_agent(db, version=2)
        _drop_prompt(db)
        with pytest.raises(ComponentPinError):
            Agent.load("a", db=db, strict=True)
        with pytest.raises(ComponentRehydrationError):
            Agent.load("a", db=db, strict=False)

    def test_latest_current_exists(self, db):
        _saved_agent(db, version="latest")
        for strict in (True, False):
            loaded = Agent.load("a", db=db, strict=strict)
            assert loaded.instructions == "two"
            assert _state(loaded, "instructions") == (None, 2, "published", False, None)

    def test_latest_current_missing_inline_fallback(self, db):
        _saved_agent(db, version="latest", fallback="Answer safely.")
        _drop_prompt(db)
        with pytest.raises(ComponentRehydrationError):
            Agent.load("a", db=db, strict=True)
        loaded = Agent.load("a", db=db, strict=False)
        assert loaded.instructions == "Answer safely."
        assert _state(loaded, "instructions") == (None, None, "inline", True, "no_current_version")

    def test_latest_current_missing_no_fallback(self, db):
        _saved_agent(db, version="latest")
        _drop_prompt(db)
        for strict in (True, False):
            with pytest.raises(ComponentRehydrationError):
                Agent.load("a", db=db, strict=strict)

    def test_archived_prompt_counts_as_missing(self, db):
        _saved_agent(db, version=2, fallback="Answer safely.")
        db.delete_component("support", require_no_dependents=False)
        with pytest.raises(ComponentPinError):
            Agent.load("a", db=db, strict=True)
        assert Agent.load("a", db=db, strict=False).instructions == "Answer safely."

    def test_wrong_component_type_never_substitutes_its_text(self, db):
        db.create_component_with_config(
            component_id="helper",
            component_type=ComponentType.AGENT,
            name="helper",
            config={"instructions": "helper text"},
            stage="published",
        )
        db.create_component_with_config(
            component_id="a",
            component_type=ComponentType.AGENT,
            name="a",
            config={"instructions": {"prompt_id": "helper", "version": 1}},
            stage="published",
            links=[
                {
                    "link_kind": "prompt",
                    "link_key": "instructions",
                    "child_component_id": "helper",
                    "child_version": 1,
                    "position": 1,
                }
            ],
        )
        with pytest.raises(ComponentPinError):
            Agent.load("a", db=db, strict=True)
        with pytest.raises(ComponentRehydrationError):
            Agent.load("a", db=db, strict=False)

    def test_malformed_reference_raises_in_both_modes(self, db):
        db.create_component_with_config(
            component_id="a",
            component_type=ComponentType.AGENT,
            name="a",
            config={"instructions": {"prompt_id": 5}},
            stage="published",
        )
        for strict in (True, False):
            with pytest.raises(ValueError, match="`id`"):
                Agent.load("a", db=db, strict=strict)

    def test_database_failure_propagates_in_both_modes(self, db, monkeypatch):
        _saved_agent(db, version=1, fallback="Answer safely.")
        original = db.get_config

        def failing(component_id, *args, **kwargs):
            if component_id == "support":
                raise RuntimeError("database down")
            return original(component_id, *args, **kwargs)

        monkeypatch.setattr(db, "get_config", failing)
        for strict in (True, False):
            with pytest.raises(RuntimeError, match="database down"):
                Agent.load("a", db=db, strict=strict)

    def test_resave_after_fallback_keeps_the_requested_pin(self, db):
        _saved_agent(db, version=2)
        _drop_prompt(db, republish="fresh")
        loaded = Agent.load("a", db=db, strict=False)
        assert loaded.instructions == "fresh"
        assert loaded.save(db=db) == 2
        [link] = db.get_links("a", version=2)
        assert link["child_version"] == 2
        assert db.get_config("a", version=2)["config"]["instructions"] == {"prompt_id": "support", "version": 2}
        assert db.get_component("support")["current_version"] == 1


class TestTeamPersistence:
    @pytest.mark.parametrize("field, position", [("system_message", 0), ("instructions", 1)])
    @pytest.mark.parametrize("selector, stored", [(None, 1), ("latest", None)])
    def test_round_trip(self, db, field, position, selector, stored):
        _publish(db)
        team = Team(id="t", members=[_plain_member()], **{field: Prompt(id="support", version=selector)})
        assert team.save(db=db) == 1
        prompt_links = [link for link in db.get_links("t", version=1) if link["link_kind"] == "prompt"]
        assert [(link["link_key"], link["child_version"], link["position"]) for link in prompt_links] == [
            (field, stored, position)
        ]
        loaded = Team.load("t", db=db)
        assert getattr(loaded, field) == "one"
        assert _state(loaded, field) == (stored, 1, "published", False, None)

    def test_member_links_and_prompt_links_coexist(self, db):
        _publish(db, content="one")
        member = Agent(id="m", instructions=Prompt(id="support"))
        team = Team(id="t", members=[member], instructions=Prompt(id="support", version="latest"))
        team.save(db=db)
        kinds = sorted(link["link_kind"] for link in db.get_links("t", version=1))
        assert kinds == ["member", "prompt"]
        _publish(db, content="two")
        loaded = Team.load("t", db=db)
        assert loaded.instructions == "two"
        assert [m.id for m in loaded.members] == ["m"]
        assert loaded.members[0].instructions == "one"

    def test_strict_pin_miss_and_lenient_fallback(self, db):
        _publish(db, content="one")
        _publish(db, content="two")
        Team(id="t", members=[_plain_member()], instructions=Prompt(id="support", version=2)).save(db=db)
        _drop_prompt(db, republish="fresh")
        with pytest.raises(ComponentPinError):
            Team.load("t", db=db, strict=True)
        loaded = Team.load("t", db=db, strict=False)
        assert loaded.instructions == "fresh"
        assert _state(loaded, "instructions") == (2, 1, "published", True, "pinned_version_missing")

    def test_loaded_system_message_is_still_a_total_replacement(self, db):
        _publish(db, prompt_id="sm", content="Only this text.")
        Team(id="t", members=[_plain_member()], system_message=Prompt(id="sm")).save(db=db)
        model = StubModel()
        loaded = Team.load("t", db=db)
        loaded.model = model
        loaded.run("hi")
        assert _system_content(model) == "Only this text."

    def test_team_save_rejects_missing_prompt_before_any_write(self, db):
        with pytest.raises(ValueError, match="not an active Prompt"):
            Team(id="t", members=[_plain_member()], instructions=Prompt(id="support")).save(db=db)
        assert db.get_component("t") is None
        assert db.get_component("member") is None
