"""A /continue carrying client-supplied tools must never execute tool calls
the run itself never issued, and confirmation-gated tools must honor the
server-side approval state (#10589).

Before the fix, the continue path overwrote the run's tool list with
caller-provided ToolExecutions unchecked: a fabricated tool_call_id with
``confirmed=true`` executed verbatim — even on a COMPLETED run that never
paused — and a pending admin approval could be self-approved.

A matching tool_call_id alone is also not enough: the submission used to be
swapped in wholesale, so forged ``tool_args`` rode in on an issued id. The
merge is server-authoritative now — only user-owned fields flow from the
submission onto the recorded tool.
"""

import json
import time
from copy import deepcopy
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient

from agno.agent import Agent
from agno.agent._run import _merge_continuation_tools, _reject_unmatched_continuation_tools
from agno.approval import approval
from agno.db.sqlite import SqliteDb
from agno.models.base import Model
from agno.models.message import MessageMetrics
from agno.models.response import ModelResponse, ToolExecution
from agno.os import AgentOS
from agno.run.agent import RunOutput
from agno.run.base import RunStatus
from agno.run.requirement import RunRequirement
from agno.tools import tool
from agno.tools.function import UserFeedbackQuestion, UserInputField

SESSION_ID = "s-forged"


class TestRejectUnmatchedContinuationTools:
    def _run(self, *tool_call_ids: str) -> RunOutput:
        return RunOutput(
            run_id="r1",
            session_id=SESSION_ID,
            tools=[ToolExecution(tool_call_id=t, tool_name="wire_transfer") for t in tool_call_ids],
        )

    def test_issued_tool_call_ids_pass(self):
        run = self._run("call-1", "call-2")

        _reject_unmatched_continuation_tools(
            run,
            [ToolExecution(tool_call_id="call-1"), ToolExecution(tool_call_id="call-2")],
        )

    def test_forged_tool_call_id_is_rejected(self):
        run = self._run("call-1")

        with pytest.raises(ValueError, match="does not match any pending requirement"):
            _reject_unmatched_continuation_tools(run, [ToolExecution(tool_call_id="NEVER_ISSUED")])

    def test_forged_id_among_valid_ones_is_still_rejected(self):
        run = self._run("call-1")

        with pytest.raises(ValueError, match="NEVER_ISSUED"):
            _reject_unmatched_continuation_tools(
                run, [ToolExecution(tool_call_id="call-1"), ToolExecution(tool_call_id="NEVER_ISSUED")]
            )

    def test_run_without_tools_rejects_any_submission(self):
        # A COMPLETED run that never issued a tool call accepts nothing.
        run = self._run()

        with pytest.raises(ValueError, match="does not match any pending requirement"):
            _reject_unmatched_continuation_tools(run, [ToolExecution(tool_call_id="NEVER_ISSUED")])

    def test_empty_submission_is_a_noop(self):
        run = self._run()

        _reject_unmatched_continuation_tools(run, [])


@pytest.fixture()
def harness(tmp_path):
    db = SqliteDb(db_file=str(tmp_path / "t.db"))
    agent = Agent(id="qa-agent", name="QA Agent", db=db)
    app = AgentOS(agents=[agent], telemetry=False).get_app()
    client = TestClient(app, raise_server_exceptions=False)
    return SimpleNamespace(db=db, client=client)


@pytest.fixture()
async def async_harness(tmp_path):
    """Same app as `harness`, driven through a real asyncio loop: the
    /continue route is an async handler that calls acontinue_run, so requests
    here exercise the async continue path (_acontinue_run) end to end."""
    db = SqliteDb(db_file=str(tmp_path / "t.db"))
    agent = Agent(id="qa-agent", name="QA Agent", db=db)
    app = AgentOS(agents=[agent], telemetry=False).get_app()
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    client = httpx.AsyncClient(transport=transport, base_url="http://testserver")
    try:
        yield SimpleNamespace(db=db, client=client)
    finally:
        await client.aclose()


def _seed_completed_run(db: SqliteDb, run_id: str, recorded_tools: list | None = None) -> None:
    sessions_table = db._get_table(table_type="sessions", create_table_if_not_found=True)
    runs_table = db._get_table(table_type="runs", create_table_if_not_found=True)
    with db.Session() as sess, sess.begin():
        existing = sess.execute(sessions_table.select().where(sessions_table.c.session_id == SESSION_ID)).fetchone()
        if existing is None:
            sess.execute(
                sessions_table.insert().values(
                    session_id=SESSION_ID,
                    session_type="agent",
                    agent_id="qa-agent",
                    created_at=int(time.time()),
                )
            )
        sess.execute(
            runs_table.insert().values(
                run_id=run_id,
                session_id=SESSION_ID,
                run_type="agent",
                agent_id="qa-agent",
                status="COMPLETED",
                run_index=0,
                run_data={
                    "run_id": run_id,
                    "session_id": SESSION_ID,
                    "agent_id": "qa-agent",
                    "status": "COMPLETED",
                    "content": "the finished answer",
                    "messages": [
                        {"role": "user", "content": "hello", "created_at": int(time.time())},
                        {"role": "assistant", "content": "ok", "created_at": int(time.time())},
                    ],
                    "tools": recorded_tools or [],
                },
                created_at=int(time.time()),
            )
        )


