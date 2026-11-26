"""Per-call response_schema on delegate_task_to_member, and the cap on concurrent delegations."""

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import BaseModel

from agno.agent import Agent
from agno.run import RunContext
from agno.run.agent import RunOutput
from agno.run.team import TeamRunOutput
from agno.session.team import TeamSession
from agno.team.team import Team

SCORE_SCHEMA = json.dumps(
    {
        "type": "object",
        "title": "Score",
        "properties": {"name": {"type": "string"}, "score": {"type": "integer"}},
        "required": ["name", "score"],
    }
)


def _member(member_id: str) -> Agent:
    agent = Agent(name=member_id, id=member_id)
    agent.arun = AsyncMock(return_value=RunOutput(run_id=f"run-{member_id}", agent_id=member_id, content="done"))  # type: ignore[method-assign]
    agent.run = MagicMock(return_value=RunOutput(run_id=f"run-{member_id}", agent_id=member_id, content="done"))  # type: ignore[method-assign]
    return agent


def _delegate(team: Team, async_mode: bool = False):
    return team._get_delegate_task_function(
        session=TeamSession(session_id="s"),
        run_response=TeamRunOutput(run_id="team-run"),
        run_context=RunContext(session_state={}, run_id="team-run", session_id="s"),
        team_run_context={},
        async_mode=async_mode,
    )


async def _drain(gen) -> list:
    return [item async for item in gen]


def _params(function, strict: bool = False) -> set:
    function.process_entrypoint(strict=strict)
    return set(function.parameters["properties"])


def test_tool_schema_unchanged_when_flag_off():
    team = Team(members=[_member("a")])
    assert _params(_delegate(team)) == {"member_id", "task"}


def test_tool_takes_response_schema_when_flag_on():
    team = Team(members=[_member("a")], enable_member_response_schema=True)
    assert _params(_delegate(team)) == {"member_id", "task", "response_schema"}
    assert "response_schema" in _params(_delegate(team, async_mode=True))


@pytest.mark.parametrize("strict", [False, True])
def test_response_schema_is_a_plain_string_in_the_tool_schema(strict):
    # A free-form object parameter collapses to {} under strict tool schemas; a string survives both
    function = _delegate(Team(members=[_member("a")], enable_member_response_schema=True))
    _params(function, strict=strict)
    assert function.parameters["properties"]["response_schema"]["type"] == "string"


def test_empty_string_means_no_schema():
    # Strict mode makes the argument required, so the leader sends "" for a plain-text answer
    member = _member("a")
    team = Team(members=[member], enable_member_response_schema=True)
    list(_delegate(team).entrypoint(member_id="a", task="x", response_schema=""))
    assert "output_schema" not in member.run.call_args.kwargs


def test_respond_directly_keeps_plain_tool():
    team = Team(members=[_member("a")], enable_member_response_schema=True, respond_directly=True)
    assert _params(_delegate(team)) == {"member_id", "task"}


def test_sync_schema_reaches_member_as_output_schema():
    member = _member("a")
    team = Team(members=[member], enable_member_response_schema=True)
    list(_delegate(team).entrypoint(member_id="a", task="score it", response_schema=SCORE_SCHEMA))
    output_schema = member.run.call_args.kwargs["output_schema"]
    assert issubclass(output_schema, BaseModel)
    assert set(output_schema.model_fields) == {"name", "score"}


@pytest.mark.asyncio
async def test_async_schema_reaches_member_as_output_schema():
    member = _member("a")
    team = Team(members=[member], enable_member_response_schema=True)
    await _drain(_delegate(team, async_mode=True).entrypoint(member_id="a", task="x", response_schema=SCORE_SCHEMA))
    assert set(member.arun.call_args.kwargs["output_schema"].model_fields) == {"name", "score"}


def test_no_schema_leaves_member_schema_alone():
    member = _member("a")
    team = Team(members=[member], enable_member_response_schema=True)
    list(_delegate(team).entrypoint(member_id="a", task="x"))
    assert "output_schema" not in member.run.call_args.kwargs


def _deep(levels: int) -> dict:
    node: dict = {"type": "string"}
    for _ in range(levels):
        node = {"type": "object", "properties": {"x": node}}
    return node


_REF_SCHEMA = {
    "type": "object",
    "properties": {"r": {"$ref": "#/$defs/N"}},
    "$defs": {"N": {"type": "object", "properties": {"a": {"type": "string"}}}},
}
_MAP_SCHEMA = {"type": "object", "properties": {"m": {"type": "object", "additionalProperties": _deep(8)}}}


