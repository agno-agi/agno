"""A requires_user_input tool must not run until the user has filled its fields.

Continuing a paused run with a field still empty used to dispatch the tool with
None for that argument and complete the run. The continue now re-pauses instead,
on every continue path (sync/async, streaming/non-streaming), and a later
continue that supplies the answer runs the tool with it.
"""

import asyncio
import json
from typing import Any, AsyncIterator, Dict, Iterator, List, Optional

import pytest

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.base import Model
from agno.models.response import ModelResponse, ModelResponseEvent
from agno.run.agent import RunOutput
from agno.run.base import RunStatus
from agno.run.requirement import RunRequirement
from agno.tools import tool


class _ScriptedModel(Model):
    """Emits scripted turns offline: ('tools', [(name, args, id), ...]) or ('content', text)."""

    def __init__(self, script: List[tuple]):
        super().__init__(id="scripted", name="scripted", provider="test")
        self._script = list(script)
        self._i = 0

    def _next(self) -> ModelResponse:
        turn = self._script[min(self._i, len(self._script) - 1)]
        self._i += 1
        if turn[0] == "tools":
            r = ModelResponse(role="assistant")
            r.tool_calls = [
                {"id": tcid, "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}
                for name, args, tcid in turn[1]
            ]
        else:
            r = ModelResponse(content=turn[1], role="assistant")
            r.event = ModelResponseEvent.assistant_response.value
        return r

    def invoke(self, *a, **k):
        return self._next()

    async def ainvoke(self, *a, **k):
        return self._next()

    def invoke_stream(self, *a, **k) -> Iterator[ModelResponse]:
        yield self._next()

    async def ainvoke_stream(self, *a, **k) -> AsyncIterator[ModelResponse]:
        yield self._next()

    def parse_provider_response(self, response: Any, **k) -> ModelResponse:
        return response if isinstance(response, ModelResponse) else ModelResponse()

    def parse_provider_response_delta(self, response: Any) -> ModelResponse:
        return response if isinstance(response, ModelResponse) else ModelResponse()

    def _parse_provider_response(self, response: Any, **k) -> ModelResponse:
        return response if isinstance(response, ModelResponse) else ModelResponse()

    def _parse_provider_response_delta(self, response: Any) -> ModelResponse:
        return response if isinstance(response, ModelResponse) else ModelResponse()


_TRANSFERS: List[Dict[str, Any]] = []
_EMAILS: List[str] = []


@tool(requires_user_input=True, user_input_fields=["note"])
def transfer_funds(account_id: str, note: Optional[str] = None) -> str:
    _TRANSFERS.append({"account_id": account_id, "note": note})
    return "Transfer done."


@tool(requires_confirmation=True)
def send_email(to: str) -> str:
    _EMAILS.append(to)
    return f"Email sent to {to}"


@pytest.fixture(autouse=True)
def _reset_side_effects():
    _TRANSFERS.clear()
    _EMAILS.clear()


def _banker(db: SqliteDb, calls: List[tuple]) -> Agent:
    return Agent(
        name="Banker",
        id="banker",
        model=_ScriptedModel([("tools", calls), ("content", "Done.")]),
        tools=[transfer_funds, send_email],
        db=db,
        telemetry=False,
    )


def _wire(requirements, values: Optional[Dict[str, Any]] = None) -> List[RunRequirement]:
    """Round-trip requirements the way a client sends them back, optionally answering them."""
    payload = []
    for data in [r.to_dict() for r in requirements or []]:
        req = RunRequirement.from_dict(data)
        if req.needs_confirmation:
            req.confirm()
        if values is not None and req.needs_user_input:
            req.provide_user_input(values)
        payload.append(req)
    return payload


def _continue(agent: Agent, mode: str, run_id: str, session_id: str, requirements) -> RunStatus:
    kwargs = dict(run_id=run_id, session_id=session_id, requirements=requirements)
    if mode == "sync":
        return agent.continue_run(**kwargs).status
    if mode == "async":
        return asyncio.run(agent.acontinue_run(**kwargs)).status
    if mode == "sync_stream":
        final = [
            e for e in agent.continue_run(stream=True, yield_run_output=True, **kwargs) if isinstance(e, RunOutput)
        ]
        return final[-1].status

    async def _drain():
        return [
            e
            async for e in agent.acontinue_run(stream=True, yield_run_output=True, **kwargs)
            if isinstance(e, RunOutput)
        ]

    return asyncio.run(_drain())[-1].status


MODES = ["sync", "async", "sync_stream", "async_stream"]


@pytest.mark.parametrize("mode", MODES)
def test_unanswered_field_repauses_instead_of_running_the_tool(tmp_path, mode):
    db = SqliteDb(db_file=str(tmp_path / "unanswered.db"))
    run1 = _banker(db, [("transfer_funds", {"account_id": "acc-1"}, "tc-xfer")]).run("Move it", session_id="s1")
    assert run1.is_paused

    status = _continue(_banker(db, []), mode, run1.run_id, "s1", _wire(run1.requirements))

    assert status == RunStatus.paused
    assert _TRANSFERS == []
    stored = db.get_run(run1.run_id)
    assert stored.status == RunStatus.paused
    assert [r.needs_user_input for r in stored.requirements] == [True]


@pytest.mark.parametrize("mode", MODES)
def test_repaused_run_resumes_once_the_field_is_answered(tmp_path, mode):
    db = SqliteDb(db_file=str(tmp_path / "answered.db"))
    run1 = _banker(db, [("transfer_funds", {"account_id": "acc-1"}, "tc-xfer")]).run("Move it", session_id="s1")
    assert _continue(_banker(db, []), mode, run1.run_id, "s1", _wire(run1.requirements)) == RunStatus.paused

    stored = db.get_run(run1.run_id)
    status = _continue(_banker(db, []), mode, run1.run_id, "s1", _wire(stored.requirements, {"note": "rent"}))

    assert status == RunStatus.completed
    assert _TRANSFERS == [{"account_id": "acc-1", "note": "rent"}]


def test_in_process_continue_without_an_answer_repauses():
    agent = _banker(None, [("transfer_funds", {"account_id": "acc-1"}, "tc-xfer")])  # type: ignore[arg-type]
    run1 = agent.run("Move it")
    assert run1.is_paused

    run2 = agent.continue_run(run_response=run1)

    assert run2.status == RunStatus.paused
    assert _TRANSFERS == []


def test_answered_flag_without_a_value_does_not_run_the_tool(tmp_path):
    db = SqliteDb(db_file=str(tmp_path / "flag.db"))
    run1 = _banker(db, [("transfer_funds", {"account_id": "acc-1"}, "tc-xfer")]).run("Move it", session_id="s1")

    payload = _wire(run1.requirements)
    for req in payload:
        req.tool_execution.answered = True

    run2 = _banker(db, []).continue_run(run_id=run1.run_id, session_id="s1", requirements=payload)

    assert run2.status == RunStatus.paused
    assert _TRANSFERS == []


def test_nothing_in_the_batch_runs_while_a_field_is_open(tmp_path):
    """A confirmed call next to an unanswered one waits too, so the batch runs once, together."""
    db = SqliteDb(db_file=str(tmp_path / "batch.db"))
    calls = [
        ("send_email", {"to": "a@example.com"}, "tc-email"),
        ("transfer_funds", {"account_id": "acc-1"}, "tc-xfer"),
    ]
    run1 = _banker(db, calls).run("Do both", session_id="s1")
    assert run1.is_paused

    run2 = _banker(db, []).continue_run(run_id=run1.run_id, session_id="s1", requirements=_wire(run1.requirements))
    assert run2.status == RunStatus.paused
    assert _EMAILS == [] and _TRANSFERS == []

    stored = db.get_run(run1.run_id)
    run3 = _banker(db, []).continue_run(
        run_id=run1.run_id, session_id="s1", requirements=_wire(stored.requirements, {"note": "rent"})
    )
    assert run3.status == RunStatus.completed
    assert _EMAILS == ["a@example.com"]
    assert _TRANSFERS == [{"account_id": "acc-1", "note": "rent"}]
