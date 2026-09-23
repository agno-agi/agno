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
MODEL_STRING = "openai:gpt-5.5"


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
        kwargs.setdefault("followups", True)
        if kind == "agent":
            return Agent(model=main, telemetry=False, **kwargs)
        return Team(members=[], model=main, telemetry=False, **kwargs)

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
            "followups": FollowupConfig(model=models["config"], instructions=INSTRUCTIONS),
            "followup_model": models["legacy"],
        }
    if case == "config-instructions-only":
        return {"followups": FollowupConfig(instructions=INSTRUCTIONS), "followup_model": models["legacy"]}
    if case == "config-instructions-no-legacy":
        return {"followups": FollowupConfig(instructions=INSTRUCTIONS)}
    if case == "config-empty":
        return {"followups": FollowupConfig(), "followup_model": models["legacy"]}
    if case == "legacy-only":
        return {"followup_model": models["legacy"]}
    return {}


def _build(kind: str, case: str):
    models = {name: RecordingModel(name) for name in ("main", "legacy", "config")}
    kwargs = {"followups": True, "num_followups": 2, "telemetry": False}
    kwargs.update(_followup_kwargs(case, models))
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
    configured = build(followups=shared)
    assert isinstance(configured.followups.model, Model)
    assert configured.followups.instructions == INSTRUCTIONS
    # A config object may be shared across components: it is never mutated, the
    # component owns a resolved copy instead.
    assert shared.model == MODEL_STRING
    assert configured.followups is not shared

    ready = FollowupConfig(model=RecordingModel("config"))
    assert build(followups=ready).followups is ready


@pytest.mark.parametrize("slot", ["followup_model", "followups"])
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
        followups=FollowupConfig(model=models["config"], instructions=INSTRUCTIONS),
        num_followups=2,
        followup_model=models["legacy"],
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
    assert isinstance(reconstructed.followups, FollowupConfig)
    assert reconstructed.num_followups == 2
    assert reconstructed.model is models["main"]
    assert reconstructed.followup_model is models["legacy"]
    assert reconstructed.followups.model is models["config"]
    assert reconstructed.followups.instructions == INSTRUCTIONS

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
        followups=FollowupConfig(model=models["config"], instructions=INSTRUCTIONS),
        num_followups=2,
        followup_model=models["legacy"],
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
        followups=FollowupConfig(model=models["config"], instructions=INSTRUCTIONS),
        num_followups=2,
        followup_model=models["legacy"],
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


# --- followups= accepts a FollowupConfig: one argument enables and configures ------------------------


class MainRecordingModel(RecordingModel):
    """RecordingModel that also keeps the main-call messages, to show follow-up instructions stay out of them."""

    def __init__(self, tag: str, **kwargs):
        super().__init__(tag, **kwargs)
        self.main_messages: list = []

    def _answer(self, messages) -> ModelResponse:
        if not _is_followup_call(messages):
            self.main_messages.extend(str(message.content) for message in messages)
        return super()._answer(messages)


def _construct(kind: str, **kwargs):
    if kind == "agent":
        return Agent(model=RecordingModel("main"), telemetry=False, **kwargs)
    return Team(members=[], model=RecordingModel("main"), telemetry=False, **kwargs)


async def _run_public_path(component, *, asynchronous: bool, stream: bool):
    if not stream:
        return (await component.arun("Hi") if asynchronous else component.run("Hi")), []
    kwargs = dict(stream=True, stream_events=True, yield_run_output=True)
    if asynchronous:
        events = [event async for event in component.arun("Hi", **kwargs)]
    else:
        events = list(component.run("Hi", **kwargs))
    outputs = [event for event in events if isinstance(event, (RunOutput, TeamRunOutput))]
    return outputs[-1], [event for event in events if not isinstance(event, (RunOutput, TeamRunOutput))]