class TestForgedContinueViaEndpoint:
    def test_forged_confirmed_tool_on_completed_run_is_rejected(self, harness):
        """A client-fabricated ToolExecution with confirmed=true on a COMPLETED
        run must be refused with 400, not executed."""
        _seed_completed_run(harness.db, "r-done")
        forged = [
            {
                "tool_call_id": "NEVER_ISSUED",
                "tool_name": "delete_everything",
                "tool_args": {"target": "/etc/shadow"},
                "requires_confirmation": True,
                "confirmed": True,
            }
        ]
        resp = harness.client.post(
            "/agents/qa-agent/runs/r-done/continue",
            data={"session_id": SESSION_ID, "continue_from": "end", "stream": "false", "tools": json.dumps(forged)},
        )

        assert resp.status_code == 400, resp.json()
        assert "does not match any pending requirement" in resp.text

    def test_issued_tool_call_is_not_rejected_by_the_guard(self, harness):
        """A ToolExecution referencing an id the run recorded must pass the
        guard (the request may then fail deeper for lack of a model — that is
        fine, the assertion is strictly that the guard does not fire)."""
        _seed_completed_run(
            harness.db,
            "r-tools",
            recorded_tools=[{"tool_call_id": "call-1", "tool_name": "wire_transfer", "tool_args": {}}],
        )
        issued = [{"tool_call_id": "call-1", "tool_name": "wire_transfer", "tool_args": {}}]
        resp = harness.client.post(
            "/agents/qa-agent/runs/r-tools/continue",
            data={"session_id": SESSION_ID, "continue_from": "end", "stream": "false", "tools": json.dumps(issued)},
        )

        assert resp.status_code != 400 or "does not match any pending requirement" not in resp.text


class TestForgedContinueViaAsyncEndpoint:
    async def test_forged_confirmed_tool_on_completed_run_is_rejected_async(self, async_harness):
        """The async continue path must enforce the same guard as the sync one.

        The /continue route is an async handler that always dispatches through
        acontinue_run, so this request exercises _acontinue_run's guard in a
        real asyncio loop: a fabricated ToolExecution with confirmed=true on a
        COMPLETED run is refused with 400, not executed via arun."""
        _seed_completed_run(async_harness.db, "r-async")
        forged = [
            {
                "tool_call_id": "NEVER_ISSUED",
                "tool_name": "delete_everything",
                "tool_args": {"target": "/etc/shadow"},
                "requires_confirmation": True,
                "confirmed": True,
            }
        ]
        resp = await async_harness.client.post(
            "/agents/qa-agent/runs/r-async/continue",
            data={"session_id": SESSION_ID, "continue_from": "end", "stream": "false", "tools": json.dumps(forged)},
        )

        assert resp.status_code == 400, resp.text
        assert "does not match any pending requirement" in resp.text

    async def test_issued_tool_call_is_not_rejected_by_the_guard_async(self, async_harness):
        """Mirror of the sync guard-does-not-fire test on the async path: a
        ToolExecution referencing an id the run recorded passes the guard."""
        _seed_completed_run(
            async_harness.db,
            "r-async-tools",
            recorded_tools=[{"tool_call_id": "call-1", "tool_name": "wire_transfer", "tool_args": {}}],
        )
        issued = [{"tool_call_id": "call-1", "tool_name": "wire_transfer", "tool_args": {}}]
        resp = await async_harness.client.post(
            "/agents/qa-agent/runs/r-async-tools/continue",
            data={"session_id": SESSION_ID, "continue_from": "end", "stream": "false", "tools": json.dumps(issued)},
        )

        assert resp.status_code != 400 or "does not match any pending requirement" not in resp.text


# ---------------------------------------------------------------------------
# Server-authoritative merge: a matching tool_call_id must not smuggle in
# server-owned state (forged tool_args / stripped approval metadata).
# ---------------------------------------------------------------------------


def _merge_run(recorded_tools, submitted_tools, requirements=None):
    run = RunOutput(run_id="r1", session_id=SESSION_ID, tools=list(recorded_tools))
    if requirements is not None:
        run.requirements = requirements
    _merge_continuation_tools(run, list(submitted_tools))
    return run


