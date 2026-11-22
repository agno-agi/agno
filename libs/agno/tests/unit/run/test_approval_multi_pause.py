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


# ---------------------------------------------------------------------------
# A required call followed by an audit call, and a member's deleted record
# ---------------------------------------------------------------------------
LOGGED: List[str] = []


@approval(type="audit")
@tool(requires_confirmation=True)
def log_action(note: str) -> str:
    """Log an action for the audit trail.

    Args:
        note (str): What happened
    """
    LOGGED.append(note)
    return "logged"


def _audit_script() -> List[tuple]:
    return [
        ("tool", "pay_invoice", {"invoice": "INV-1"}, "call_1"),
        ("tool", "log_action", {"note": "paid INV-1"}, "call_2"),
        ("content", "Done."),
    ]


def _build_agent_with_audit(db: SqliteDb) -> Agent:
    return Agent(
        id="payer", model=_ScriptedModel(_audit_script()), tools=[pay_invoice, log_action], db=db, telemetry=False
    )


def _build_team_with_audit(db: SqliteDb) -> Team:
    helper = Agent(id="helper", model=_ScriptedModel([("content", "ok")]), telemetry=False)
    return Team(
        id="payer-team",
        model=_ScriptedModel(_audit_script()),
        members=[helper],
        tools=[pay_invoice, log_action],
        db=db,
        telemetry=False,
    )


@pytest.mark.parametrize(
    "build",
    [pytest.param(_build_agent_with_audit, id="agent"), pytest.param(_build_team_with_audit, id="team_level_tool")],
)
def test_audit_call_after_approved_call_can_be_continued(db, build):
    LOGGED.clear()
    entity: Union[Agent, Team] = build(db)
    run = entity.run("Pay INV-1 and log it.")
    assert _approve_pending(db, run.run_id) == 1
    run = entity.continue_run(run_id=run.run_id, session_id=run.session_id)
    assert run.is_paused
    assert PAID == ["INV-1"]

    # The audit call never gets a required record; the client confirms it directly.
    decisions = [r for r in run.requirements if r.tool_execution.tool_call_id == "call_2"]
    decisions[0].confirm()
    run = entity.continue_run(run_id=run.run_id, session_id=run.session_id, requirements=decisions)

    assert not run.is_paused
    assert LOGGED == ["paid INV-1"]
    assert PAID == ["INV-1"]


def test_member_call_does_not_run_when_its_record_is_deleted(db):
    payer = Agent(id="payer", model=_ScriptedModel(_script()), tools=[pay_invoice], db=db, telemetry=False)
    team = Team(
        id="finance-team",
        model=_ScriptedModel(
            [("tool", "delegate_task_to_member", {"member_id": "payer", "task": "Pay"}, "deleg_1"), ("content", "ok")]
        ),
        members=[payer],
        db=db,
        telemetry=False,
    )
    run = team.run("Pay INV-1 and INV-2.")
    pending, _ = db.get_approvals(approval_type="required", status="pending")
    assert [p["tool_args"] for p in pending] == [{"invoice": "INV-1"}]
    _approve_pending(db, pending[0]["run_id"])
    run = team.continue_run(run_id=run.run_id, session_id=run.session_id)
    assert run.is_paused
    assert PAID == ["INV-1"]

    # Delete the second call's pending record: the first call's approval must not run it.
    (second,) = db.get_approvals(approval_type="required", status="pending")[0]
    assert second["tool_args"] == {"invoice": "INV-2"}
    db.delete_approval(second["id"])
    try:
        run = team.continue_run(run_id=run.run_id, session_id=run.session_id)
        assert run.is_paused
    except ValueError:
        pass
    assert PAID == ["INV-1"]


# ---------------------------------------------------------------------------
# Sending every requirement back must not re-run a call that already ran
# ---------------------------------------------------------------------------
AUDIT_BUILDERS = [
    pytest.param(_build_agent_with_audit, id="agent"),
    pytest.param(_build_team_with_audit, id="team_level_tool"),
]


def _confirm_open(run) -> None:
    for req in run.active_requirements:
        if req.needs_confirmation:
            req.confirm()


