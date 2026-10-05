"""Unit tests for agno.run.approval — approval record creation and resolution gating."""

from dataclasses import dataclass
from typing import Any, Dict, Optional
from unittest.mock import AsyncMock, MagicMock

import pytest

from agno.run.approval import (
    _apply_approval_to_tools,
    _build_approval_dict,
    _get_first_approval_tool,
    _get_pause_type,
    _has_approval_requirement,
    acheck_and_apply_approval_resolution,
    acreate_approval_from_pause,
    acreate_audit_approval,
    check_and_apply_approval_resolution,
    create_approval_from_pause,
    create_audit_approval,
)

# =============================================================================
# Helpers: lightweight stand-ins for ToolExecution / RunResponse / UserInputField
# =============================================================================


@dataclass
class FakeToolExecution:
    tool_name: Optional[str] = None
    tool_call_id: Optional[str] = None
    tool_args: Optional[Dict[str, Any]] = None
    approval_type: Optional[str] = None
    approval_id: Optional[str] = None
    requires_confirmation: Optional[bool] = None
    requires_user_input: Optional[bool] = None
    external_execution_required: Optional[bool] = None
    user_input_schema: Optional[list] = None
    confirmed: Optional[bool] = None
    result: Optional[str] = None


@dataclass
class FakeRequirement:
    tool_execution: Optional[FakeToolExecution] = None

    def to_dict(self) -> Dict[str, Any]:
        return {"tool_execution": self.tool_execution.tool_name if self.tool_execution else None}


@dataclass
class FakeRunResponse:
    run_id: Optional[str] = "run-123"
    session_id: Optional[str] = "sess-456"
    tools: Optional[list] = None
    requirements: Optional[list] = None
    metadata: Optional[Dict[str, Any]] = None


@dataclass
class FakeUserInputField:
    name: str = ""
    value: Optional[str] = None


# =============================================================================
# _get_pause_type
# =============================================================================


class TestGetPauseType:
    def test_user_input(self):
        te = FakeToolExecution(requires_user_input=True)
        assert _get_pause_type(te) == "user_input"

    def test_external_execution(self):
        te = FakeToolExecution(external_execution_required=True)
        assert _get_pause_type(te) == "external_execution"

    def test_confirmation_default(self):
        te = FakeToolExecution()
        assert _get_pause_type(te) == "confirmation"

    def test_user_input_takes_precedence(self):
        """user_input is checked before external_execution."""
        te = FakeToolExecution(requires_user_input=True, external_execution_required=True)
        assert _get_pause_type(te) == "user_input"


# =============================================================================
# _get_first_approval_tool
# =============================================================================


class TestGetFirstApprovalTool:
    def test_returns_none_when_empty(self):
        assert _get_first_approval_tool(None) is None
        assert _get_first_approval_tool([]) is None

    def test_finds_tool_in_tools_list(self):
        t1 = FakeToolExecution(tool_name="t1", approval_type=None)
        t2 = FakeToolExecution(tool_name="t2", approval_type="required")
        assert _get_first_approval_tool([t1, t2]) is t2

    def test_finds_tool_in_requirements(self):
        te = FakeToolExecution(tool_name="req_tool", approval_type="audit")
        req = FakeRequirement(tool_execution=te)
        assert _get_first_approval_tool(None, requirements=[req]) is te

    def test_tools_list_takes_precedence(self):
        t_in_tools = FakeToolExecution(tool_name="from_tools", approval_type="required")
        t_in_reqs = FakeToolExecution(tool_name="from_reqs", approval_type="required")
        req = FakeRequirement(tool_execution=t_in_reqs)
        result = _get_first_approval_tool([t_in_tools], requirements=[req])
        assert result is t_in_tools


# =============================================================================
# _has_approval_requirement
# =============================================================================


class TestHasApprovalRequirement:
    def test_false_when_no_tools(self):
        assert _has_approval_requirement(None) is False

    def test_false_when_approval_type_is_audit(self):
        t = FakeToolExecution(approval_type="audit")
        assert _has_approval_requirement([t]) is False

    def test_true_when_approval_type_is_required(self):
        t = FakeToolExecution(approval_type="required")
        assert _has_approval_requirement([t]) is True

    def test_true_via_requirements(self):
        te = FakeToolExecution(approval_type="required")
        req = FakeRequirement(tool_execution=te)
        assert _has_approval_requirement(None, requirements=[req]) is True


# =============================================================================
# _build_approval_dict
# =============================================================================