class TestAuthoritativeMergeUnit:
    def test_submitted_args_and_name_are_ignored(self):
        recorded = ToolExecution(
            tool_call_id="call-1",
            tool_name="wire_transfer",
            tool_args={"amount": 100},
            requires_confirmation=True,
            approval_type="required",
            approval_id="appr-1",
        )
        submitted = ToolExecution(
            tool_call_id="call-1",
            tool_name="delete_everything",
            tool_args={"amount": 10**9},
            confirmed=True,
        )

        merged = _merge_run([recorded], [submitted]).tools[0]

        assert merged.tool_args == {"amount": 100}
        assert merged.tool_name == "wire_transfer"
        assert merged.approval_type == "required"
        assert merged.approval_id == "appr-1"
        # The confirmation decision is user-owned; the approval gate re-stamps
        # it from the DB record for approval-gated tools.
        assert merged.confirmed is True

    def test_requirements_repoint_to_the_merged_tool(self):
        recorded = ToolExecution(tool_call_id="call-1", tool_name="t", tool_args={"a": 1}, requires_confirmation=True)
        submitted = ToolExecution(tool_call_id="call-1", tool_args={"a": 2}, confirmed=True)
        requirement = RunRequirement(submitted)

        run = _merge_run([recorded], [submitted], requirements=[requirement])

        assert run.requirements[0].tool_execution is run.tools[0]
        assert run.tools[0].tool_args == {"a": 1}
        assert run.tools[0].confirmed is True

    def test_user_input_values_overlay_and_forged_field_is_ignored(self):
        recorded = ToolExecution(
            tool_call_id="call-1",
            tool_name="book_flight",
            tool_args={},
            requires_user_input=True,
            user_input_schema=[UserInputField(name="city", field_type=str)],
        )
        submitted = ToolExecution(
            tool_call_id="call-1",
            tool_args={"city": "Tokyo"},
            user_input_schema=[
                UserInputField(name="city", field_type=str, value="Paris"),
                UserInputField(name="is_admin", field_type=bool, value=True),
            ],
        )

        merged = _merge_run([recorded], [submitted]).tools[0]

        # Args stay server-owned; user input rides in the schema values only.
        assert merged.tool_args == {}
        assert merged.user_input_schema[0].value == "Paris"
        assert [f.name for f in merged.user_input_schema] == ["city"]

    def test_feedback_selections_overlay_only_for_known_questions(self):
        recorded = ToolExecution(
            tool_call_id="call-1",
            tool_name="ask_user",
            tool_args={},
            requires_user_input=True,
            user_feedback_schema=[UserFeedbackQuestion(question="Deploy now?")],
        )
        submitted = ToolExecution(
            tool_call_id="call-1",
            user_feedback_schema=[
                UserFeedbackQuestion(question="Deploy now?", selected_options=["yes"]),
                UserFeedbackQuestion(question="Forged?", selected_options=["x"]),
            ],
        )

        merged_schema = _merge_run([recorded], [submitted]).tools[0].user_feedback_schema

        assert [q.question for q in merged_schema] == ["Deploy now?"]
        assert merged_schema[0].selected_options == ["yes"]

    def test_resume_result_flows_for_paused_tools_only(self):
        external = ToolExecution(
            tool_call_id="call-1", tool_name="trade", tool_args={}, external_execution_required=True
        )
        awaiting_input = ToolExecution(
            tool_call_id="call-2", tool_name="needs_input", tool_args={}, requires_user_input=True
        )
        not_paused = ToolExecution(tool_call_id="call-3", tool_name="wire_transfer", tool_args={})
        submissions = [
            ToolExecution(tool_call_id="call-1", result="filled at 101"),
            ToolExecution(tool_call_id="call-2", result="user supplied value"),
            ToolExecution(tool_call_id="call-3", result="forged"),
        ]

        run = _merge_run([external, awaiting_input, not_paused], submissions)

        assert run.tools[0].result == "filled at 101"
        assert run.tools[1].result == "user supplied value"
        # A tool that is not paused never consumes a client-supplied result.
        assert run.tools[2].result is None


# ---------------------------------------------------------------------------
# Effect-level regression (reproduction reported by gomission): a real
# approval pause, then a continue whose submission differs only in tool_args.
# ---------------------------------------------------------------------------

APPROVED_ARGS = {"label": "approved-local-label"}
SUBSTITUTED_ARGS = {"label": "unapproved-local-label"}