@pytest.mark.parametrize("build", AUDIT_BUILDERS)
def test_resending_all_requirements_does_not_rerun_executed_call(db, build):
    LOGGED.clear()
    entity: Union[Agent, Team] = build(db)
    run = entity.run("Pay INV-1 and log it.")
    _approve_pending(db, run.run_id)
    run = entity.continue_run(run_id=run.run_id, session_id=run.session_id)
    assert PAID == ["INV-1"]

    # The client confirms the open call and sends back the run's whole requirements
    # list, including the requirement of the INV-1 call that already ran.
    _confirm_open(run)
    run = entity.continue_run(run_id=run.run_id, session_id=run.session_id, requirements=run.requirements)

    assert not run.is_paused
    assert PAID == ["INV-1"]
    assert LOGGED == ["paid INV-1"]


@pytest.mark.parametrize("build", AUDIT_BUILDERS)
@pytest.mark.asyncio
async def test_resending_all_requirements_does_not_rerun_executed_call_async(db, build):
    LOGGED.clear()
    entity: Union[Agent, Team] = build(db)
    run = await entity.arun("Pay INV-1 and log it.")
    _approve_pending(db, run.run_id)
    run = await entity.acontinue_run(run_id=run.run_id, session_id=run.session_id)
    assert PAID == ["INV-1"]

    _confirm_open(run)
    run = await entity.acontinue_run(run_id=run.run_id, session_id=run.session_id, requirements=run.requirements)

    assert not run.is_paused
    assert PAID == ["INV-1"]
    assert LOGGED == ["paid INV-1"]


def _stale_and_executed():
    from agno.models.response import ToolExecution

    executed = ToolExecution(
        tool_call_id="call_1", tool_name="pay_invoice", requires_confirmation=True, confirmed=True, result="PAID INV-1"
    )
    stale = ToolExecution(tool_call_id="call_1", tool_name="pay_invoice", requires_confirmation=True, confirmed=True)
    open_call = ToolExecution(tool_call_id="call_2", tool_name="log_action", requires_confirmation=True)
    decided = ToolExecution(tool_call_id="call_2", tool_name="log_action", requires_confirmation=True, confirmed=True)
    return executed, stale, open_call, decided


def test_agent_merge_keeps_executed_call():
    from agno.agent._run import _apply_requirement_tools
    from agno.run.agent import RunOutput
    from agno.run.requirement import RunRequirement

    executed, stale, open_call, decided = _stale_and_executed()
    run = RunOutput(run_id="r", tools=[executed, open_call])
    _apply_requirement_tools(run, [RunRequirement(tool_execution=stale), RunRequirement(tool_execution=decided)])
    assert run.tools[0] is executed
    assert run.tools[1] is decided


def test_team_merge_keeps_executed_call():
    from agno.team._run import _merge_tools_preserving_approval

    executed, stale, open_call, decided = _stale_and_executed()
    merged = _merge_tools_preserving_approval([executed, open_call], {"call_1": stale, "call_2": decided})
    assert merged[0] is executed
    assert merged[1] is decided


# ---------------------------------------------------------------------------
# Post-hooks see the record of the call the continue runs
# ---------------------------------------------------------------------------
SEEN_BY_HOOK: List[Optional[str]] = []


def _record_seen_by_post_hook(run_output) -> None:
    approval_record = (run_output.metadata or {}).get("approval") or {}
    SEEN_BY_HOOK.append((approval_record.get("tool_args") or {}).get("invoice"))


@pytest.mark.parametrize("build", BUILDERS)
def test_post_hook_sees_the_record_for_the_call_being_run(db, build):
    SEEN_BY_HOOK.clear()
    entity: Union[Agent, Team] = build(db)
    entity.post_hooks = [_record_seen_by_post_hook]
    run = entity.run("Pay INV-1 and INV-2.")
    for _ in range(2):
        _approve_pending(db, run.run_id)
        run = entity.continue_run(run_id=run.run_id, session_id=run.session_id)
        # The hook ran with the continued run's output, which carries the record attached by the gate.
        assert ((run.metadata or {}).get("approval") or {}).get("tool_args") == {"invoice": PAID[-1]}

    assert not run.is_paused
    assert PAID == ["INV-1", "INV-2"]
    assert SEEN_BY_HOOK[-1] == "INV-2"


# ---------------------------------------------------------------------------
# An audit call earlier in the run must not hide a later approval-required call
# ---------------------------------------------------------------------------
def _audit_first_script() -> List[tuple]:
    return [
        ("tool", "log_action", {"note": "start"}, "call_1"),
        ("tool", "pay_invoice", {"invoice": "INV-1"}, "call_2"),
        ("content", "Done."),
    ]


def _build_agent_audit_first(db: SqliteDb) -> Agent:
    return Agent(
        id="payer", model=_ScriptedModel(_audit_first_script()), tools=[log_action, pay_invoice], db=db, telemetry=False
    )


