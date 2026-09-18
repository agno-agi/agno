"""Follow-up configuration through the public run entrypoints.

Covers model precedence (config model, then followup_model, then the component model),
string model references on both slots, and answer preservation when the optional
follow-up stage fails.
"""

from __future__ import annotations

import json
from typing import Any, AsyncIterator, Iterator, Optional

import pytest

from agno.agent import Agent, FollowupConfig
from agno.db.in_memory import InMemoryDb
from agno.exceptions import RunCancelledException
from agno.models.base import Model
from agno.models.message import MessageMetrics
from agno.models.response import ModelResponse
from agno.run.agent import RunOutput
from agno.run.base import RunStatus
from agno.run.team import TeamRunOutput
from agno.team import Team

FOLLOWUP_PROMPT_START = "Based on the user's message and the assistant's response below"
INSTRUCTIONS = "Suggest only documentation questions."
MODEL_STRING = "openai:gpt-4o-mini"


def _is_followup_call(messages) -> bool:
    return (
        bool(messages) and messages[0].role == "system" and str(messages[0].content).startswith(FOLLOWUP_PROMPT_START)
    )


class RecordingModel(Model):
    """Offline model: "ANSWER" on the main call, a fixed suggestion list on the follow-up call."""

    def __init__(
        self,
        tag: str,
        suggestions=("S1", "S2", "S3"),
        fail_followups: bool = False,
        raw_followup_content: Optional[str] = None,
    ):
        super().__init__(id=f"rec-{tag}", name=f"rec-{tag}", provider="test")
        self.suggestions = list(suggestions)
        self.fail_followups = fail_followups
        self.followup_exception: Optional[BaseException] = None
        self.raw_followup_content = raw_followup_content
        self.main_calls = 0
        self.followup_calls = 0
        self.followup_system_prompts: list = []
        self.followup_user_messages: list = []

    def _answer(self, messages) -> ModelResponse:
        if _is_followup_call(messages):
            self.followup_calls += 1
            self.followup_system_prompts.append(str(messages[0].content))
            self.followup_user_messages.append(str(messages[1].content) if len(messages) > 1 else "")
            if self.followup_exception is not None:
                raise self.followup_exception
            if self.fail_followups:
                raise RuntimeError("follow-up provider failure")
            content = (
                self.raw_followup_content
                if self.raw_followup_content is not None
                else json.dumps({"suggestions": self.suggestions})
            )
        else:
            self.main_calls += 1
            content = "ANSWER"
        return ModelResponse(content=content, role="assistant", response_usage=MessageMetrics())

    def invoke(self, *args, **kwargs) -> ModelResponse:
        return self._answer(kwargs.get("messages") or [])

    async def ainvoke(self, *args, **kwargs) -> ModelResponse:
        return self._answer(kwargs.get("messages") or [])

    def invoke_stream(self, *args, **kwargs) -> Iterator[ModelResponse]:
        yield self._answer(kwargs.get("messages") or [])

    async def ainvoke_stream(self, *args, **kwargs) -> AsyncIterator[ModelResponse]:
        yield self._answer(kwargs.get("messages") or [])

    def _parse_provider_response(self, response: Any, **kwargs) -> ModelResponse:
        return response

    def _parse_provider_response_delta(self, response: Any) -> ModelResponse:
        return response


def _component_factory(kind: str):
    def build(**kwargs):
        main = RecordingModel("main")
        if kind == "agent":
            return Agent(model=main, followups=True, telemetry=False, **kwargs)
        return Team(members=[], model=main, followups=True, telemetry=False, **kwargs)

    return build


# --- precedence through the public entrypoints ---------------------------------------------------

# case -> (model that must generate the follow-ups, whether INSTRUCTIONS must reach its system prompt)
PRECEDENCE = {
    "config-model": ("config", True),
    "config-instructions-only": ("legacy", True),
    "config-instructions-no-legacy": ("main", True),
    "config-empty": ("legacy", False),
    "legacy-only": ("legacy", False),
    "component-only": ("main", False),
}


def _followup_kwargs(case: str, models: dict) -> dict:
    if case == "config-model":
        return {
            "followup_config": FollowupConfig(model=models["config"], instructions=INSTRUCTIONS),
            "followup_model": models["legacy"],
        }
    if case == "config-instructions-only":
        return {"followup_config": FollowupConfig(instructions=INSTRUCTIONS), "followup_model": models["legacy"]}
    if case == "config-instructions-no-legacy":
        return {"followup_config": FollowupConfig(instructions=INSTRUCTIONS)}
    if case == "config-empty":
        return {"followup_config": FollowupConfig(), "followup_model": models["legacy"]}
    if case == "legacy-only":
        return {"followup_model": models["legacy"]}
    return {}


