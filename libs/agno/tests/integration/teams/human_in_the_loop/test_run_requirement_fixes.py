"""Tests for RunRequirement property bug fixes.

Validates that needs_confirmation and needs_external_execution return
the correct values when tool_execution fields are set directly.
"""

from agno.models.response import ToolExecution
from agno.run.requirement import RunRequirement


def test_needs_confirmation_false_when_tool_confirmed_directly():
    """needs_confirmation should be False when tool_execution.confirmed is True."""
    tool_exec = ToolExecution(
        tool_call_id="test_1",
        tool_name="test_tool",
        tool_args={"arg": "value"},
        requires_confirmation=True,
        confirmed=True,
    )
    req = RunRequirement(tool_execution=tool_exec)

    # Even though requires_confirmation is True, confirmed=True means it no longer needs confirmation
    assert req.needs_confirmation is False


def test_needs_confirmation_true_when_not_confirmed():
    """needs_confirmation should be True when tool requires confirmation and is not yet confirmed."""
    tool_exec = ToolExecution(
        tool_call_id="test_2",
        tool_name="test_tool",
        tool_args={"arg": "value"},
        requires_confirmation=True,
    )
    req = RunRequirement(tool_execution=tool_exec)

    assert req.needs_confirmation is True


def test_needs_external_execution_false_when_result_set_directly():
    """needs_external_execution should be False when external_execution_result is already set."""
    tool_exec = ToolExecution(
        tool_call_id="test_3",
        tool_name="test_tool",
        tool_args={"arg": "value"},
        external_execution_required=True,
    )
    req = RunRequirement(tool_execution=tool_exec)
    req.external_execution_result = "some result"

    # Result is provided, so it no longer needs external execution
    assert req.needs_external_execution is False


def test_needs_external_execution_true_when_no_result():
    """needs_external_execution should be True when no result has been provided."""
    tool_exec = ToolExecution(
        tool_call_id="test_4",
        tool_name="test_tool",
        tool_args={"arg": "value"},
        external_execution_required=True,
    )
    req = RunRequirement(tool_execution=tool_exec)

    assert req.needs_external_execution is True


def test_is_resolved_after_direct_manipulation():
    """is_resolved should return True after directly setting confirmed/result."""
    # Confirmation case
    tool_exec = ToolExecution(
        tool_call_id="test_5",
        tool_name="test_tool",
        tool_args={"arg": "value"},
        requires_confirmation=True,
    )
    req = RunRequirement(tool_execution=tool_exec)
    assert not req.is_resolved()

    req.confirm()
    assert req.is_resolved()

    # External execution case
    tool_exec2 = ToolExecution(
        tool_call_id="test_6",
        tool_name="test_tool",
        tool_args={"arg": "value"},
        external_execution_required=True,
    )
    req2 = RunRequirement(tool_execution=tool_exec2)
    assert not req2.is_resolved()

    req2.set_external_execution_result("done")
    assert req2.is_resolved()


def test_member_context_fields_serialization():
    """Member context fields should round-trip through to_dict/from_dict."""
    tool_exec = ToolExecution(
        tool_call_id="test_7",
        tool_name="test_tool",
        tool_args={},
        requires_confirmation=True,
    )
    req = RunRequirement(tool_execution=tool_exec)
    req.member_agent_id = "agent_123"
    req.member_agent_name = "WeatherAgent"
    req.member_run_id = "run_456"

    data = req.to_dict()
    assert data["member_agent_id"] == "agent_123"
    assert data["member_agent_name"] == "WeatherAgent"
    assert data["member_run_id"] == "run_456"

    # Deserialize
    req2 = RunRequirement.from_dict(data)
    assert req2.member_agent_id == "agent_123"
    assert req2.member_agent_name == "WeatherAgent"
    assert req2.member_run_id == "run_456"


def test_reject_accepts_note_and_propagates_to_tool():
    """reject(note=...) should store the note on both requirement and tool execution."""
    tool_exec = ToolExecution(
        tool_call_id="test_8",
        tool_name="test_tool",
        tool_args={},
        requires_confirmation=True,
    )
    req = RunRequirement(tool_execution=tool_exec)
    req.reject(note="Denied by reviewer")

    assert req.confirmation is False
    assert req.confirmation_note == "Denied by reviewer"
    assert req.tool_execution is not None
    assert req.tool_execution.confirmed is False
    assert req.tool_execution.confirmation_note == "Denied by reviewer"