class TestBuildApprovalDict:
    def test_basic_agent_source(self):
        rr = FakeRunResponse(
            tools=[FakeToolExecution(tool_name="delete_file", approval_type="required", requires_confirmation=True)]
        )
        result = _build_approval_dict(rr, agent_id="a1", agent_name="MyAgent")
        assert result["source_type"] == "agent"
        assert result["source_name"] == "MyAgent"
        assert result["agent_id"] == "a1"
        assert result["tool_name"] == "delete_file"
        assert result["approval_type"] == "required"
        assert result["status"] == "pending"
        assert result["run_id"] == "run-123"
        assert result["session_id"] == "sess-456"
        assert isinstance(result["id"], str)
        assert isinstance(result["created_at"], int)

    def test_team_source_overrides_agent(self):
        rr = FakeRunResponse(tools=[FakeToolExecution(tool_name="t", approval_type="required")])
        result = _build_approval_dict(rr, agent_id="a1", agent_name="A", team_id="t1", team_name="MyTeam")
        assert result["source_type"] == "team"
        assert result["source_name"] == "MyTeam"

    def test_workflow_source(self):
        rr = FakeRunResponse(tools=[FakeToolExecution(tool_name="t", approval_type="required")])
        result = _build_approval_dict(rr, workflow_id="w1", workflow_name="MyWorkflow")
        assert result["source_type"] == "workflow"
        assert result["source_name"] == "MyWorkflow"

    def test_session_id_falls_back_to_empty_string(self):
        rr = FakeRunResponse(session_id=None, tools=[FakeToolExecution(approval_type="required")])
        result = _build_approval_dict(rr)
        assert result["session_id"] == ""

    def test_run_id_falls_back_to_uuid(self):
        rr = FakeRunResponse(run_id=None, tools=[FakeToolExecution(approval_type="required")])
        result = _build_approval_dict(rr)
        assert isinstance(result["run_id"], str)
        assert len(result["run_id"]) > 0

    def test_context_includes_tool_names_from_requirements(self):
        te1 = FakeToolExecution(tool_name="tool_a", approval_type="required")
        te2 = FakeToolExecution(tool_name="tool_b", approval_type="required")
        rr = FakeRunResponse(requirements=[FakeRequirement(tool_execution=te1), FakeRequirement(tool_execution=te2)])
        result = _build_approval_dict(rr)
        assert result["context"]["tool_names"] == ["tool_a", "tool_b"]

    def test_context_falls_back_to_tools_list(self):
        t1 = FakeToolExecution(tool_name="my_tool", approval_type="required")
        rr = FakeRunResponse(tools=[t1])
        result = _build_approval_dict(rr)
        assert result["context"]["tool_names"] == ["my_tool"]

    def test_pause_type_from_user_input_tool(self):
        t = FakeToolExecution(tool_name="ask", approval_type="required", requires_user_input=True)
        rr = FakeRunResponse(tools=[t])
        result = _build_approval_dict(rr)
        assert result["pause_type"] == "user_input"

    def test_pause_type_from_external_execution_tool(self):
        t = FakeToolExecution(tool_name="ext", approval_type="required", external_execution_required=True)
        rr = FakeRunResponse(tools=[t])
        result = _build_approval_dict(rr)
        assert result["pause_type"] == "external_execution"

    def test_schedule_fields_passed_through(self):
        rr = FakeRunResponse(tools=[FakeToolExecution(approval_type="required")])
        result = _build_approval_dict(rr, schedule_id="sched-1", schedule_run_id="sr-1")
        assert result["schedule_id"] == "sched-1"
        assert result["schedule_run_id"] == "sr-1"


# =============================================================================
# create_approval_from_pause (sync)
# =============================================================================