# case -> (constructor arguments, enabled after construction, effective count)
# Arguments are built lazily so an unsupported form fails its own case, not the module import.
NORMALIZATION = {
    "omitted": (lambda: {}, False, 3),
    "false": (lambda: {"followups": False}, False, 3),
    "true": (lambda: {"followups": True}, True, 3),
    "empty-config": (lambda: {"followups": FollowupConfig()}, True, 3),
    "config-count": (lambda: {"followups": FollowupConfig(num_followups=5)}, True, 5),
    "legacy-count": (lambda: {"followups": True, "num_followups": 5}, True, 5),
    "config-count-beats-legacy-count": (
        lambda: {"followups": FollowupConfig(num_followups=5), "num_followups": 2},
        True,
        5,
    ),
    "unset-config-count-falls-back": (lambda: {"followups": FollowupConfig(), "num_followups": 5}, True, 5),
    "explicit-three-is-not-unset": (
        lambda: {"followups": FollowupConfig(num_followups=3), "num_followups": 5},
        True,
        3,
    ),
    "superseded-legacy-count-is-not-validated": (
        lambda: {"followups": FollowupConfig(num_followups=2), "num_followups": 0},
        True,
        2,
    ),
}


@pytest.mark.parametrize("case", list(NORMALIZATION))
@pytest.mark.parametrize("kind", ["agent", "team"])
def test_followups_argument_normalization(kind, case):
    build_kwargs, enabled, count = NORMALIZATION[case]
    kwargs = build_kwargs()
    component = _construct(kind, **kwargs)
    # followups keeps what was passed: the bool, or that very config object (nothing to resolve here).
    assert component.followups is kwargs.get("followups", False)
    assert bool(component.followups) is enabled
    assert component.num_followups == count


@pytest.mark.parametrize("kind", ["agent", "team"])
def test_followup_config_keyword_is_rejected(kind):
    # The separate argument is gone: a keyword-only constructor refuses it instead of ignoring it.
    with pytest.raises(TypeError, match="followup_config"):
        _construct(kind, followups=True, followup_config=FollowupConfig(instructions=INSTRUCTIONS))


@pytest.mark.parametrize("count", [0, -1])
@pytest.mark.parametrize("source", ["config", "legacy"])
@pytest.mark.parametrize("kind", ["agent", "team"])
def test_effective_count_below_one_is_rejected_at_construction(kind, source, count):
    kwargs = (
        {"followups": FollowupConfig(num_followups=count)}
        if source == "config"
        else {"followups": True, "num_followups": count}
    )
    with pytest.raises(ValueError, match="num_followups must be at least 1"):
        _construct(kind, **kwargs)


@pytest.mark.parametrize("config_has_model", [True, False])
@pytest.mark.parametrize("kind", ["agent", "team"])
def test_model_precedence_with_the_config_passed_as_followups(kind, config_has_model):
    models = {name: RecordingModel(name) for name in ("config", "legacy")}
    config = FollowupConfig(model=models["config"] if config_has_model else None, instructions=INSTRUCTIONS)
    component = _construct(kind, followups=config, followup_model=models["legacy"])
    winner = "config" if config_has_model else "legacy"

    output = component.run("Hi")

    assert output.followups == ["S1", "S2", "S3"]
    assert {name: model.followup_calls for name, model in models.items()} == {
        name: int(name == winner) for name in models
    }
    assert component.model.followup_calls == 0
    assert INSTRUCTIONS in models[winner].followup_system_prompts[0]