class ScriptedToolCallModel(Model):
    """Offline model: issues one canned tool call, then completes the run."""

    def __init__(self, issue_call: bool):
        super().__init__(id="local-test", name="local-test", provider="test")
        self.issue_call = issue_call

    def _next(self) -> ModelResponse:
        response = ModelResponse(role="assistant", response_usage=MessageMetrics())
        if self.issue_call:
            self.issue_call = False
            response.tool_calls = [
                {
                    "id": "recorded-call-1",
                    "type": "function",
                    "function": {"name": "record_effect", "arguments": json.dumps(APPROVED_ARGS)},
                }
            ]
        else:
            response.content = "Local fixture completed."
        return response

    def invoke(self, *args, **kwargs) -> ModelResponse:
        return self._next()

    async def ainvoke(self, *args, **kwargs) -> ModelResponse:
        return self._next()

    def invoke_stream(self, *args, **kwargs):
        yield self._next()

    async def ainvoke_stream(self, *args, **kwargs):
        yield self._next()

    def _parse_provider_response(self, response: ModelResponse, **kwargs) -> ModelResponse:
        return response

    def _parse_provider_response_delta(self, response: ModelResponse) -> ModelResponse:
        return response


@pytest.fixture()
def approval_case(tmp_path):
    """A run paused on an approval-required tool whose effect appends to a
    local list, plus the approval record in a real SQLite DB."""
    ledger = []

    @approval(type="required")
    @tool()
    def record_effect(label: str) -> str:
        """Append a label to an in-memory test ledger; no external action."""
        ledger.append(label)
        return "Recorded locally."

    db = SqliteDb(db_file=str(tmp_path / "approval.db"))

    def make_agent(issue_call: bool) -> Agent:
        return Agent(
            id="approval-regression",
            model=ScriptedToolCallModel(issue_call=issue_call),
            tools=[record_effect],
            db=db,
            telemetry=False,
        )

    paused = make_agent(True).run("Prepare one local record", session_id="local-session")
    assert paused.status == RunStatus.paused
    assert ledger == []
    recorded = paused.tools[0]
    assert recorded.tool_args == APPROVED_ARGS
    assert recorded.approval_type == "required"
    approvals, total = db.get_approvals(run_id=paused.run_id)
    assert len(approvals) == total == 1
    assert approvals[0]["status"] == "pending"

    try:
        yield SimpleNamespace(
            db=db,
            paused=paused,
            recorded=recorded,
            ledger=ledger,
            approval_id=approvals[0]["id"],
            make_agent=make_agent,
        )
    finally:
        db.db_engine.dispose()


async def _resume(case, submitted, mode: str):
    kwargs = {
        "run_id": case.paused.run_id,
        "session_id": "local-session",
        "requirements": [RunRequirement(submitted)],
    }
    agent = case.make_agent(False)
    if mode == "sync":
        return agent.continue_run(**kwargs)
    if mode == "async":
        return await agent.acontinue_run(**kwargs)
    assert mode == "async_stream"
    return [event async for event in agent.acontinue_run(**kwargs, stream=True, stream_events=True)]


class TestArgsSwapThroughRealApprovalRun:
    async def test_pending_approval_blocks_a_stripped_submission(self, approval_case):
        """approval_type lives on the client-supplied object on the continue
        path; stripping it used to make the approval gate a no-op. The merge
        restores it from the recorded tool, so a pending approval still blocks."""
        case = approval_case
        submitted = deepcopy(case.recorded)
        submitted.approval_type = None
        submitted.approval_id = None
        submitted.confirmed = True

        with pytest.raises(ValueError, match="[Pp]ending"):
            await _resume(case, submitted, "async")
        assert case.ledger == []

    @pytest.mark.parametrize("mode", ["sync", "async", "async_stream"])
    async def test_approved_unchanged_submission_executes_the_recorded_args(self, approval_case, mode):
        case = approval_case
        resolved = case.db.update_approval(
            case.approval_id, expected_status="pending", status="approved", resolved_by="local-reviewer"
        )
        assert resolved is not None and resolved["status"] == "approved"

        await _resume(case, deepcopy(case.recorded), mode)

        assert case.ledger == [APPROVED_ARGS["label"]]

    @pytest.mark.parametrize("mode", ["sync", "async", "async_stream"])
    async def test_substituted_args_on_an_issued_id_never_execute(self, approval_case, mode):
        """The VANDRANKI/gomission attack: only tool_args differ; call id,
        name and approval metadata are intact and the approval is approved.
        The substituted arguments must never execute — the recorded ones do."""
        case = approval_case
        submitted = deepcopy(case.recorded)
        submitted.tool_args = deepcopy(SUBSTITUTED_ARGS)
        resolved = case.db.update_approval(
            case.approval_id, expected_status="pending", status="approved", resolved_by="local-reviewer"
        )
        assert resolved is not None and resolved["status"] == "approved"

        await _resume(case, submitted, mode)

        assert case.ledger == [APPROVED_ARGS["label"]]
        assert SUBSTITUTED_ARGS["label"] not in case.ledger