def _build(kind: str, case: str):
    models = {name: RecordingModel(name) for name in ("main", "legacy", "config")}
    kwargs = dict(followups=True, num_followups=2, telemetry=False, **_followup_kwargs(case, models))
    if kind == "agent":
        component = Agent(model=models["main"], **kwargs)
    else:
        member = Agent(name="member", model=RecordingModel("member"), telemetry=False)
        component = Team(members=[member], model=models["main"], **kwargs)
    return component, models


def _assert_routing(output, models: dict, case: str) -> None:
    winner, expects_instructions = PRECEDENCE[case]
    assert output.content == "ANSWER"
    assert output.followups == ["S1", "S2"]
    assert {name: model.followup_calls for name, model in models.items()} == {
        name: int(name == winner) for name in models
    }
    assert {name: model.main_calls for name, model in models.items()} == {name: int(name == "main") for name in models}
    assert (INSTRUCTIONS in models[winner].followup_system_prompts[0]) is expects_instructions


@pytest.mark.parametrize("case", list(PRECEDENCE))
@pytest.mark.parametrize("kind", ["agent", "team"])
def test_followup_model_precedence_sync(kind, case):
    component, models = _build(kind, case)
    _assert_routing(component.run("Hi"), models, case)


@pytest.mark.parametrize("case", list(PRECEDENCE))
@pytest.mark.parametrize("kind", ["agent", "team"])
async def test_followup_model_precedence_async_stream(kind, case):
    component, models = _build(kind, case)
    outputs = [
        event
        async for event in component.arun("Hi", stream=True, stream_events=True, yield_run_output=True)
        if isinstance(event, (RunOutput, TeamRunOutput))
    ]
    _assert_routing(outputs[-1], models, case)


# --- string model references -----------------------------------------------------------------------


@pytest.mark.parametrize("kind", ["agent", "team"])
def test_followup_model_strings_resolve_at_construction(kind):
    build = _component_factory(kind)

    legacy = build(followup_model=MODEL_STRING)
    assert isinstance(legacy.followup_model, Model)

    shared = FollowupConfig(model=MODEL_STRING, instructions=INSTRUCTIONS)
    configured = build(followup_config=shared)
    assert isinstance(configured.followup_config.model, Model)
    assert configured.followup_config.instructions == INSTRUCTIONS
    # A config object may be shared across components: it is never mutated, the
    # component owns a resolved copy instead.
    assert shared.model == MODEL_STRING
    assert configured.followup_config is not shared

    ready = FollowupConfig(model=RecordingModel("config"))
    assert build(followup_config=ready).followup_config is ready


@pytest.mark.parametrize("slot", ["followup_model", "followup_config"])
@pytest.mark.parametrize("kind", ["agent", "team"])
def test_invalid_followup_model_string_fails_at_construction(kind, slot):
    build = _component_factory(kind)
    value = "not-a-model" if slot == "followup_model" else FollowupConfig(model="not-a-model")
    with pytest.raises(ValueError):
        build(**{slot: value})


# --- optional-stage failure keeps the answer and never re-runs the main call -------------------------


@pytest.mark.parametrize("stream", [False, True])
def test_followup_failure_keeps_answer_without_retrying_main_call(stream):
    main = RecordingModel("main")
    failing = RecordingModel("followup", fail_followups=True)
    agent = Agent(
        model=main, followups=True, followup_model=failing, retries=1, delay_between_retries=0, telemetry=False
    )
    if stream:
        events = list(agent.run("Hi", stream=True, stream_events=True, yield_run_output=True))
        output = [event for event in events if isinstance(event, RunOutput)][-1]
        assert sum(1 for event in events if getattr(event, "event", "") == "RunContent") == 1
    else:
        output = agent.run("Hi")
    assert output.status == RunStatus.completed
    assert output.content == "ANSWER"
    assert output.followups is None
    assert main.main_calls == 1
    assert failing.followup_calls == 1


# --- component persistence: save, recreate, run (registry-backed deterministic models) -------------