@pytest.mark.parametrize(
    "schema",
    [
        "not json",
        json.dumps(["a", "list"]),
        json.dumps({"type": "array", "items": {"type": "string"}}),
        json.dumps({"type": "object", "properties": {f"p{i}": {"type": "string"} for i in range(40)}}),
        json.dumps(_deep(8)),
        json.dumps({"type": "object", "properties": {"a": {"type": "string", "description": "x" * 5000}}}),
        json.dumps(_REF_SCHEMA),
        json.dumps({"type": "object", "properties": {"a": {"anyOf": [{"type": "string"}, {"type": "integer"}]}}}),
        json.dumps(_MAP_SCHEMA),
    ],
    ids=["not-json", "list-root", "array-root", "too-many-props", "too-deep", "too-big", "ref", "any-of", "deep-map"],
)
def test_bad_schema_is_refused_without_running_member(schema):
    member = _member("a")
    team = Team(members=[member], enable_member_response_schema=True)
    out = list(_delegate(team).entrypoint(member_id="a", task="x", response_schema=schema))
    assert out and out[0].startswith("Invalid response_schema")
    member.run.assert_not_called()


@pytest.mark.asyncio
async def test_concurrent_delegations_are_capped():
    active = 0
    peak = 0

    async def slow_run(*args, **kwargs):
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        await asyncio.sleep(0.02)
        active -= 1
        return RunOutput(run_id=kwargs.get("run_id"), agent_id="a", content="done")

    member = _member("a")
    member.arun = AsyncMock(side_effect=slow_run)  # type: ignore[method-assign]
    team = Team(members=[member], max_concurrent_delegations=2)
    function = _delegate(team, async_mode=True)
    await asyncio.gather(*(_drain(function.entrypoint(member_id="a", task=f"t{i}")) for i in range(5)))
    assert member.arun.call_count == 5
    assert peak == 2


@pytest.mark.asyncio
async def test_queued_delegation_does_not_start_after_cancel():
    from agno.exceptions import RunCancelledException
    from agno.run.cancel import cancel_run, cleanup_run, register_run

    release = asyncio.Event()

    async def blocking_run(*args, **kwargs):
        await release.wait()
        return RunOutput(run_id=kwargs.get("run_id"), agent_id="a", content="done")

    member = _member("a")
    member.arun = AsyncMock(side_effect=blocking_run)  # type: ignore[method-assign]
    team = Team(members=[member], max_concurrent_delegations=1)
    function = _delegate(team, async_mode=True)
    register_run("team-run")
    try:
        first = asyncio.ensure_future(_drain(function.entrypoint(member_id="a", task="first")))
        queued = asyncio.ensure_future(_drain(function.entrypoint(member_id="a", task="queued")))
        await asyncio.sleep(0.01)
        cancel_run("team-run")
        release.set()
        await asyncio.gather(first, queued, return_exceptions=True)
        assert isinstance(queued.exception(), RunCancelledException)
        assert member.arun.call_count == 1
    finally:
        cleanup_run("team-run")


def test_settings_warn_outside_coordinate_mode():
    from unittest.mock import patch

    from agno.team.mode import TeamMode

    with patch("agno.team._init.log_warning") as warn:
        Team(members=[], mode=TeamMode.broadcast, enable_member_response_schema=True, max_concurrent_delegations=2)
    assert warn.call_count == 2
    with patch("agno.team._init.log_warning") as warn:
        Team(members=[], enable_member_response_schema=True, max_concurrent_delegations=2)
    warn.assert_not_called()


def test_invalid_cap_is_rejected():
    with pytest.raises(ValueError):
        Team(members=[], max_concurrent_delegations=0)


def test_prompt_mentions_response_schema_only_when_enabled():
    from agno.team._messages import _get_mode_instructions

    plain = _get_mode_instructions(Team(members=[_member("a")]))
    typed = _get_mode_instructions(Team(members=[_member("a")], enable_member_response_schema=True))
    assert "response_schema" not in plain
    assert "response_schema" in typed


def test_config_round_trip():
    team = Team(members=[], enable_member_response_schema=True, max_concurrent_delegations=3)
    config = team.to_dict()
    assert config["enable_member_response_schema"] is True
    assert config["max_concurrent_delegations"] == 3
    restored = Team.from_dict(config)
    assert restored.enable_member_response_schema is True
    assert restored.max_concurrent_delegations == 3
