"""Runs record which Prompt relationship actually shaped the model request.

``agno_prompt_versions`` is a runtime-owned list with one record per Prompt-backed
field that reached the system message, in system_message then instructions order.
It is assigned fresh at dispatch, replaces or removes any caller value, survives
retries and continuation, and is skipped for a caller-supplied RunContext.
"""

import json
from typing import Any, AsyncIterator, Iterator, List, Optional, Tuple

import pytest

from agno.agent import Agent, FallbackConfig
from agno.db.schemas.scheduler import PROMPT_VERSIONS_METADATA_KEY
from agno.db.sqlite import SqliteDb
from agno.exceptions import ModelProviderError
from agno.models.base import Model
from agno.models.message import Message, MessageMetrics
from agno.models.response import ModelResponse
from agno.prompt import Prompt
from agno.run import RunContext
from agno.team import Team
from agno.workflow import Step, Workflow

KEY = PROMPT_VERSIONS_METADATA_KEY


@pytest.fixture
def db(tmp_path):
    return SqliteDb(id="metadata-db", db_file=str(tmp_path / "metadata.db"))


class StubModel(Model):
    """Offline model that records every message list it was asked to answer."""

    def __init__(self, fail_times: int = 0, error: Optional[Exception] = None):
        super().__init__(id="stub", name="stub", provider="test")
        self.instructions = None
        self.calls: List[List[Message]] = []
        self.fail_times = fail_times
        self.error = error or RuntimeError("transient")
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
        if len(self.calls) <= self.fail_times:
            raise self.error

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


class DelegatingModel(StubModel):
    """Leader double: each run delegates to ``member_id`` first, then answers the tool result."""

    def __init__(self, member_id: str):
        super().__init__()
        self._delegation = ModelResponse(
            role="assistant",
            tool_calls=[
                {
                    "id": "delegate-1",
                    "type": "function",
                    "function": {
                        "name": "delegate_task_to_member",
                        "arguments": json.dumps({"member_id": member_id, "task": "Handle this."}),
                    },
                }
            ],
            response_usage=MessageMetrics(),
        )

    def _next(self, kwargs) -> ModelResponse:
        self._record(kwargs)
        return self._response if self.calls[-1][-1].role == "tool" else self._delegation

    def invoke(self, *args, **kwargs) -> ModelResponse:
        return self._next(kwargs)

    async def ainvoke(self, *args, **kwargs) -> ModelResponse:
        return self._next(kwargs)

    def _parse_provider_response(self, response: Any, **kwargs) -> ModelResponse:
        return response


def _system_content(model: StubModel) -> Optional[str]:
    for message in model.calls[-1]:
        if message.role == "system":
            return message.content
    return None


def _record(
    prompt_id="support",
    field="instructions",
    selection="pinned",
    requested=1,
    resolved=1,
    source="published",
    fallback=False,
    reason=None,
):
    return {
        "prompt_id": prompt_id,
        "field": field,
        "selection": selection,
        "requested_version": requested,
        "resolved_version": resolved,
        "source": source,
        "fallback": fallback,
        "fallback_reason": reason,
    }


def _publish(db, prompt_id="support", content="one"):
    return Prompt(id=prompt_id, content=content).save(db=db)


def _saved_agent(db, **fields):
    Agent(id="a", **fields).save(db=db)


def _load_agent(db, model=None, strict=False) -> Agent:
    loaded = Agent.load("a", db=db, strict=strict)
    loaded.model = model or StubModel()
    return loaded


def _member() -> Agent:
    return Agent(id="member", name="Member", instructions="Help the team.")


def _load_team(db, model=None, strict=False) -> Team:
    loaded = Team.load("t", db=db, strict=strict)
    loaded.model = model or StubModel()
    return loaded