@pytest.mark.parametrize("kind", ["agent", "team"])
def test_reconstructed_component_keeps_followup_routing(kind):
    from agno.registry import Registry

    models = {name: RecordingModel(name) for name in ("main", "legacy", "config")}
    kwargs = dict(
        followups=True,
        num_followups=2,
        followup_model=models["legacy"],
        followup_config=FollowupConfig(model=models["config"], instructions=INSTRUCTIONS),
        telemetry=False,
    )
    registry = Registry(models=list(models.values()))
    if kind == "agent":
        original = Agent(id="fu-agent", model=models["main"], **kwargs)
        reconstructed = Agent.from_dict(original.to_dict(), registry=registry)
    else:
        original = Team(id="fu-team", members=[], model=models["main"], **kwargs)
        reconstructed = Team.from_dict(original.to_dict(), registry=registry)
    reconstructed.telemetry = False
    assert reconstructed.followups is True
    assert reconstructed.num_followups == 2
    assert reconstructed.model is models["main"]
    assert reconstructed.followup_model is models["legacy"]
    assert reconstructed.followup_config.model is models["config"]
    assert reconstructed.followup_config.instructions == INSTRUCTIONS

    output = reconstructed.run("Hi")
    assert output.content == "ANSWER"
    assert output.followups == ["S1", "S2"]
    assert {name: model.followup_calls for name, model in models.items()} == {"config": 1, "legacy": 0, "main": 0}
    assert INSTRUCTIONS in models["config"].followup_system_prompts[0]


# --- run-output persistence: the suggestions of a run survive a real database round trip ------------


@pytest.mark.parametrize(
    "label,model_kwargs,expected",
    [
        ("empty", {"suggestions": []}, []),
        ("list", {"suggestions": ["S1", "S2"]}, ["S1", "S2"]),
        ("malformed", {"raw_followup_content": "not json"}, None),
    ],
    ids=["empty", "list", "malformed"],
)
def test_run_output_followups_persist_in_sqlite(tmp_path, label, model_kwargs, expected):
    from agno.db.base import SessionType
    from agno.db.sqlite import SqliteDb

    db = SqliteDb(db_file=str(tmp_path / "followups.db"))
    agent = Agent(
        model=RecordingModel("main"),
        db=db,
        followups=True,
        followup_model=RecordingModel("followup", **model_kwargs),
        telemetry=False,
    )
    output = agent.run("Hi", session_id=f"session-{label}")
    assert output.followups == expected

    session = db.get_session(session_id=f"session-{label}", session_type=SessionType.AGENT)
    stored = session.runs[-1]
    assert stored.run_id == output.run_id
    assert stored.followups == expected


# --- default contract without a FollowupConfig (applies to every followups=True component) ----------

BOUNDARY_SENTENCE = "Never suggest repeating or fulfilling a request the assistant declined"


def _component_without_config(kind: str, followup_model: RecordingModel):
    main = RecordingModel("main")
    if kind == "agent":
        return Agent(model=main, followups=True, num_followups=2, followup_model=followup_model, telemetry=False)
    return Team(members=[], model=main, followups=True, num_followups=2, followup_model=followup_model, telemetry=False)


@pytest.mark.parametrize(
    "returned,expected",
    [(0, []), (1, ["S0"]), (2, ["S0", "S1"]), (3, ["S0", "S1"]), (7, ["S0", "S1"])],
    ids=["zero", "one", "max", "max-plus-one", "oversized"],
)
@pytest.mark.parametrize("kind", ["agent", "team"])
def test_default_contract_without_config(kind, returned, expected):
    followup_model = RecordingModel("followup", suggestions=[f"S{i}" for i in range(returned)])
    output = _component_without_config(kind, followup_model).run("Hi")
    assert output.followups == expected
    assert BOUNDARY_SENTENCE in followup_model.followup_system_prompts[0]
    assert INSTRUCTIONS not in followup_model.followup_system_prompts[0]
    assert "Generate at most 2 follow-up suggestions." in followup_model.followup_user_messages[0]


@pytest.mark.parametrize("kind", ["agent", "team"])
def test_failed_generation_without_config_is_none_not_empty(kind):
    followup_model = RecordingModel("followup", raw_followup_content="not json")
    output = _component_without_config(kind, followup_model).run("Hi")
    assert output.status == RunStatus.completed
    assert output.followups is None


# --- continuation paths: config model, instructions, empty, clipped, stale, failure, cancellation -----


def _continuation_agent():
    models = {name: RecordingModel(name) for name in ("main", "legacy", "config")}
    agent = Agent(
        model=models["main"],
        db=InMemoryDb(),
        followups=True,
        num_followups=2,
        followup_model=models["legacy"],
        followup_config=FollowupConfig(model=models["config"], instructions=INSTRUCTIONS),
        telemetry=False,
    )
    return agent, models


async def _continue(agent, run_id: str, *, asynchronous: bool, stream: bool):
    kwargs = dict(run_id=run_id, session_id="s1", requirements=[])
    if not stream:
        return (await agent.acontinue_run(**kwargs)) if asynchronous else agent.continue_run(**kwargs), []
    kwargs.update(stream=True, stream_events=True, yield_run_output=True)
    if asynchronous:
        events = [event async for event in agent.acontinue_run(**kwargs)]
    else:
        events = list(agent.continue_run(**kwargs))
    outputs = [event for event in events if isinstance(event, RunOutput)]
    return outputs[-1], [event for event in events if not isinstance(event, RunOutput)]


