"""Regression tests for agno-agi/agno#11480.

Cancelling a background Team run during the leader's preflight used to
return success while the leader still delegated to members afterwards:
the cancel path enumerated no member run ids (none were registered yet),
but the delegate tools started member runs anyway, so member tools
executed and completed while the parent ended CANCELLED.

Fix: the delegate tools check the parent run's cancellation state before
starting any new member run, and abort with RunCancelledException when
the parent was already cancelled. Already-running members are untouched;
only starting new ones is gated.

These tests drive a real Team (broadcast mode, delegate_to_all_members)
with deterministic offline models. The leader model pauses in a
"preflight" step so the test can cancel the run before any member run
id is registered, exactly like the reported AgentOS reproduction.
"""

import asyncio
import json
import uuid
from collections.abc import AsyncIterator, Iterator
from typing import Any

import pytest

from agno.agent import Agent
from agno.db.in_memory import InMemoryDb
from agno.models.base import Model
from agno.models.response import ModelResponse
from agno.run.base import RunStatus
from agno.team import Team, TeamMode
from agno.team._run import acancel_run, aget_member_run_ids


def _tool_call(call_id: str, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": call_id,
        "type": "function",
        "function": {"name": name, "arguments": json.dumps(arguments)},
    }


class _LeaderModel(Model):
    """Leader model: waits in preflight, then delegates to all members."""

    def __init__(self, preflight_started: asyncio.Event, release_preflight: asyncio.Event) -> None:
        super().__init__(id="test-leader-model", name="test-leader-model", provider="test")
        self._preflight_started = preflight_started
        self._release_preflight = release_preflight
        self._calls = 0

    def get_instructions_for_model(self, *args: Any, **kwargs: Any):
        return None

    def get_system_message_for_model(self, *args: Any, **kwargs: Any):
        return None

    async def aget_instructions_for_model(self, *args: Any, **kwargs: Any):
        return None

    def invoke(self, *args: Any, **kwargs: Any) -> ModelResponse:
        raise RuntimeError("This test uses the async Team run path")

    async def ainvoke(self, *args: Any, **kwargs: Any) -> ModelResponse:
        self._calls += 1
        if self._calls == 1:
            # Preflight: the window in which cancellation may arrive before
            # any member run id is registered.
            self._preflight_started.set()
            await asyncio.wait_for(self._release_preflight.wait(), timeout=10)
            return ModelResponse(
                role="assistant",
                tool_calls=[
                    _tool_call(f"call_{uuid.uuid4().hex}", "delegate_task_to_members", {"task": "Do the task."})
                ],
            )
        return ModelResponse(role="assistant", content="Leader done.")

    def invoke_stream(self, *args: Any, **kwargs: Any) -> Iterator[ModelResponse]:
        yield self.invoke(*args, **kwargs)

    async def ainvoke_stream(self, *args: Any, **kwargs: Any) -> AsyncIterator[ModelResponse]:
        yield await self.ainvoke(*args, **kwargs)

    def _parse_provider_response(self, response: Any, **kwargs: Any) -> ModelResponse:
        return response if isinstance(response, ModelResponse) else ModelResponse()

    def _parse_provider_response_delta(self, response: Any) -> ModelResponse:
        return self._parse_provider_response(response)


class _MemberModel(Model):
    """Member model: calls its tool once, then answers."""

    def __init__(self, tool_name: str) -> None:
        super().__init__(id="test-member-model", name="test-member-model", provider="test")
        self._member_tool_name = tool_name
        self._calls = 0

    def get_instructions_for_model(self, *args: Any, **kwargs: Any):
        return None

    def get_system_message_for_model(self, *args: Any, **kwargs: Any):
        return None

    async def aget_instructions_for_model(self, *args: Any, **kwargs: Any):
        return None

    def invoke(self, *args: Any, **kwargs: Any) -> ModelResponse:
        raise RuntimeError("This test uses the async Team run path")

    async def ainvoke(self, *args: Any, **kwargs: Any) -> ModelResponse:
        self._calls += 1
        if self._calls == 1:
            return ModelResponse(
                role="assistant",
                tool_calls=[_tool_call(f"call_{uuid.uuid4().hex}", self._member_tool_name, {})],
            )
        return ModelResponse(role="assistant", content="Member done.")

    def invoke_stream(self, *args: Any, **kwargs: Any) -> Iterator[ModelResponse]:
        yield self.invoke(*args, **kwargs)

    async def ainvoke_stream(self, *args: Any, **kwargs: Any) -> AsyncIterator[ModelResponse]:
        yield await self.ainvoke(*args, **kwargs)

    def _parse_provider_response(self, response: Any, **kwargs: Any) -> ModelResponse:
        return response if isinstance(response, ModelResponse) else ModelResponse()

    def _parse_provider_response_delta(self, response: Any) -> ModelResponse:
        return self._parse_provider_response(response)