class TestCreateApprovalFromPause:
    def test_noop_when_db_is_none(self):
        rr = FakeRunResponse(tools=[FakeToolExecution(approval_type="required")])
        create_approval_from_pause(db=None, run_response=rr)  # should not raise

    def test_noop_when_no_approval_requirement(self):
        db = MagicMock()
        rr = FakeRunResponse(tools=[FakeToolExecution(approval_type=None)])
        create_approval_from_pause(db=db, run_response=rr)
        db.create_approval.assert_not_called()

    def test_creates_approval_record(self):
        db = MagicMock()
        rr = FakeRunResponse(tools=[FakeToolExecution(tool_name="delete", approval_type="required")])
        create_approval_from_pause(db=db, run_response=rr, agent_id="a1", agent_name="Agent")
        db.create_approval.assert_called_once()
        data = db.create_approval.call_args[0][0]
        assert data["status"] == "pending"
        assert data["agent_id"] == "a1"

    def test_silently_handles_not_implemented(self):
        db = MagicMock()
        db.create_approval.side_effect = NotImplementedError
        rr = FakeRunResponse(tools=[FakeToolExecution(approval_type="required")])
        create_approval_from_pause(db=db, run_response=rr)  # should not raise

    def test_silently_handles_generic_exception(self):
        db = MagicMock()
        db.create_approval.side_effect = RuntimeError("db down")
        rr = FakeRunResponse(tools=[FakeToolExecution(approval_type="required")])
        create_approval_from_pause(db=db, run_response=rr)  # should not raise

    def test_passes_user_id(self):
        db = MagicMock()
        rr = FakeRunResponse(tools=[FakeToolExecution(approval_type="required")])
        create_approval_from_pause(db=db, run_response=rr, user_id="user-1")
        data = db.create_approval.call_args[0][0]
        assert data["user_id"] == "user-1"

    def test_passes_team_context(self):
        db = MagicMock()
        rr = FakeRunResponse(tools=[FakeToolExecution(approval_type="required")])
        create_approval_from_pause(db=db, run_response=rr, team_id="t1", team_name="Team", user_id="u1")
        data = db.create_approval.call_args[0][0]
        assert data["team_id"] == "t1"
        assert data["source_type"] == "team"
        assert data["source_name"] == "Team"
        assert data["user_id"] == "u1"

    def test_returns_approval_id_on_success(self):
        db = MagicMock()
        tool = FakeToolExecution(tool_name="delete", approval_type="required")
        rr = FakeRunResponse(tools=[tool])
        result = create_approval_from_pause(db=db, run_response=rr, agent_id="a1", agent_name="Agent")
        assert result is not None
        assert isinstance(result, str)
        assert len(result) > 0
        # The returned ID must match what was passed to db.create_approval
        data = db.create_approval.call_args[0][0]
        assert result == data["id"]
        # approval_id must also be stamped on the tool itself
        assert tool.approval_id == result


# =============================================================================
# acreate_approval_from_pause (async)
# =============================================================================


class TestAsyncCreateApprovalFromPause:
    @pytest.mark.asyncio
    async def test_noop_when_db_is_none(self):
        await acreate_approval_from_pause(db=None, run_response=FakeRunResponse())

    @pytest.mark.asyncio
    async def test_calls_async_create_approval(self):
        db = MagicMock()
        db.create_approval = AsyncMock()
        rr = FakeRunResponse(tools=[FakeToolExecution(tool_name="t", approval_type="required")])
        await acreate_approval_from_pause(db=db, run_response=rr)
        db.create_approval.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_falls_back_to_sync_create_approval(self):
        db = MagicMock()
        db.create_approval = MagicMock()  # sync
        rr = FakeRunResponse(tools=[FakeToolExecution(approval_type="required")])
        await acreate_approval_from_pause(db=db, run_response=rr)
        db.create_approval.assert_called_once()

    @pytest.mark.asyncio
    async def test_noop_when_create_approval_missing(self):
        db = MagicMock(spec=[])  # no create_approval attribute
        rr = FakeRunResponse(tools=[FakeToolExecution(approval_type="required")])
        await acreate_approval_from_pause(db=db, run_response=rr)  # should not raise

    @pytest.mark.asyncio
    async def test_returns_approval_id_on_success(self):
        db = MagicMock()
        db.create_approval = AsyncMock()
        tool = FakeToolExecution(tool_name="delete", approval_type="required")
        rr = FakeRunResponse(tools=[tool])
        result = await acreate_approval_from_pause(db=db, run_response=rr, agent_id="a1", agent_name="Agent")
        assert result is not None
        assert isinstance(result, str)
        assert len(result) > 0
        data = db.create_approval.call_args[0][0]
        assert result == data["id"]
        # approval_id must also be stamped on the tool itself
        assert tool.approval_id == result


# =============================================================================
# create_audit_approval (sync)
# =============================================================================


class TestCreateAuditApproval:
    def test_noop_when_db_is_none(self):
        te = FakeToolExecution(tool_name="t")
        rr = FakeRunResponse()
        create_audit_approval(db=None, tool_execution=te, run_response=rr, status="approved")

    def test_creates_audit_record(self):
        db = MagicMock()
        te = FakeToolExecution(tool_name="send_email", tool_args={"to": "a@b.com"}, requires_confirmation=True)
        rr = FakeRunResponse()
        create_audit_approval(
            db=db, tool_execution=te, run_response=rr, status="approved", agent_id="a1", agent_name="Bot"
        )
        db.create_approval.assert_called_once()
        data = db.create_approval.call_args[0][0]
        assert data["approval_type"] == "audit"
        assert data["status"] == "approved"
        assert data["tool_name"] == "send_email"
        assert data["source_type"] == "agent"
        assert data["source_name"] == "Bot"

    def test_team_source_name_set(self):
        """Verify the fix: source_name is set to team_name when team_id is present."""
        db = MagicMock()
        te = FakeToolExecution(tool_name="t")
        rr = FakeRunResponse()
        create_audit_approval(
            db=db, tool_execution=te, run_response=rr, status="rejected", team_id="t1", team_name="TheTeam"
        )
        data = db.create_approval.call_args[0][0]
        assert data["source_type"] == "team"
        assert data["source_name"] == "TheTeam"

    def test_rejected_status(self):
        db = MagicMock()
        te = FakeToolExecution(tool_name="t")
        rr = FakeRunResponse()
        create_audit_approval(db=db, tool_execution=te, run_response=rr, status="rejected")
        data = db.create_approval.call_args[0][0]
        assert data["status"] == "rejected"

    def test_silently_handles_not_implemented(self):
        db = MagicMock()
        db.create_approval.side_effect = NotImplementedError
        te = FakeToolExecution(tool_name="t")
        rr = FakeRunResponse()
        create_audit_approval(db=db, tool_execution=te, run_response=rr, status="approved")