@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize("asynchronous", [False, True])
async def test_continuation_routes_followups_to_config_model(asynchronous, stream):
    agent, models = _continuation_agent()
    first = await agent.arun("Hi", session_id="s1") if asynchronous else agent.run("Hi", session_id="s1")
    assert first.followups == ["S1", "S2"]
    continued, events = await _continue(agent, first.run_id, asynchronous=asynchronous, stream=stream)
    assert continued.content == "ANSWER"
    assert continued.followups == ["S1", "S2"]
    assert {name: model.followup_calls for name, model in models.items()} == {"config": 2, "legacy": 0, "main": 0}
    assert INSTRUCTIONS in models["config"].followup_system_prompts[-1]
    if stream:
        completed = [event for event in events if str(event.event) == "FollowupsCompleted"]
        assert len(completed) == 1
        assert completed[0].followups == ["S1", "S2"]
        assert completed[0].run_id == continued.run_id


@pytest.mark.parametrize(
    "later_suggestions,expected",
    [([], []), (["A", "B", "C", "D"], ["A", "B"])],
    ids=["empty-replaces-earlier", "clipped"],
)
def test_continuation_result_is_fresh_not_stale(later_suggestions, expected):
    agent, models = _continuation_agent()
    first = agent.run("Hi", session_id="s1")
    assert first.followups == ["S1", "S2"]
    models["config"].suggestions = later_suggestions
    continued = agent.continue_run(run_id=first.run_id, session_id="s1", requirements=[])
    assert continued.followups == expected


def test_continuation_failure_keeps_answer_without_repeating_main_call():
    agent, models = _continuation_agent()
    first = agent.run("Hi", session_id="s1")
    models["config"].fail_followups = True
    continued = agent.continue_run(run_id=first.run_id, session_id="s1", requirements=[])
    assert continued.status == RunStatus.completed
    assert continued.content == "ANSWER"
    assert continued.followups is None
    assert models["main"].main_calls == 2  # one per run, no retry of the answer


def test_continuation_cancellation_propagates():
    agent, models = _continuation_agent()
    first = agent.run("Hi", session_id="s1")
    models["config"].followup_exception = RunCancelledException("cancelled during follow-ups")
    continued = agent.continue_run(run_id=first.run_id, session_id="s1", requirements=[])
    assert continued.status == RunStatus.cancelled
    assert continued.content == "ANSWER"
    assert continued.followups is None


# --- Team tasks mode across the four public modes -------------------------------------------------


def _tasks_team(suggestions):
    models = {name: RecordingModel(name, suggestions=suggestions) for name in ("main", "legacy", "config")}
    member = Agent(name="Helper", id="helper", model=RecordingModel("member"), telemetry=False)
    team = Team(
        model=models["main"],
        members=[member],
        mode="tasks",
        followups=True,
        num_followups=2,
        followup_model=models["legacy"],
        followup_config=FollowupConfig(model=models["config"], instructions=INSTRUCTIONS),
        telemetry=False,
    )
    return team, models


@pytest.mark.parametrize(
    "suggestions,expected", [([], []), (["S1", "S2", "S3"], ["S1", "S2"])], ids=["empty", "clipped"]
)
@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize("asynchronous", [False, True])
async def test_team_tasks_mode_public_paths(asynchronous, stream, suggestions, expected):
    team, models = _tasks_team(suggestions)
    prompt = "Hi! Say hello."
    events: list = []
    if not stream:
        output = await team.arun(prompt) if asynchronous else team.run(prompt)
    else:
        kwargs = dict(stream=True, stream_events=True, yield_run_output=True)
        if asynchronous:
            events = [event async for event in team.arun(prompt, **kwargs)]
        else:
            events = list(team.run(prompt, **kwargs))
        output = [event for event in events if isinstance(event, TeamRunOutput)][-1]
        events = [event for event in events if not isinstance(event, TeamRunOutput)]
    # Tasks mode may take a reminder turn; the leader loop concatenates turn content.
    assert output.content.startswith("ANSWER")
    assert output.followups == expected
    assert {name: model.followup_calls for name, model in models.items()} == {"config": 1, "legacy": 0, "main": 0}
    assert INSTRUCTIONS in models["config"].followup_system_prompts[0]
    assert output.content in models["config"].followup_user_messages[0]  # the final team answer reached the call
    if stream:
        completed = [event for event in events if str(event.event) == "TeamFollowupsCompleted"]
        assert len(completed) == 1
        assert completed[0].followups == expected
        assert completed[0].run_id == output.run_id
