"""Each approval-required call to a team-level tool gets its own approval record.

The tool sits on the Team itself. With parallel tool calls off, a request to
pay two invoices pauses the team run once per call. Continuing by run id after
resolving the run's pending approvals must never execute a call that no
approved record names.
"""

import os
import time
from typing import List, Set

import pytest

from agno.agent import Agent
from agno.approval import approval
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.team.team import Team
from agno.tools import tool

pytestmark = pytest.mark.skipif(not os.getenv("OPENAI_API_KEY"), reason="OPENAI_API_KEY not set")

PAID: List[str] = []


@approval
@tool(requires_confirmation=True)
def pay_invoice(invoice: str) -> str:
    """Pay a vendor invoice. This moves money and cannot be undone.

    Args:
        invoice (str): Invoice number, e.g. INV-1
    """
    PAID.append(invoice)
    return f"PAID {invoice}"


def _make_team(db: SqliteDb) -> Team:
    helper = Agent(
        name="Helper Agent",
        role="Answers general questions",
        model=OpenAIResponses(id="gpt-5.6-luna"),
        telemetry=False,
    )
    return Team(
        name="Finance Team",
        model=OpenAIResponses(id="gpt-5.6-luna", parallel_tool_calls=False),
        members=[helper],
        tools=[pay_invoice],
        db=db,
        telemetry=False,
        instructions=[
            "You pay vendor invoices yourself with the pay_invoice tool. Never delegate payments.",
            "Pay every invoice the user lists: after each pay_invoice result, immediately pay the next unpaid invoice.",
            "Do not reply to the user until every listed invoice has been paid.",
        ],
    )


def _named_calls(db: SqliteDb, run_id: str, status: str) -> Set[str]:
    records, _ = db.get_approvals(run_id=run_id, approval_type="required", status=status)
    return {
        (r.get("tool_execution") or {}).get("tool_call_id") for rec in records for r in rec.get("requirements") or []
    }


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


def _assert_paused_calls_have_pending_records(db: SqliteDb, run) -> None:
    waiting = {t.tool_call_id for t in run.tools or [] if t.tool_name == "pay_invoice" and t.confirmed is None}
    assert waiting, "team paused without a pay_invoice call waiting for approval"
    assert waiting <= _named_calls(db, run.run_id, "pending")


def _assert_every_executed_call_was_approved(db: SqliteDb, run) -> None:
    executed = {t.tool_call_id for t in run.tools or [] if t.tool_name == "pay_invoice" and t.result is not None}
    assert executed <= _named_calls(db, run.run_id, "approved")
    _, total = db.get_approvals(run_id=run.run_id, approval_type="required")
    assert total == len(executed)


@pytest.fixture
def db(shared_db):
    PAID.clear()
    return shared_db


def test_team_tool_each_call_needs_its_own_approval(db):
    team = _make_team(db)
    run = team.run("Pay invoices INV-1 and INV-2.", session_id="team_multi_pause_sync")
    pauses = 0
    while run.is_paused and pauses < 4:
        pauses += 1
        _assert_paused_calls_have_pending_records(db, run)
        assert _approve_pending(db, run.run_id) >= 1
        run = team.continue_run(run_id=run.run_id, session_id=run.session_id)

    assert not run.is_paused
    assert pauses == 2
    assert sorted(PAID) == ["INV-1", "INV-2"]
    _assert_every_executed_call_was_approved(db, run)


@pytest.mark.asyncio
async def test_team_tool_each_call_needs_its_own_approval_async(db):
    team = _make_team(db)
    run = await team.arun("Pay invoices INV-1 and INV-2.", session_id="team_multi_pause_async")
    pauses = 0
    while run.is_paused and pauses < 4:
        pauses += 1
        _assert_paused_calls_have_pending_records(db, run)
        assert _approve_pending(db, run.run_id) >= 1
        run = await team.acontinue_run(run_id=run.run_id, session_id=run.session_id)

    assert not run.is_paused
    assert pauses == 2
    assert sorted(PAID) == ["INV-1", "INV-2"]
    _assert_every_executed_call_was_approved(db, run)


def test_team_tool_pending_second_approval_does_not_execute(db):
    team = _make_team(db)
    run = team.run("Pay invoices INV-1 and INV-2.", session_id="team_multi_pause_blocked")
    assert run.is_paused
    _approve_pending(db, run.run_id)
    run = team.continue_run(run_id=run.run_id, session_id=run.session_id)
    assert run.is_paused
    assert len(PAID) == 1

    # The second call's record is still pending: continuing must not pay it.
    try:
        run = team.continue_run(run_id=run.run_id, session_id=run.session_id)
        assert run.is_paused
    except ValueError:
        pass
    assert len(PAID) == 1