@pytest.mark.parametrize("form", ["config", "legacy-model"])
@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize("asynchronous", [False, True])
@pytest.mark.parametrize("kind", ["agent", "team"])
async def test_config_reaches_every_public_path(kind, asynchronous, stream, form):
    main = MainRecordingModel("main")
    configured = RecordingModel("config", suggestions=["S1", "S2", "S3"])
    if form == "config":
        kwargs = dict(followups=FollowupConfig(model=configured, instructions=INSTRUCTIONS, num_followups=2))
    else:
        kwargs = dict(followups=True, num_followups=2, followup_model=configured)
    if kind == "agent":
        component = Agent(model=main, telemetry=False, **kwargs)
    else:
        component = Team(members=[], model=main, telemetry=False, **kwargs)

    output, events = await _run_public_path(component, asynchronous=asynchronous, stream=stream)

    assert output.content == "ANSWER"
    assert output.followups == ["S1", "S2"]  # three returned, clipped to the effective count
    assert (main.main_calls, main.followup_calls) == (1, 0)
    assert (configured.main_calls, configured.followup_calls) == (0, 1)
    assert (INSTRUCTIONS in configured.followup_system_prompts[0]) is (form == "config")
    assert "Generate at most 2 follow-up suggestions." in configured.followup_user_messages[0]
    assert all(INSTRUCTIONS not in text for text in main.main_messages)
    if stream:
        name = "FollowupsCompleted" if kind == "agent" else "TeamFollowupsCompleted"
        completed = [event for event in events if str(event.event) == name]
        assert len(completed) == 1
        assert completed[0].followups == ["S1", "S2"]


@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize("asynchronous", [False, True])
@pytest.mark.parametrize("kind", ["agent", "team"])
async def test_disabled_followups_generate_nothing(kind, asynchronous, stream):
    configured = RecordingModel("config")
    component = _construct(kind, followups=False, followup_model=configured)
    output, events = await _run_public_path(component, asynchronous=asynchronous, stream=stream)
    assert output.content == "ANSWER"
    assert output.followups is None
    assert configured.followup_calls == 0
    assert component.model.followup_calls == 0
    assert not [event for event in events if "Followups" in str(event.event)]


@pytest.mark.parametrize("enabled_by", ["true", "empty-config"])
@pytest.mark.parametrize("kind", ["agent", "team"])
def test_boolean_and_empty_config_share_the_defaults(kind, enabled_by):
    component = _construct(kind, followups=True if enabled_by == "true" else FollowupConfig())
    output = component.run("Hi")
    assert output.followups == ["S1", "S2", "S3"]
    assert component.model.followup_calls == 1  # no configured model: the component model generates them
    assert "Generate at most 3 follow-up suggestions." in component.model.followup_user_messages[0]
    assert BOUNDARY_SENTENCE in component.model.followup_system_prompts[0]


@pytest.mark.parametrize("kind", ["agent", "team"])
def test_config_through_followups_resolves_model_strings_on_a_copy(kind):
    shared = FollowupConfig(model=MODEL_STRING, instructions=INSTRUCTIONS, num_followups=4)
    first = _construct(kind, followups=shared)
    second = _construct(kind, followups=shared)
    for component in (first, second):
        assert isinstance(component.followups, FollowupConfig)
        assert isinstance(component.followups.model, Model)
        assert component.followups.instructions == INSTRUCTIONS
        assert component.followups.num_followups == 4  # the count survives the resolving copy
        assert component.num_followups == 4
    # One config reused by two components is never mutated, and the resolved copies are separate.
    assert (shared.model, shared.instructions, shared.num_followups) == (MODEL_STRING, INSTRUCTIONS, 4)
    assert first.followups is not second.followups


@pytest.mark.parametrize("kind", ["agent", "team"])
def test_invalid_model_string_through_followups_fails_at_construction(kind):
    with pytest.raises(ValueError):
        _construct(kind, followups=FollowupConfig(model="not-a-model"))


@pytest.mark.parametrize("kind", ["agent", "team"])
def test_config_through_followups_survives_repeated_deep_copy(kind):
    configured = RecordingModel("config")
    config = FollowupConfig(model=configured, instructions=INSTRUCTIONS, num_followups=5)
    component = _construct(kind, followups=config, num_followups=2)
    first_copy = component.deep_copy()
    second_copy = first_copy.deep_copy()
    for candidate in (component, first_copy, second_copy):
        assert isinstance(candidate.followups, FollowupConfig)
        assert candidate.num_followups == 5
        assert candidate.followups.num_followups == 5
        assert candidate.followups.instructions == INSTRUCTIONS
        assert candidate.followups.model is configured
    # Updating the legacy count cannot override a count the config sets explicitly.
    assert component.deep_copy(update={"num_followups": 4}).num_followups == 5
    assert config.num_followups == 5
    assert config.model is configured
    # A copy still generates through the configured model; a copy disabled by update does not.
    assert second_copy.run("Hi").followups == ["S1", "S2", "S3"]
    assert configured.followup_calls == 1
    disabled = component.deep_copy(update={"followups": False})
    assert disabled.followups is False
    assert disabled.run("Hi").followups is None
    assert configured.followup_calls == 1