class TestAgentAttribution:
    def test_instructions_only(self, db):
        _publish(db)
        _saved_agent(db, instructions=Prompt(id="support"))
        agent = _load_agent(db)
        output = agent.run("hi")
        assert output.metadata[KEY] == [_record()]
        assert "one" in _system_content(agent.model)

    def test_system_message_only(self, db):
        _publish(db, prompt_id="sm", content="Only this text.")
        _saved_agent(db, system_message=Prompt(id="sm"))
        agent = _load_agent(db)
        output = agent.run("hi")
        assert output.metadata[KEY] == [_record(prompt_id="sm", field="system_message")]
        assert _system_content(agent.model) == "Only this text."

    def test_both_fields_record_only_the_system_message(self, db):
        _publish(db, content="instruction text")
        _publish(db, prompt_id="sm", content="Only this text.")
        _saved_agent(db, instructions=Prompt(id="support"), system_message=Prompt(id="sm"))
        agent = _load_agent(db)
        output = agent.run("hi")
        assert output.metadata[KEY] == [_record(prompt_id="sm", field="system_message")]
        assert _system_content(agent.model) == "Only this text."

    def test_build_context_false_records_nothing(self, db):
        _publish(db)
        _saved_agent(db, instructions=Prompt(id="support"), build_context=False)
        agent = _load_agent(db)
        output = agent.run("hi")
        assert not output.metadata or KEY not in output.metadata
        assert _system_content(agent.model) is None

    def test_latest_selection(self, db):
        _publish(db)
        _saved_agent(db, instructions=Prompt(id="support", version="latest"))
        output = _load_agent(db).run("hi")
        assert output.metadata[KEY] == [_record(selection="latest", requested=None, resolved=1)]

    def test_pinned_to_current_fallback(self, db):
        _publish(db, content="one")
        _publish(db, content="two")
        _saved_agent(db, instructions=Prompt(id="support", version=2))
        db.delete_component("support", hard_delete=True, require_no_dependents=False)
        _publish(db, content="fresh")
        agent = _load_agent(db)
        output = agent.run("hi")
        assert output.metadata[KEY] == [
            _record(requested=2, resolved=1, fallback=True, reason="pinned_version_missing")
        ]
        assert "fresh" in _system_content(agent.model)

    def test_pinned_to_inline_fallback(self, db):
        _publish(db, content="one")
        _publish(db, content="two")
        _saved_agent(db, instructions=Prompt(id="support", version=2, fallback=["Answer safely."]))
        db.delete_component("support", require_no_dependents=False)
        agent = _load_agent(db)
        output = agent.run("hi")
        expected = _record(requested=2, resolved=None, source="inline", fallback=True, reason="pinned_version_missing")
        assert output.metadata[KEY] == [expected]
        assert "Answer safely." in _system_content(agent.model)

    def test_latest_to_inline_fallback(self, db):
        _publish(db)
        _saved_agent(db, instructions=Prompt(id="support", version="latest", fallback="Answer safely."))
        db.delete_component("support", require_no_dependents=False)
        output = _load_agent(db).run("hi")
        expected = _record(
            selection="latest",
            requested=None,
            resolved=None,
            source="inline",
            fallback=True,
            reason="no_current_version",
        )
        assert output.metadata[KEY] == [expected]

    def test_a_forged_value_is_replaced(self, db):
        _publish(db)
        _saved_agent(db, instructions=Prompt(id="support"))
        output = _load_agent(db).run("hi", metadata={KEY: "forged", "team": "growth"})
        assert output.metadata[KEY] == [_record()]
        assert output.metadata["team"] == "growth"

    def test_a_forged_value_is_removed_when_no_prompt_is_effective(self):
        output = Agent(model=StubModel(), instructions="plain").run("hi", metadata={KEY: "forged", "team": "growth"})
        assert KEY not in output.metadata
        assert output.metadata["team"] == "growth"

    def test_retries_do_not_duplicate_records(self, db):
        _publish(db)
        _saved_agent(db, instructions=Prompt(id="support"))
        agent = _load_agent(db, model=StubModel(fail_times=2))
        agent.retries = 2
        agent.delay_between_retries = 0
        output = agent.run("hi")
        assert len(agent.model.calls) == 3
        assert output.metadata[KEY] == [_record()]

    def test_a_fallback_model_keeps_the_attribution(self, db):
        _publish(db)
        _saved_agent(db, instructions=Prompt(id="support"))
        agent = _load_agent(db, model=StubModel(fail_times=99, error=ModelProviderError("primary down")))
        agent.fallback_config = FallbackConfig(on_error=[StubModel()])
        output = agent.run("hi")
        assert output.content == "ok"
        assert output.metadata[KEY] == [_record()]

    async def test_async_run(self, db):
        _publish(db)
        _saved_agent(db, instructions=Prompt(id="support"))
        agent = _load_agent(db)
        output = await agent.arun("hi")
        assert output.metadata[KEY] == [_record()]
        assert "one" in _system_content(agent.model)

    def test_streaming_run(self, db):
        _publish(db)
        _saved_agent(db, instructions=Prompt(id="support"))
        agent = _load_agent(db)
        final = list(agent.run("hi", stream=True, yield_run_output=True))[-1]
        assert final.metadata[KEY] == [_record()]

    async def test_async_streaming_run(self, db):
        _publish(db)
        _saved_agent(db, instructions=Prompt(id="support"))
        agent = _load_agent(db)
        events = [event async for event in agent.arun("hi", stream=True, yield_run_output=True)]
        assert events[-1].metadata[KEY] == [_record()]

    def test_continue_run_keeps_the_stored_records(self, db):
        _publish(db, content="one")
        _saved_agent(db, instructions=Prompt(id="support", version="latest"))
        first = _load_agent(db).run("hi", session_id="s1")
        assert first.metadata[KEY] == [_record(selection="latest", requested=None, resolved=1)]
        _publish(db, content="two")
        reloaded = _load_agent(db)
        continued = reloaded.continue_run(run_id=first.run_id, session_id="s1", input="again")
        assert continued.metadata[KEY] == [_record(selection="latest", requested=None, resolved=1)]

    def test_a_caller_supplied_run_context_is_not_stamped(self, db):
        _publish(db)
        _saved_agent(db, instructions=Prompt(id="support"))
        output = _load_agent(db).run("hi", run_context=RunContext(run_id="r1", session_id="s1"))
        assert not output.metadata or KEY not in output.metadata

    def test_a_workflow_step_is_not_stamped(self, db):
        _publish(db)
        _saved_agent(db, instructions=Prompt(id="support"))
        agent = _load_agent(db)
        workflow = Workflow(id="wf", name="wf", steps=[Step(name="answer", agent=agent)])
        output = workflow.run("hi")
        assert not output.metadata or KEY not in output.metadata
        nested = getattr(output, "step_executor_runs", None) or []
        assert nested, "the workflow step must have run the agent"
        for run in nested:
            assert not run.metadata or KEY not in run.metadata
        assert "one" in _system_content(agent.model)

    def test_two_runs_in_one_process_do_not_leak(self, db):
        _publish(db)
        _saved_agent(db, instructions=Prompt(id="support"))
        agent = _load_agent(db)
        first = agent.run("hi")
        second = agent.run("hi again")
        assert first.metadata[KEY] == [_record()]
        assert second.metadata[KEY] == [_record()]
        assert first.metadata[KEY] is not second.metadata[KEY]
        plain = Agent(model=StubModel(), instructions="plain").run("hi")
        assert not plain.metadata or KEY not in plain.metadata

    def test_in_place_edits_between_runs_end_the_attribution(self, db):
        _publish(db, content=["Be concise."])
        _saved_agent(db, instructions=Prompt(id="support"))
        agent = _load_agent(db)
        first = agent.run("hi")
        agent.instructions.append("Added by hand.")
        second = agent.run("hi again")
        assert first.metadata[KEY] == [_record()]
        assert not second.metadata or KEY not in second.metadata
        assert "Added by hand." in _system_content(agent.model)

    def test_a_never_published_inline_prompt_is_not_recorded(self):
        model = StubModel()
        output = Agent(model=model, instructions=Prompt(id="support", content="Be concise.")).run("hi")
        assert not output.metadata or KEY not in output.metadata
        assert "Be concise." in _system_content(model)

    async def test_a_never_published_inline_system_message_is_not_recorded_async(self):
        model = StubModel()
        agent = Agent(model=model, system_message=Prompt(id="sm", content="Only this text."))
        output = await agent.arun("hi")
        assert not output.metadata or KEY not in output.metadata
        assert _system_content(model) == "Only this text."

    def test_a_forged_value_is_removed_for_an_inline_prompt(self):
        agent = Agent(model=StubModel(), instructions=Prompt(id="support", content="Be concise."))
        output = agent.run("hi", metadata={KEY: "forged", "team": "growth"})
        assert KEY not in output.metadata
        assert output.metadata["team"] == "growth"


