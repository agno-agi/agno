"""Two approval-required tool calls in one run need two approval records.

A run that pauses for an @approval tool, is approved, and then pauses again for
a second call (different arguments) must create a second record naming the
second call. Continuing by run id without requirements must not execute the
second call under the first call's approval.
"""

import json
import time
from typing import Any, AsyncIterator, Iterator, List, Optional, Union

import pytest

from agno.agent import Agent
from agno.approval import approval
from agno.db.sqlite import SqliteDb
from agno.metrics import MessageMetrics
from agno.models.base import Model
from agno.models.response import ModelResponse, ModelResponseEvent
from agno.team import Team
from agno.tools import tool

PAID: List[str] = []


class _ScriptedModel(Model):
    """Emits scripted turns offline: ('tool', name, args, id) or ('content', text)."""

    def __init__(self, script: List[tuple]):
        super().__init__(id="scripted", name="scripted", provider="test")
        self._script = list(script)
        self._i = 0

    def _next(self) -> ModelResponse:
        turn = self._script[min(self._i, len(self._script) - 1)]
        self._i += 1
        if turn[0] == "tool":
            _, name, args, tcid = turn
            r = ModelResponse(role="assistant")
            r.tool_calls = [{"id": tcid, "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}]
        else:
            r = ModelResponse(content=turn[1], role="assistant")
            r.event = ModelResponseEvent.assistant_response.value
        r.response_usage = MessageMetrics(input_tokens=10, output_tokens=5, total_tokens=15)
        return r

    def invoke(self, *a, **k):
        return self._next()

    async def ainvoke(self, *a, **k):
        return self._next()

    def invoke_stream(self, *a, **k) -> Iterator[ModelResponse]:
        yield self._next()

    async def ainvoke_stream(self, *a, **k) -> AsyncIterator[ModelResponse]:
        yield self._next()

    def _parse_provider_response(self, response: Any, **k) -> ModelResponse:
        return response if isinstance(response, ModelResponse) else ModelResponse()

    def _parse_provider_response_delta(self, response: Any) -> ModelResponse:
        return response if isinstance(response, ModelResponse) else ModelResponse()


@approval
@tool(requires_confirmation=True)
def pay_invoice(invoice: str) -> str:
    """Pay a vendor invoice.

    Args:
        invoice (str): Invoice number
    """
    PAID.append(invoice)
    return f"PAID {invoice}"


def _script() -> List[tuple]:
    return [
        ("tool", "pay_invoice", {"invoice": "INV-1"}, "call_1"),
        ("tool", "pay_invoice", {"invoice": "INV-2"}, "call_2"),
        ("content", "Paid."),
    ]


def _build_agent(db: SqliteDb) -> Agent:
    return Agent(id="payer", model=_ScriptedModel(_script()), tools=[pay_invoice], db=db, telemetry=False)


def _build_team(db: SqliteDb) -> Team:
    helper = Agent(id="helper", model=_ScriptedModel([("content", "ok")]), telemetry=False)
    return Team(
        id="payer-team",
        model=_ScriptedModel(_script()),
        members=[helper],
        tools=[pay_invoice],
        db=db,
        telemetry=False,
    )


BUILDERS = [pytest.param(_build_agent, id="agent"), pytest.param(_build_team, id="team_level_tool")]


@pytest.fixture
def db(tmp_path):
    PAID.clear()
    return SqliteDb(db_file=str(tmp_path / "approvals.db"))


def _required_records(db: SqliteDb, run_id: str) -> List[dict]:
    records, _ = db.get_approvals(run_id=run_id, approval_type="required")
    return sorted(records, key=lambda r: r["created_at"])


def _named_calls(record: dict) -> List[Optional[str]]:
    return [(r.get("tool_execution") or {}).get("tool_call_id") for r in record.get("requirements") or []]


def _approve_pending(db: SqliteDb, run_id: str) -> int:
    pending, _ = db.get_approvals(run_id=run_id, approval_type="required", status="pending")
    for record in pending:
        db.update_approval(
            record["id"],
            expected_status="pending",
            status="approved",
            resolved_by="admin",
            resolved_at=int(time.time()),
        )
    return len(pending)


def _assert_second_pause_has_own_record(db: SqliteDb, run_id: str) -> None:
    records = _required_records(db, run_id)
    assert len(records) == 2
    assert records[0]["status"] == "approved"
    assert _named_calls(records[0]) == ["call_1"]
    assert records[1]["status"] == "pending"
    assert _named_calls(records[1]) == ["call_2"]
    assert records[1]["tool_args"] == {"invoice": "INV-2"}


def _assert_two_admin_decisions(db: SqliteDb, run_id: str) -> None:
    records = _required_records(db, run_id)
    assert [r["status"] for r in records] == ["approved", "approved"]
    assert [r["resolved_by"] for r in records] == ["admin", "admin"]


@pytest.mark.parametrize("build", BUILDERS)
def test_each_call_needs_its_own_admin_decision(db, build):
    entity: Union[Agent, Team] = build(db)
    run = entity.run("Pay INV-1 and INV-2.")
    assert run.is_paused
    run_id, session_id = run.run_id, run.session_id
    assert _approve_pending(db, run_id) == 1

    run = entity.continue_run(run_id=run_id, session_id=session_id)
    assert run.is_paused
    assert PAID == ["INV-1"]
    _assert_second_pause_has_own_record(db, run_id)

    assert _approve_pending(db, run_id) == 1
    run = entity.continue_run(run_id=run_id, session_id=session_id)
    assert not run.is_paused
    assert PAID == ["INV-1", "INV-2"]
    _assert_two_admin_decisions(db, run_id)


@pytest.mark.parametrize("build", BUILDERS)
@pytest.mark.asyncio
async def test_each_call_needs_its_own_admin_decision_async(db, build):
    entity: Union[Agent, Team] = build(db)
    run = await entity.arun("Pay INV-1 and INV-2.")
    assert run.is_paused
    run_id, session_id = run.run_id, run.session_id
    assert _approve_pending(db, run_id) == 1

    run = await entity.acontinue_run(run_id=run_id, session_id=session_id)
    assert run.is_paused
    assert PAID == ["INV-1"]
    _assert_second_pause_has_own_record(db, run_id)

    assert _approve_pending(db, run_id) == 1
    run = await entity.acontinue_run(run_id=run_id, session_id=session_id)
    assert not run.is_paused
    assert PAID == ["INV-1", "INV-2"]
    _assert_two_admin_decisions(db, run_id)


@pytest.mark.parametrize("build", BUILDERS)
def test_second_call_does_not_run_while_its_approval_is_pending(db, build):
    entity: Union[Agent, Team] = build(db)
    run = entity.run("Pay INV-1 and INV-2.")
    run_id, session_id = run.run_id, run.session_id
    _approve_pending(db, run_id)
    entity.continue_run(run_id=run_id, session_id=session_id)

    # The admin has not decided on INV-2: continuing must not pay it.
    try:
        run = entity.continue_run(run_id=run_id, session_id=session_id)
        assert run.is_paused
    except ValueError:
        pass
    assert PAID == ["INV-1"]
    assert _required_records(db, run_id)[1]["status"] == "pending"