# =============================================================================
# acreate_audit_approval (async)
# =============================================================================


class TestAsyncCreateAuditApproval:
    @pytest.mark.asyncio
    async def test_creates_audit_record_async(self):
        db = MagicMock()
        db.create_approval = AsyncMock()
        te = FakeToolExecution(tool_name="send_email")
        rr = FakeRunResponse()
        await acreate_audit_approval(
            db=db, tool_execution=te, run_response=rr, status="approved", agent_id="a1", agent_name="Bot"
        )
        db.create_approval.assert_awaited_once()
        data = db.create_approval.call_args[0][0]
        assert data["approval_type"] == "audit"
        assert data["status"] == "approved"

    @pytest.mark.asyncio
    async def test_team_source_name_set(self):
        """Verify the fix: source_name is set to team_name when team_id is present."""
        db = MagicMock()
        db.create_approval = AsyncMock()
        te = FakeToolExecution(tool_name="t")
        rr = FakeRunResponse()
        await acreate_audit_approval(
            db=db, tool_execution=te, run_response=rr, status="approved", team_id="t1", team_name="TheTeam"
        )
        data = db.create_approval.call_args[0][0]
        assert data["source_type"] == "team"
        assert data["source_name"] == "TheTeam"

    @pytest.mark.asyncio
    async def test_falls_back_to_sync(self):
        db = MagicMock()
        db.create_approval = MagicMock()  # sync
        te = FakeToolExecution(tool_name="t")
        rr = FakeRunResponse()
        await acreate_audit_approval(db=db, tool_execution=te, run_response=rr, status="approved")
        db.create_approval.assert_called_once()


# =============================================================================
# _apply_approval_to_tools
# =============================================================================


class TestApplyApprovalToTools:
    def test_approved_sets_confirmed_true(self):
        t = FakeToolExecution(approval_type="required", requires_confirmation=True)
        _apply_approval_to_tools([t], "approved", None)
        assert t.confirmed is True

    def test_rejected_sets_confirmed_false(self):
        t = FakeToolExecution(approval_type="required", requires_confirmation=True)
        _apply_approval_to_tools([t], "rejected", None)
        assert t.confirmed is False

    def test_skips_tools_without_approval_type_required(self):
        t = FakeToolExecution(approval_type="audit", requires_confirmation=True)
        _apply_approval_to_tools([t], "approved", None)
        assert t.confirmed is None  # untouched

    def test_approved_applies_user_input_values(self):
        ufield = FakeUserInputField(name="reason")
        t = FakeToolExecution(
            approval_type="required",
            requires_user_input=True,
            user_input_schema=[ufield],
        )
        _apply_approval_to_tools([t], "approved", {"values": {"reason": "looks good"}})
        assert ufield.value == "looks good"

    def test_approved_applies_external_execution_result(self):
        t = FakeToolExecution(approval_type="required", external_execution_required=True)
        _apply_approval_to_tools([t], "approved", {"result": "done"})
        assert t.result == "done"

    def test_rejected_user_input_sets_confirmed_false(self):
        t = FakeToolExecution(approval_type="required", requires_user_input=True)
        _apply_approval_to_tools([t], "rejected", None)
        assert t.confirmed is False

    def test_rejected_external_execution_sets_confirmed_false(self):
        t = FakeToolExecution(approval_type="required", external_execution_required=True)
        _apply_approval_to_tools([t], "rejected", None)
        assert t.confirmed is False


# =============================================================================
# check_and_apply_approval_resolution (sync)
# =============================================================================