class TestTeamAttribution:
    def test_instructions_only(self, db):
        _publish(db)
        Team(id="t", members=[_member()], instructions=Prompt(id="support")).save(db=db)
        team = _load_team(db)
        output = team.run("hi")
        assert output.metadata[KEY] == [_record()]
        assert "one" in _system_content(team.model)

    def test_system_message_is_a_total_replacement(self, db):
        _publish(db, prompt_id="sm", content="Only this text.")
        Team(id="t", members=[_member()], system_message=Prompt(id="sm")).save(db=db)
        team = _load_team(db)
        output = team.run("hi")
        assert output.metadata[KEY] == [_record(prompt_id="sm", field="system_message")]
        assert _system_content(team.model) == "Only this text."

    def test_both_fields_record_only_the_system_message(self, db):
        _publish(db, content="instruction text")
        _publish(db, prompt_id="sm", content="Only this text.")
        Team(id="t", members=[_member()], instructions=Prompt(id="support"), system_message=Prompt(id="sm")).save(db=db)
        team = _load_team(db)
        output = team.run("hi")
        assert output.metadata[KEY] == [_record(prompt_id="sm", field="system_message")]
        assert _system_content(team.model) == "Only this text."

    def test_latest_selection_and_pinned_to_current_fallback(self, db):
        _publish(db, content="one")
        _publish(db, content="two")
        Team(id="t", members=[_member()], instructions=Prompt(id="support", version=2)).save(db=db)
        db.delete_component("support", hard_delete=True, require_no_dependents=False)
        _publish(db, content="fresh")
        output = _load_team(db).run("hi")
        assert output.metadata[KEY] == [
            _record(requested=2, resolved=1, fallback=True, reason="pinned_version_missing")
        ]

    def test_a_forged_value_is_replaced(self, db):
        _publish(db)
        Team(id="t", members=[_member()], instructions=Prompt(id="support")).save(db=db)
        output = _load_team(db).run("hi", metadata={KEY: "forged", "team": "growth"})
        assert output.metadata[KEY] == [_record()]
        assert output.metadata["team"] == "growth"

    async def test_async_run(self, db):
        _publish(db)
        Team(id="t", members=[_member()], instructions=Prompt(id="support")).save(db=db)
        team = _load_team(db)
        output = await team.arun("hi")
        assert output.metadata[KEY] == [_record()]
        assert "one" in _system_content(team.model)

    def test_streaming_run(self, db):
        _publish(db)
        Team(id="t", members=[_member()], instructions=Prompt(id="support")).save(db=db)
        team = _load_team(db)
        final = list(team.run("hi", stream=True, yield_run_output=True))[-1]
        assert final.metadata[KEY] == [_record()]

    def test_a_caller_supplied_run_context_is_not_stamped(self, db):
        _publish(db)
        Team(id="t", members=[_member()], instructions=Prompt(id="support")).save(db=db)
        output = _load_team(db).run("hi", run_context=RunContext(run_id="r1", session_id="s1"))
        assert not output.metadata or KEY not in output.metadata

    def test_two_runs_in_one_process_do_not_leak(self, db):
        _publish(db)
        Team(id="t", members=[_member()], instructions=Prompt(id="support")).save(db=db)
        team = _load_team(db)
        first = team.run("hi")
        second = team.run("hi again")
        assert first.metadata[KEY] == [_record()]
        assert second.metadata[KEY] == [_record()]
        assert first.metadata[KEY] is not second.metadata[KEY]

    def test_a_never_published_inline_prompt_is_not_recorded(self):
        model = StubModel()
        team = Team(model=model, members=[_member()], instructions=Prompt(id="support", content="Be concise."))
        output = team.run("hi")
        assert not output.metadata or KEY not in output.metadata
        assert "Be concise." in _system_content(model)

    async def test_a_never_published_inline_system_message_is_not_recorded_async(self):
        model = StubModel()
        team = Team(model=model, members=[_member()], system_message=Prompt(id="sm", content="Only this text."))
        output = await team.arun("hi")
        assert not output.metadata or KEY not in output.metadata
        assert _system_content(model) == "Only this text."