def _build_team_audit_first(db: SqliteDb) -> Team:
    helper = Agent(id="helper", model=_ScriptedModel([("content", "ok")]), telemetry=False)
    return Team(
        id="payer-team",
        model=_ScriptedModel(_audit_first_script()),
        members=[helper],
        tools=[log_action, pay_invoice],
        db=db,
        telemetry=False,
    )


@pytest.mark.parametrize(
    "build",
    [pytest.param(_build_agent_audit_first, id="agent"), pytest.param(_build_team_audit_first, id="team_level_tool")],
)
def test_approval_call_after_audit_call_gets_its_own_record(db, build):
    LOGGED.clear()
    entity: Union[Agent, Team] = build(db)
    run = entity.run("Log, then pay INV-1.")
    decisions = [r for r in run.requirements if not r.is_resolved()]
    for req in decisions:
        req.confirm()
    run = entity.continue_run(run_id=run.run_id, session_id=run.session_id, requirements=decisions)
    assert run.is_paused
    assert LOGGED == ["start"]
    assert PAID == []

    (record,) = _required_records(db, run.run_id)
    assert record["status"] == "pending"
    assert _named_calls(record) == ["call_2"]

    assert _approve_pending(db, run.run_id) == 1
    run = entity.continue_run(run_id=run.run_id, session_id=run.session_id)
    assert not run.is_paused
    assert PAID == ["INV-1"]


# ---------------------------------------------------------------------------
# Deleting the record of a call that already ran must not block the next call
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("build", BUILDERS)
def test_deleted_record_of_executed_call_does_not_block_next_call(db, build):
    entity: Union[Agent, Team] = build(db)
    run = entity.run("Pay INV-1 and INV-2.")
    (first,) = _required_records(db, run.run_id)
    _approve_pending(db, run.run_id)
    run = entity.continue_run(run_id=run.run_id, session_id=run.session_id)
    assert PAID == ["INV-1"]

    # An admin deletes INV-1's record after it ran, then approves INV-2.
    assert db.delete_approval(first["id"])
    assert _approve_pending(db, run.run_id) == 1
    run = entity.continue_run(run_id=run.run_id, session_id=run.session_id)

    assert not run.is_paused
    assert PAID == ["INV-1", "INV-2"]
    assert run.metadata["approval"]["tool_args"] == {"invoice": "INV-2"}


def test_agent_merge_with_repeated_tool_call_id():
    # Some providers send no id and a fallback like call_{i} repeats across turns.
    from agno.agent._run import _apply_requirement_tools
    from agno.models.response import ToolExecution
    from agno.run.agent import RunOutput
    from agno.run.requirement import RunRequirement

    paid = ToolExecution(
        tool_call_id="call_0",
        tool_name="pay_invoice",
        tool_args={"invoice": "INV-1"},
        requires_confirmation=True,
        confirmed=True,
        result="PAID INV-1",
    )
    new = ToolExecution(
        tool_call_id="call_0", tool_name="pay_invoice", tool_args={"invoice": "INV-2"}, requires_confirmation=True
    )
    decided = ToolExecution(
        tool_call_id="call_0",
        tool_name="pay_invoice",
        tool_args={"invoice": "INV-2"},
        requires_confirmation=True,
        confirmed=True,
    )
    run = RunOutput(run_id="r", tools=[paid, new])
    _apply_requirement_tools(run, [RunRequirement(tool_execution=decided)])
    assert run.tools[0] is paid
    assert run.tools[1] is decided
    assert run.tools[1].confirmed is True


def test_team_merge_with_repeated_tool_call_id():
    from agno.models.response import ToolExecution
    from agno.team._run import _merge_tools_preserving_approval

    paid = ToolExecution(
        tool_call_id="call_0",
        tool_name="pay_invoice",
        tool_args={"invoice": "INV-1"},
        requires_confirmation=True,
        confirmed=True,
        result="PAID INV-1",
    )
    new = ToolExecution(
        tool_call_id="call_0", tool_name="pay_invoice", tool_args={"invoice": "INV-2"}, requires_confirmation=True
    )
    decided = ToolExecution(
        tool_call_id="call_0",
        tool_name="pay_invoice",
        tool_args={"invoice": "INV-2"},
        requires_confirmation=True,
        confirmed=True,
    )
    merged = _merge_tools_preserving_approval([paid, new], {"call_0": decided})
    assert merged[0] is paid
    assert merged[1] is decided