# Module-level tools: Agno builds Function tools from the callable's
# definition, so closures renamed after definition do not register cleanly.
SIDE_EFFECT_CALLS: list[str] = []


def tool_a() -> str:
    SIDE_EFFECT_CALLS.append("tool_a")
    return "tool_a done"


def tool_b() -> str:
    SIDE_EFFECT_CALLS.append("tool_b")
    return "tool_b done"


def _build_team(
    db: InMemoryDb,
    preflight_started: asyncio.Event,
    release_preflight: asyncio.Event,
) -> Team:
    members = [
        Agent(
            id=f"member-{name}",
            name=f"Member {name}",
            model=_MemberModel(name),
            tools=[tool_a if name == "tool_a" else tool_b],
            db=db,
            telemetry=False,
        )
        for name in ("tool_a", "tool_b")
    ]
    return Team(
        id="cancel-preflight-team",
        name="Cancel Preflight Team",
        mode=TeamMode.broadcast,
        model=_LeaderModel(preflight_started, release_preflight),
        members=members,
        delegate_to_all_members=True,
        db=db,
        telemetry=False,
    )


@pytest.mark.asyncio
async def test_cancel_during_preflight_starts_no_member_runs():
    """Cancelling before member registration must not start member runs (#11480)."""
    db = InMemoryDb()
    preflight_started = asyncio.Event()
    release_preflight = asyncio.Event()
    SIDE_EFFECT_CALLS.clear()
    team = _build_team(db, preflight_started, release_preflight)

    run_id = f"test-cancel-preflight-{uuid.uuid4().hex}"
    run_task = asyncio.create_task(
        team.arun("Do the task.", session_id="cancel-preflight-session", run_id=run_id, stream=False)
    )
    try:
        await asyncio.wait_for(preflight_started.wait(), timeout=10)
        # No member run ids exist yet: this is the reported race window.
        assert await aget_member_run_ids(run_id) == set()
        assert await acancel_run(run_id) is True
        release_preflight.set()
        output = await asyncio.wait_for(run_task, timeout=30)
    finally:
        if not run_task.done():
            run_task.cancel()
            await asyncio.gather(run_task, return_exceptions=True)

    assert output.status == RunStatus.cancelled
    assert await aget_member_run_ids(run_id) == set()
    assert SIDE_EFFECT_CALLS == []


@pytest.mark.asyncio
async def test_no_cancel_runs_members_normally():
    """Control: without cancellation, delegation still runs every member."""
    db = InMemoryDb()
    preflight_started = asyncio.Event()
    release_preflight = asyncio.Event()
    release_preflight.set()
    SIDE_EFFECT_CALLS.clear()
    team = _build_team(db, preflight_started, release_preflight)

    run_id = f"test-cancel-preflight-control-{uuid.uuid4().hex}"
    output = await asyncio.wait_for(
        team.arun("Do the task.", session_id="cancel-preflight-control-session", run_id=run_id, stream=False),
        timeout=30,
    )

    # Member run ids are only tracked while a member run is in flight, so
    # they are gone again once the run completes; the side-effect calls are
    # the proof both members actually ran.
    assert output.status == RunStatus.completed
    assert sorted(SIDE_EFFECT_CALLS) == ["tool_a", "tool_b"]