def _saved_team_with_member(db, *, member_instructions):
    _publish(db, content="Lead well.")
    member = Agent(id="member", name="Member", instructions=member_instructions)
    Team(id="t", members=[member], instructions=Prompt(id="support")).save(db=db)


def _delegating_team(db) -> Tuple[Team, StubModel]:
    team = Team.load("t", db=db)
    team.model = DelegatingModel("member")
    member_model = StubModel()
    team.members[0].model = member_model
    return team, member_model


class TestMemberDispatchIsolation:
    """Delegation forwards the leader's run metadata; every member run re-derives its own records."""

    def test_the_member_records_only_its_own_prompt(self, db):
        _publish(db, prompt_id="member-prompt", content="Member text.")
        _saved_team_with_member(db, member_instructions=Prompt(id="member-prompt"))
        team, member_model = _delegating_team(db)
        output = team.run("hi", metadata={"team": "growth"})
        assert output.metadata[KEY] == [_record()]
        [member_run] = output.member_responses
        assert member_run.metadata[KEY] == [_record(prompt_id="member-prompt")]
        assert member_run.metadata["team"] == "growth"
        assert "Member text." in _system_content(member_model)

    def test_a_member_without_a_prompt_drops_the_inherited_key(self, db):
        _saved_team_with_member(db, member_instructions="Help the team.")
        team, member_model = _delegating_team(db)
        caller = {KEY: "forged", "team": "growth"}
        output = team.run("hi", metadata=caller)
        assert output.metadata[KEY] == [_record()]
        [member_run] = output.member_responses
        assert KEY not in member_run.metadata
        assert member_run.metadata["team"] == "growth"
        assert caller == {KEY: "forged", "team": "growth"}
        assert member_model.calls

    def test_repeated_delegations_do_not_accumulate(self, db):
        _publish(db, prompt_id="member-prompt", content="Member text.")
        _saved_team_with_member(db, member_instructions=Prompt(id="member-prompt"))
        team, _ = _delegating_team(db)
        first = team.run("hi")
        second = team.run("again")
        records = [output.member_responses[0].metadata[KEY] for output in (first, second)]
        assert records == [[_record(prompt_id="member-prompt")]] * 2
        assert records[0] is not records[1]