@pytest.mark.parametrize("kind", ["agent", "team"])
def test_legacy_count_update_on_deep_copy_still_applies(kind):
    component = _construct(kind, followups=True, num_followups=2)
    assert component.deep_copy(update={"num_followups": 4}).num_followups == 4


@pytest.mark.parametrize("kind", ["agent", "team"])
def test_config_through_followups_survives_save_and_reconstruction(kind):
    from agno.registry import Registry

    models = {name: RecordingModel(name) for name in ("main", "config")}
    config = FollowupConfig(model=models["config"], instructions=INSTRUCTIONS, num_followups=3)
    kwargs = dict(followups=config, num_followups=5, telemetry=False)
    registry = Registry(models=list(models.values()))
    if kind == "agent":
        stored = Agent(id="fu-agent", model=models["main"], **kwargs).to_dict()
        reconstructed = Agent.from_dict(json.loads(json.dumps(stored)), registry=registry)
    else:
        stored = Team(id="fu-team", members=[], model=models["main"], **kwargs).to_dict()
        reconstructed = Team.from_dict(json.loads(json.dumps(stored)), registry=registry)
    reconstructed.telemetry = False

    # followups is stored as True, False or the config's fields, which carry the count.
    assert stored["followups"]["num_followups"] == 3
    assert stored["followups"]["instructions"] == INSTRUCTIONS
    assert stored["followups"]["model"]["id"] == "rec-config"
    assert "followup_config" not in stored
    assert isinstance(reconstructed.followups, FollowupConfig)
    assert reconstructed.num_followups == 3  # an explicit 3 stays explicit; it is not read as unset
    assert reconstructed.followups.num_followups == 3
    assert reconstructed.followups.model is models["config"]
    assert reconstructed.followups.instructions == INSTRUCTIONS

    # save -> restore -> copy -> run
    copied = reconstructed.deep_copy()
    output = copied.run("Hi")
    assert output.followups == ["S1", "S2", "S3"]
    assert models["config"].followup_calls == 1
    assert INSTRUCTIONS in models["config"].followup_system_prompts[0]


@pytest.mark.parametrize("kind", ["agent", "team"])
def test_stored_config_without_a_count_still_loads(kind):
    from agno.registry import Registry

    main = RecordingModel("main")
    kwargs = dict(followups=FollowupConfig(instructions=INSTRUCTIONS), num_followups=4, telemetry=False)
    if kind == "agent":
        stored = Agent(id="fu-agent", model=main, **kwargs).to_dict()
    else:
        stored = Team(id="fu-team", members=[], model=main, **kwargs).to_dict()
    # A config stored without a count loads as unset.
    assert "num_followups" not in stored["followups"]

    cls = Agent if kind == "agent" else Team
    reconstructed = cls.from_dict(json.loads(json.dumps(stored)), registry=Registry(models=[main]))
    assert isinstance(reconstructed.followups, FollowupConfig)
    assert reconstructed.num_followups == 4
    assert reconstructed.followups.instructions == INSTRUCTIONS
    assert reconstructed.followups.num_followups is None


def test_followup_config_positional_arguments_keep_their_meaning():
    model = RecordingModel("config")
    config = FollowupConfig(model, INSTRUCTIONS)
    assert config.model is model
    assert config.instructions == INSTRUCTIONS
    assert config.num_followups is None


def test_followup_config_count_serialization_keeps_unset_distinct_from_three():
    assert FollowupConfig().to_dict() == {}
    assert FollowupConfig(num_followups=3).to_dict() == {"num_followups": 3}
    assert FollowupConfig.from_dict({"num_followups": 3}).num_followups == 3
    # A dict stored before the count existed loads as unset.
    assert FollowupConfig.from_dict({"instructions": INSTRUCTIONS}).num_followups is None