class TestCheckAndApplyApprovalResolution:
    def test_noop_when_db_is_none(self):
        rr = FakeRunResponse()
        check_and_apply_approval_resolution(db=None, run_id="r1", run_response=rr)

    def test_noop_when_no_tools_require_approval(self):
        db = MagicMock()
        rr = FakeRunResponse(tools=[FakeToolExecution(approval_type=None)])
        check_and_apply_approval_resolution(db=db, run_id="r1", run_response=rr)
        db.get_approvals.assert_not_called()

    def test_raises_when_no_approval_record_found(self):
        db = MagicMock()
        db.get_approvals.return_value = ([], 0)
        rr = FakeRunResponse(tools=[FakeToolExecution(approval_type="required")])
        with pytest.raises(RuntimeError, match="No approval record found"):
            check_and_apply_approval_resolution(db=db, run_id="r1", run_response=rr)

    def test_raises_when_approval_still_pending(self):
        db = MagicMock()
        db.get_approvals.return_value = ([{"status": "pending"}], 1)
        rr = FakeRunResponse(tools=[FakeToolExecution(approval_type="required")])
        with pytest.raises(RuntimeError, match="still pending"):
            check_and_apply_approval_resolution(db=db, run_id="r1", run_response=rr)

    def test_applies_approved_status(self):
        db = MagicMock()
        db.get_approvals.return_value = ([{"status": "approved", "resolution_data": None}], 1)
        t = FakeToolExecution(approval_type="required", requires_confirmation=True)
        rr = FakeRunResponse(tools=[t])
        check_and_apply_approval_resolution(db=db, run_id="r1", run_response=rr)
        assert t.confirmed is True

    def test_applies_rejected_status(self):
        db = MagicMock()
        db.get_approvals.return_value = ([{"status": "rejected", "resolution_data": None}], 1)
        t = FakeToolExecution(approval_type="required", requires_confirmation=True)
        rr = FakeRunResponse(tools=[t])
        check_and_apply_approval_resolution(db=db, run_id="r1", run_response=rr)
        assert t.confirmed is False

    def test_attaches_resolved_approval_to_metadata(self):
        approval = {"status": "approved", "resolution_data": None, "resolved_by": "alice", "resolved_at": 1700000000}
        db = MagicMock()
        db.get_approvals.return_value = ([approval], 1)
        rr = FakeRunResponse(tools=[FakeToolExecution(approval_type="required", requires_confirmation=True)])
        check_and_apply_approval_resolution(db=db, run_id="r1", run_response=rr)
        assert rr.metadata is not None
        assert rr.metadata["approval"] == approval

    def test_preserves_existing_metadata(self):
        approval = {"status": "approved", "resolution_data": None}
        db = MagicMock()
        db.get_approvals.return_value = ([approval], 1)
        rr = FakeRunResponse(
            tools=[FakeToolExecution(approval_type="required", requires_confirmation=True)],
            metadata={"existing": "value"},
        )
        check_and_apply_approval_resolution(db=db, run_id="r1", run_response=rr)
        assert rr.metadata["existing"] == "value"
        assert rr.metadata["approval"] == approval


# =============================================================================
# acheck_and_apply_approval_resolution (async)
# =============================================================================


class TestAsyncCheckAndApplyApprovalResolution:
    @pytest.mark.asyncio
    async def test_noop_when_db_is_none(self):
        rr = FakeRunResponse()
        await acheck_and_apply_approval_resolution(db=None, run_id="r1", run_response=rr)

    @pytest.mark.asyncio
    async def test_raises_when_no_approval_record_found(self):
        db = MagicMock()
        db.get_approvals = AsyncMock(return_value=([], 0))
        rr = FakeRunResponse(tools=[FakeToolExecution(approval_type="required")])
        with pytest.raises(RuntimeError, match="No approval record found"):
            await acheck_and_apply_approval_resolution(db=db, run_id="r1", run_response=rr)

    @pytest.mark.asyncio
    async def test_raises_when_approval_still_pending(self):
        db = MagicMock()
        db.get_approvals = AsyncMock(return_value=([{"status": "pending"}], 1))
        rr = FakeRunResponse(tools=[FakeToolExecution(approval_type="required")])
        with pytest.raises(RuntimeError, match="still pending"):
            await acheck_and_apply_approval_resolution(db=db, run_id="r1", run_response=rr)

    @pytest.mark.asyncio
    async def test_applies_approved_status_async(self):
        db = MagicMock()
        db.get_approvals = AsyncMock(return_value=([{"status": "approved", "resolution_data": None}], 1))
        t = FakeToolExecution(approval_type="required", requires_confirmation=True)
        rr = FakeRunResponse(tools=[t])
        await acheck_and_apply_approval_resolution(db=db, run_id="r1", run_response=rr)
        assert t.confirmed is True

    @pytest.mark.asyncio
    async def test_falls_back_to_sync_get_approvals(self):
        db = MagicMock()
        db.get_approvals = MagicMock(return_value=([{"status": "approved", "resolution_data": None}], 1))
        t = FakeToolExecution(approval_type="required", requires_confirmation=True)
        rr = FakeRunResponse(tools=[t])
        await acheck_and_apply_approval_resolution(db=db, run_id="r1", run_response=rr)
        assert t.confirmed is True

    @pytest.mark.asyncio
    async def test_attaches_resolved_approval_to_metadata(self):
        approval = {"status": "approved", "resolution_data": None, "resolved_by": "alice"}
        db = MagicMock()
        db.get_approvals = AsyncMock(return_value=([approval], 1))
        rr = FakeRunResponse(tools=[FakeToolExecution(approval_type="required", requires_confirmation=True)])
        await acheck_and_apply_approval_resolution(db=db, run_id="r1", run_response=rr)
        assert rr.metadata is not None
        assert rr.metadata["approval"] == approval


