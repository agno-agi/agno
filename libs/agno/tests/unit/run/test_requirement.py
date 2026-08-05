"""Unit tests for agno.run.requirement — RunRequirement serialization round-trips."""

from agno.models.response import ToolExecution
from agno.run.requirement import RunRequirement

# =============================================================================
# Helpers
# =============================================================================


def build_confirmation_requirement_dict(**overrides) -> dict:
    """A stored requirement dict for a tool call awaiting confirmation."""
    data = {
        "id": "req-1",
        "tool_execution": {
            "tool_name": "delete_file",
            "tool_args": {"path": "/tmp/x"},
            "tool_call_id": "call-1",
            "requires_confirmation": True,
        },
    }
    data.update(overrides)
    return data


# =============================================================================
# from_dict: top-level confirmation propagates to tool_execution
# =============================================================================


class TestFromDictConfirmationPropagation:
    def test_top_level_confirmation_true_reaches_tool_execution(self):
        """A bare top-level {"confirmation": true} must set tool_execution.confirmed."""
        req = RunRequirement.from_dict(build_confirmation_requirement_dict(confirmation=True))
        assert req.confirmation is True
        assert req.tool_execution is not None
        assert req.tool_execution.confirmed is True
        assert req.needs_confirmation is False

    def test_top_level_rejection_propagates_note(self):
        req = RunRequirement.from_dict(build_confirmation_requirement_dict(confirmation=False, confirmation_note="no"))
        assert req.confirmation is False
        assert req.tool_execution is not None
        assert req.tool_execution.confirmed is False
        assert req.tool_execution.confirmation_note == "no"

    def test_nested_confirmed_stays_authoritative(self):
        """An explicitly set tool_execution.confirmed wins over the top-level field."""
        data = build_confirmation_requirement_dict(confirmation=True)
        data["tool_execution"]["confirmed"] = False
        req = RunRequirement.from_dict(data)
        assert req.tool_execution is not None
        assert req.tool_execution.confirmed is False

    def test_no_confirmation_leaves_tool_execution_untouched(self):
        req = RunRequirement.from_dict(build_confirmation_requirement_dict())
        assert req.confirmation is None
        assert req.tool_execution is not None
        assert req.tool_execution.confirmed is None
        assert req.needs_confirmation is True

    def test_round_trip_preserves_confirm(self):
        requirement = RunRequirement(
            tool_execution=ToolExecution(
                tool_name="delete_file",
                tool_args={"path": "/tmp/x"},
                tool_call_id="call-1",
                requires_confirmation=True,
            )
        )
        requirement.confirm()
        restored = RunRequirement.from_dict(requirement.to_dict())
        assert restored.confirmation is True
        assert restored.tool_execution is not None
        assert restored.tool_execution.confirmed is True
        assert restored.needs_confirmation is False


# =============================================================================
# from_dict: external_execution_result propagates to tool_execution
# =============================================================================


class TestFromDictExternalExecutionResultPropagation:
    def test_top_level_result_reaches_tool_execution(self):
        data = {
            "id": "req-2",
            "tool_execution": {
                "tool_name": "run_query",
                "tool_args": {"sql": "select 1"},
                "tool_call_id": "call-2",
                "external_execution_required": True,
            },
            "external_execution_result": "1 row",
        }
        req = RunRequirement.from_dict(data)
        assert req.external_execution_result == "1 row"
        assert req.tool_execution is not None
        assert req.tool_execution.result == "1 row"
        assert req.needs_external_execution is False

    def test_nested_result_stays_authoritative(self):
        data = {
            "id": "req-3",
            "tool_execution": {
                "tool_name": "run_query",
                "tool_args": {"sql": "select 1"},
                "tool_call_id": "call-3",
                "external_execution_required": True,
                "result": "nested result",
            },
            "external_execution_result": "top-level result",
        }
        req = RunRequirement.from_dict(data)
        assert req.tool_execution is not None
        assert req.tool_execution.result == "nested result"