@pytest.mark.parametrize("kind", ["agent", "team"])
def test_followups_setting_is_stored_as_bool_or_dict(kind):
    from agno.registry import Registry

    main = RecordingModel("main")
    build = _component_factory(kind)
    assert "followups" not in build(followups=False).to_dict()  # the default is omitted
    assert build(followups=True).to_dict()["followups"] is True
    assert build(followups=FollowupConfig()).to_dict()["followups"] == {}
    assert build(followups=FollowupConfig(instructions=INSTRUCTIONS)).to_dict()["followups"] == {
        "instructions": INSTRUCTIONS
    }

    cls = Agent if kind == "agent" else Team
    registry = Registry(models=[main])
    extra = {"members": []} if kind == "team" else {}
    # A record written before follow-ups could be configured: the released flag plus the legacy fields.
    legacy = {"id": "legacy", "model": main.to_dict(), "followups": True, "num_followups": 4, **extra}
    legacy["followup_model"] = main.to_dict()
    reconstructed = cls.from_dict(json.loads(json.dumps(legacy)), registry=registry)
    assert reconstructed.followups is True
    assert reconstructed.num_followups == 4
    assert reconstructed.followup_model is main
    off = cls.from_dict({"id": "off", "model": main.to_dict(), "followups": False, **extra}, registry=registry)
    assert off.followups is False
    plain = cls.from_dict({"id": "plain", "model": main.to_dict(), **extra}, registry=registry)
    assert plain.followups is False


# --- follow-up models are stored by identity only: no request options, no credentials ---------------


@pytest.mark.parametrize("model_class", ["chat", "responses"])
@pytest.mark.parametrize("kind", ["agent", "team"])
def test_followup_models_are_stored_by_identity_only(kind, model_class):
    from agno.models.openai import OpenAIChat, OpenAIResponses
    from agno.registry import Registry

    cls = OpenAIChat if model_class == "chat" else OpenAIResponses
    headers = {"Authorization": "Bearer synthetic-not-a-real-token", "X-Tenant": "synthetic-tenant"}
    body = {"session_token": "synthetic-body-secret"}
    live = cls(id="gpt-5.5", api_key="sk-synthetic-not-real", extra_headers=headers, extra_body=body)
    main = RecordingModel("main")
    kwargs = dict(followups=FollowupConfig(model=live, instructions=INSTRUCTIONS), followup_model=live)
    if kind == "agent":
        stored = Agent(id="fu-agent", model=main, telemetry=False, **kwargs).to_dict()
    else:
        stored = Team(id="fu-team", members=[], model=main, telemetry=False, **kwargs).to_dict()
    serialized = json.dumps(stored)

    identity = {"id": "gpt-5.5", "name": live.name, "provider": live.provider}
    assert stored["followups"]["model"] == identity
    assert stored["followup_model"] == identity
    for marker in (
        "synthetic-not-a-real-token",
        "synthetic-tenant",
        "synthetic-body-secret",
        "sk-synthetic-not-real",
        "extra_headers",
        "extra_body",
        "Authorization",
    ):
        assert marker not in serialized
    # The caller's model and its header dict are untouched.
    assert live.extra_headers is headers
    assert headers == {"Authorization": "Bearer synthetic-not-a-real-token", "X-Tenant": "synthetic-tenant"}
    assert live.extra_body is body

    component_cls = Agent if kind == "agent" else Team
    registered = component_cls.from_dict(json.loads(serialized), registry=Registry(models=[live, main]))
    assert registered.followups.model is live
    assert registered.followup_model is live
    # Without the registry the identity rebuilds a plain model: no headers can come back from storage.
    rebuilt = component_cls.from_dict(json.loads(serialized), registry=Registry(models=[main]))
    assert isinstance(rebuilt.followups.model, cls)
    assert rebuilt.followups.model.id == "gpt-5.5"
    assert rebuilt.followups.model.extra_headers is None