# =============================================================================
# Multiple pauses in one run: each approval-required call gets its own record
# =============================================================================


@dataclass
class FakeCallRequirement:
    tool_execution: Optional[FakeToolExecution] = None

    def to_dict(self) -> Dict[str, Any]:
        te = self.tool_execution
        return {"tool_execution": {"tool_call_id": te.tool_call_id, "tool_args": te.tool_args} if te else None}


@dataclass
class FakeMemberRequirement:
    tool_execution: Optional[FakeToolExecution] = None
    member_run_id: Optional[str] = None
    confirmation: Optional[bool] = None


def _second_pause_run_response():
    """A run at its second pause: call_1 was approved and executed under appr-1,
    call_2 was just raised. tools and requirements accumulate across pauses."""
    first = FakeToolExecution(
        tool_name="pay_invoice",
        tool_call_id="call_1",
        tool_args={"invoice": "INV-1"},
        approval_type="required",
        approval_id="appr-1",
        requires_confirmation=True,
        confirmed=True,
        result="PAID",
    )
    second = FakeToolExecution(
        tool_name="pay_invoice",
        tool_call_id="call_2",
        tool_args={"invoice": "INV-2"},
        approval_type="required",
        requires_confirmation=True,
    )
    rr = FakeRunResponse(
        tools=[first, second],
        requirements=[FakeCallRequirement(tool_execution=first), FakeCallRequirement(tool_execution=second)],
    )
    return rr, first, second


def _record_for(*tool_call_ids: str, status: str = "approved", record_id: str = "appr-1") -> Dict[str, Any]:
    return {
        "id": record_id,
        "status": status,
        "resolution_data": None,
        "requirements": [{"tool_execution": {"tool_call_id": tcid}} for tcid in tool_call_ids],
    }


class TestCreateApprovalOnLaterPause:
    def test_later_pause_creates_record_for_new_call_only(self):
        db = MagicMock()
        rr, first, second = _second_pause_run_response()
        result = create_approval_from_pause(db=db, run_response=rr, agent_id="a1")

        db.create_approval.assert_called_once()
        data = db.create_approval.call_args[0][0]
        assert result == data["id"] != "appr-1"
        assert second.approval_id == result
        assert first.approval_id == "appr-1"
        assert data["tool_args"] == {"invoice": "INV-2"}
        assert [r["tool_execution"]["tool_call_id"] for r in data["requirements"]] == ["call_2"]
        assert data["context"]["tool_names"] == ["pay_invoice"]

    def test_repeated_hook_on_same_pause_creates_no_duplicate(self):
        db = MagicMock()
        rr, _, second = _second_pause_run_response()
        first_id = create_approval_from_pause(db=db, run_response=rr)
        again = create_approval_from_pause(db=db, run_response=rr)
        assert again == first_id == second.approval_id
        db.create_approval.assert_called_once()

    @pytest.mark.asyncio
    async def test_later_pause_creates_record_for_new_call_only_async(self):
        db = MagicMock()
        db.create_approval = AsyncMock()
        rr, first, second = _second_pause_run_response()
        result = await acreate_approval_from_pause(db=db, run_response=rr, agent_id="a1")

        db.create_approval.assert_awaited_once()
        data = db.create_approval.call_args[0][0]
        assert result == data["id"] != "appr-1"
        assert second.approval_id == result
        assert first.approval_id == "appr-1"
        assert data["tool_args"] == {"invoice": "INV-2"}
        assert [r["tool_execution"]["tool_call_id"] for r in data["requirements"]] == ["call_2"]

    @pytest.mark.asyncio
    async def test_repeated_hook_on_same_pause_creates_no_duplicate_async(self):
        db = MagicMock()
        db.create_approval = AsyncMock()
        rr, _, second = _second_pause_run_response()
        first_id = await acreate_approval_from_pause(db=db, run_response=rr)
        again = await acreate_approval_from_pause(db=db, run_response=rr)
        assert again == first_id == second.approval_id
        db.create_approval.assert_awaited_once()


class TestRunLevelFallbackNeverCrossesToolCalls:
    def _unstamped_second_call(self):
        rr, first, second = _second_pause_run_response()
        db = MagicMock()
        db.get_approval.side_effect = lambda aid: _record_for("call_1") if aid == "appr-1" else None
        db.get_approvals.return_value = ([_record_for("call_1")], 1)
        return db, rr, second

    def test_record_for_another_call_does_not_resolve_unstamped_call(self):
        db, rr, second = self._unstamped_second_call()
        with pytest.raises(RuntimeError, match="No approval record found"):
            check_and_apply_approval_resolution(db=db, run_id="run-123", run_response=rr)
        assert second.confirmed is None

    @pytest.mark.asyncio
    async def test_record_for_another_call_does_not_resolve_unstamped_call_async(self):
        db, rr, second = self._unstamped_second_call()
        db.get_approvals = AsyncMock(return_value=([_record_for("call_1")], 1))
        with pytest.raises(RuntimeError, match="No approval record found"):
            await acheck_and_apply_approval_resolution(db=db, run_id="run-123", run_response=rr)
        assert second.confirmed is None

    def test_record_naming_the_call_still_resolves_it(self):
        db = MagicMock()
        db.get_approvals.return_value = ([_record_for("call_2")], 1)
        t = FakeToolExecution(tool_call_id="call_2", approval_type="required", requires_confirmation=True)
        check_and_apply_approval_resolution(db=db, run_id="r1", run_response=FakeRunResponse(tools=[t]))
        assert t.confirmed is True

    def test_stamped_record_gone_does_not_borrow_another_calls_record(self):
        db = MagicMock()
        db.get_approval.return_value = None
        db.get_approvals.return_value = ([_record_for("call_1")], 1)
        t = FakeToolExecution(
            tool_call_id="call_2", approval_type="required", approval_id="appr-gone", requires_confirmation=True
        )
        with pytest.raises(RuntimeError, match="No approval record found"):
            check_and_apply_approval_resolution(db=db, run_id="r1", run_response=FakeRunResponse(tools=[t]))
        assert t.confirmed is None

    @pytest.mark.asyncio
    async def test_stamped_record_gone_does_not_borrow_another_calls_record_async(self):
        db = MagicMock()
        db.get_approval = AsyncMock(return_value=None)
        db.get_approvals = AsyncMock(return_value=([_record_for("call_1")], 1))
        t = FakeToolExecution(
            tool_call_id="call_2", approval_type="required", approval_id="appr-gone", requires_confirmation=True
        )
        with pytest.raises(RuntimeError, match="No approval record found"):
            await acheck_and_apply_approval_resolution(db=db, run_id="r1", run_response=FakeRunResponse(tools=[t]))
        assert t.confirmed is None


class TestGateReviewRegressions:
    def _required_and_audit(self):
        required = FakeToolExecution(
            tool_name="pay_invoice",
            tool_call_id="call_1",
            approval_type="required",
            approval_id="appr-1",
            requires_confirmation=True,
        )
        audit = FakeToolExecution(
            tool_name="log_action", tool_call_id="call_2", approval_type="audit", requires_confirmation=True
        )
        return required, audit

    def test_audit_tool_does_not_need_a_required_record(self):
        db = MagicMock()
        db.get_approval.return_value = _record_for("call_1")
        db.get_approvals.return_value = ([_record_for("call_1")], 1)
        required, audit = self._required_and_audit()
        audit.confirmed = True
        check_and_apply_approval_resolution(db=db, run_id="r1", run_response=FakeRunResponse(tools=[required, audit]))
        assert required.confirmed is True
        assert audit.confirmed is True

    @pytest.mark.asyncio
    async def test_audit_tool_does_not_need_a_required_record_async(self):
        db = MagicMock()
        db.get_approval = AsyncMock(return_value=_record_for("call_1"))
        db.get_approvals = AsyncMock(return_value=([_record_for("call_1")], 1))
        required, audit = self._required_and_audit()
        audit.confirmed = True
        await acheck_and_apply_approval_resolution(
            db=db, run_id="r1", run_response=FakeRunResponse(tools=[required, audit])
        )
        assert required.confirmed is True
        assert audit.confirmed is True

    def _member_call_with_deleted_record(self):
        te = FakeToolExecution(
            tool_name="pay_invoice",
            tool_call_id="call_2",
            approval_type="required",
            approval_id="appr-deleted",
            requires_confirmation=True,
        )
        rr = FakeRunResponse(
            tools=[], requirements=[FakeMemberRequirement(tool_execution=te, member_run_id="member-run")]
        )
        return te, rr

    def test_member_record_for_another_call_does_not_resolve_deleted_record(self):
        te, rr = self._member_call_with_deleted_record()
        db = MagicMock()
        db.get_approval.return_value = None
        db.get_approvals.return_value = ([_record_for("call_1")], 1)
        with pytest.raises(RuntimeError, match="No approval record found"):
            check_and_apply_approval_resolution(db=db, run_id="team-run", run_response=rr)
        assert te.confirmed is None

    @pytest.mark.asyncio
    async def test_member_record_for_another_call_does_not_resolve_deleted_record_async(self):
        te, rr = self._member_call_with_deleted_record()
        db = MagicMock()
        db.get_approval = AsyncMock(return_value=None)
        db.get_approvals = AsyncMock(return_value=([_record_for("call_1")], 1))
        with pytest.raises(RuntimeError, match="No approval record found"):
            await acheck_and_apply_approval_resolution(db=db, run_id="team-run", run_response=rr)
        assert te.confirmed is None

    def test_member_record_naming_the_call_still_resolves_it(self):
        te, rr = self._member_call_with_deleted_record()
        db = MagicMock()
        db.get_approval.return_value = None
        db.get_approvals.return_value = ([_record_for("call_2", record_id="appr-reissued")], 1)
        check_and_apply_approval_resolution(db=db, run_id="team-run", run_response=rr)
        assert te.confirmed is True


@dataclass
class FakeResolvableRequirement(FakeCallRequirement):
    resolved: bool = False

    def is_resolved(self) -> bool:
        return self.resolved


class TestRecordCoversCurrentPause:
    def test_plain_hitl_tool_paused_alongside_is_listed(self):
        earlier_plain = FakeToolExecution(tool_name="notify", tool_call_id="call_0", requires_confirmation=True)
        gated = FakeToolExecution(
            tool_name="pay_invoice", tool_call_id="call_1", approval_type="required", requires_confirmation=True
        )
        plain = FakeToolExecution(tool_name="notify", tool_call_id="call_2", requires_confirmation=True)
        rr = FakeRunResponse(
            tools=[earlier_plain, gated, plain],
            requirements=[
                FakeResolvableRequirement(tool_execution=earlier_plain, resolved=True),
                FakeResolvableRequirement(tool_execution=gated),
                FakeResolvableRequirement(tool_execution=plain),
            ],
        )
        db = MagicMock()
        approval_id = create_approval_from_pause(db=db, run_response=rr)

        data = db.create_approval.call_args[0][0]
        assert [r["tool_execution"]["tool_call_id"] for r in data["requirements"]] == ["call_1", "call_2"]
        assert data["tool_name"] == "pay_invoice"
        assert data["context"]["tool_names"] == ["pay_invoice"]
        assert gated.approval_id == approval_id
        assert plain.approval_id is None


class TestAuditToolBeforeRequiredTool:
    def _run_response(self):
        audit = FakeToolExecution(
            tool_name="log_action",
            tool_call_id="call_1",
            approval_type="audit",
            requires_confirmation=True,
            confirmed=True,
            result="logged",
        )
        gated = FakeToolExecution(
            tool_name="pay_invoice",
            tool_call_id="call_2",
            tool_args={"invoice": "INV-1"},
            approval_type="required",
            requires_confirmation=True,
        )
        rr = FakeRunResponse(
            tools=[audit, gated],
            requirements=[FakeCallRequirement(tool_execution=audit), FakeCallRequirement(tool_execution=gated)],
        )
        return rr, audit, gated

    def test_has_approval_requirement_sees_required_tool_after_audit_tool(self):
        rr, _, _ = self._run_response()
        assert _has_approval_requirement(rr.tools, rr.requirements) is True

    def test_required_tool_after_audit_tool_gets_a_record(self):
        db = MagicMock()
        rr, audit, gated = self._run_response()
        approval_id = create_approval_from_pause(db=db, run_response=rr)

        db.create_approval.assert_called_once()
        data = db.create_approval.call_args[0][0]
        assert data["tool_name"] == "pay_invoice"
        assert data["tool_args"] == {"invoice": "INV-1"}
        assert gated.approval_id == approval_id
        assert audit.approval_id is None

    @pytest.mark.asyncio
    async def test_required_tool_after_audit_tool_gets_a_record_async(self):
        db = MagicMock()
        db.create_approval = AsyncMock()
        rr, audit, gated = self._run_response()
        approval_id = await acreate_approval_from_pause(db=db, run_response=rr)

        db.create_approval.assert_awaited_once()
        assert db.create_approval.call_args[0][0]["tool_name"] == "pay_invoice"
        assert gated.approval_id == approval_id
        assert audit.approval_id is None

    def test_audit_tool_paused_in_same_turn_is_not_stamped(self):
        db = MagicMock()
        audit = FakeToolExecution(tool_name="log_action", approval_type="audit", requires_confirmation=True)
        gated = FakeToolExecution(tool_name="pay_invoice", approval_type="required", requires_confirmation=True)
        approval_id = create_approval_from_pause(db=db, run_response=FakeRunResponse(tools=[gated, audit]))
        assert approval_id is not None
        assert gated.approval_id == approval_id
        assert audit.approval_id is None
