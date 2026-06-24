"""Tests for RunRequirement fixes in the Team HITL implementation."""

import pytest

from agno.models.response import ToolExecution
from agno.run.requirement import RunRequirement
from agno.tools.function import UserInputField

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_tool_execution(**overrides) -> ToolExecution:
    """Create a ToolExecution with sensible defaults, overridden by kwargs."""
    defaults = dict(tool_name="do_something", tool_args={"x": 1})
    defaults.update(overrides)
    return ToolExecution(**defaults)


def _make_requirement(**te_overrides) -> RunRequirement:
    """Shortcut: build a RunRequirement wrapping a fresh ToolExecution."""
    return RunRequirement(tool_execution=_make_tool_execution(**te_overrides))


# ===========================================================================
# 1. needs_confirmation fix
# ===========================================================================


class TestNeedsConfirmation:
    """When tool_execution.confirmed is already set, needs_confirmation must be False."""

    def test_confirmed_true_returns_false(self):
        """If the tool was already confirmed (True), no further confirmation is needed."""
        req = _make_requirement(requires_confirmation=True, confirmed=True)
        assert req.needs_confirmation is False

    def test_confirmed_false_returns_false(self):
        """If the tool was explicitly rejected (False), no further confirmation is needed."""
        req = _make_requirement(requires_confirmation=True, confirmed=False)
        assert req.needs_confirmation is False

    def test_confirmed_none_returns_true(self):
        """If confirmed is None and requires_confirmation is True, confirmation is still needed."""
        req = _make_requirement(requires_confirmation=True, confirmed=None)
        assert req.needs_confirmation is True

    def test_no_requires_confirmation_returns_false(self):
        """If requires_confirmation is not set at all, needs_confirmation is False."""
        req = _make_requirement(requires_confirmation=False)
        assert req.needs_confirmation is False

    def test_requirement_level_confirmation_overrides(self):
        """If RunRequirement.confirmation is already set (e.g. True), needs_confirmation is False."""
        req = _make_requirement(requires_confirmation=True)
        req.confirmation = True
        assert req.needs_confirmation is False

    def test_requirement_level_confirmation_false_overrides(self):
        """If RunRequirement.confirmation is False, needs_confirmation is False."""
        req = _make_requirement(requires_confirmation=True)
        req.confirmation = False
        assert req.needs_confirmation is False


# ===========================================================================
# 2. needs_external_execution fix
# ===========================================================================


class TestNeedsExternalExecution:
    """When external_execution_result is set, needs_external_execution must be False."""

    def test_result_set_returns_false(self):
        req = _make_requirement(external_execution_required=True)
        req.external_execution_result = "done"
        assert req.needs_external_execution is False

    def test_result_none_returns_true(self):
        req = _make_requirement(external_execution_required=True)
        assert req.needs_external_execution is True

    def test_not_required_returns_false(self):
        req = _make_requirement(external_execution_required=False)
        assert req.needs_external_execution is False

    def test_empty_string_result_counts_as_set(self):
        """Even an empty string is not None so it should resolve the requirement."""
        req = _make_requirement(external_execution_required=True)
        req.external_execution_result = ""
        assert req.needs_external_execution is False


# ===========================================================================
# 3. provide_user_input
# ===========================================================================


class TestProvideUserInput:
    def test_sets_user_input_fields_on_tool_execution(self):
        te = _make_tool_execution(
            requires_user_input=True,
            user_input_schema=[
                UserInputField(name="name", field_type=str, description="Your name"),
                UserInputField(name="age", field_type=int, description="Your age"),
            ],
        )
        req = RunRequirement(tool_execution=te)
        # Provide partial input first
        req.provide_user_input({"name": "Alice"})
        assert req.user_input_schema[0].value == "Alice"
        assert req.user_input_schema[1].value is None
        # Not fully answered yet
        assert req.tool_execution.answered is not True

    def test_all_fields_marks_answered(self):
        te = _make_tool_execution(
            requires_user_input=True,
            user_input_schema=[
                UserInputField(name="name", field_type=str),
            ],
        )
        req = RunRequirement(tool_execution=te)
        req.provide_user_input({"name": "Alice"})
        assert req.user_input_schema[0].value == "Alice"
        assert req.tool_execution.answered is True

    def test_provide_user_input_raises_when_not_needed(self):
        req = _make_requirement(requires_user_input=False)
        with pytest.raises(ValueError, match="does not require user input"):
            req.provide_user_input({"name": "Alice"})


# ===========================================================================
# 4. reject(note=...) propagation
# ===========================================================================


class TestRejectNotePropagation:
    def test_reject_sets_confirmation_note_on_tool_execution(self):
        req = _make_requirement(requires_confirmation=True)
        req.reject(note="Not allowed")
        assert req.confirmation_note == "Not allowed"
        assert req.tool_execution.confirmation_note == "Not allowed"
        assert req.confirmation is False
        assert req.tool_execution.confirmed is False

    def test_reject_without_note(self):
        req = _make_requirement(requires_confirmation=True)
        req.reject()
        assert req.confirmation_note is None
        assert req.tool_execution.confirmation_note is None
        assert req.confirmation is False

    def test_reject_raises_when_not_needed(self):
        req = _make_requirement(requires_confirmation=False)
        with pytest.raises(ValueError, match="does not require confirmation"):
            req.reject(note="nope")


# ===========================================================================
# 5. Member context fields (serialisation round-trip)
# ===========================================================================


class TestMemberContextFields:
    def test_member_fields_are_set(self):
        req = _make_requirement()
        req.member_agent_id = "agent-123"
        req.member_agent_name = "Research Agent"
        req.member_run_id = "run-456"

        assert req.member_agent_id == "agent-123"
        assert req.member_agent_name == "Research Agent"
        assert req.member_run_id == "run-456"

    def test_member_fields_serialised_in_to_dict(self):
        req = _make_requirement()
        req.member_agent_id = "agent-123"
        req.member_agent_name = "Research Agent"
        req.member_run_id = "run-456"

        d = req.to_dict()
        assert d["member_agent_id"] == "agent-123"
        assert d["member_agent_name"] == "Research Agent"
        assert d["member_run_id"] == "run-456"

    def test_member_fields_absent_when_none(self):
        req = _make_requirement()
        d = req.to_dict()
        # None values are stripped by to_dict
        assert "member_agent_id" not in d
        assert "member_agent_name" not in d
        assert "member_run_id" not in d

    def test_member_fields_round_trip_via_from_dict(self):
        req = _make_requirement(requires_confirmation=True)
        req.member_agent_id = "agent-123"
        req.member_agent_name = "Research Agent"
        req.member_run_id = "run-456"

        d = req.to_dict()
        restored = RunRequirement.from_dict(d)

        assert restored.member_agent_id == "agent-123"
        assert restored.member_agent_name == "Research Agent"
        assert restored.member_run_id == "run-456"

    def test_from_dict_without_member_fields(self):
        req = _make_requirement()
        d = req.to_dict()
        restored = RunRequirement.from_dict(d)
        assert restored.member_agent_id is None
        assert restored.member_agent_name is None
        assert restored.member_run_id is None


# ===========================================================================
# 6. is_resolved() method
# ===========================================================================


class TestIsResolved:
    def test_confirmation_pending_not_resolved(self):
        req = _make_requirement(requires_confirmation=True)
        assert req.is_resolved() is False

    def test_confirmation_given_resolved(self):
        req = _make_requirement(requires_confirmation=True)
        req.confirm()
        assert req.is_resolved() is True

    def test_confirmation_rejected_resolved(self):
        req = _make_requirement(requires_confirmation=True)
        req.reject(note="No")
        assert req.is_resolved() is True

    def test_external_execution_pending_not_resolved(self):
        req = _make_requirement(external_execution_required=True)
        assert req.is_resolved() is False

    def test_external_execution_provided_resolved(self):
        req = _make_requirement(external_execution_required=True)
        req.set_external_execution_result("result data")
        assert req.is_resolved() is True

    def test_user_input_pending_not_resolved(self):
        te = _make_tool_execution(
            requires_user_input=True,
            user_input_schema=[UserInputField(name="city", field_type=str)],
        )
        req = RunRequirement(tool_execution=te)
        assert req.is_resolved() is False

    def test_user_input_provided_resolved(self):
        te = _make_tool_execution(
            requires_user_input=True,
            user_input_schema=[UserInputField(name="city", field_type=str)],
        )
        req = RunRequirement(tool_execution=te)
        req.provide_user_input({"city": "Paris"})
        assert req.is_resolved() is True

    def test_no_requirements_is_resolved(self):
        """A requirement with no HITL flags is trivially resolved."""
        req = _make_requirement()
        assert req.is_resolved() is True

    def test_multiple_unresolved_flags(self):
        """If both confirmation and external execution are needed, not resolved until both done."""
        te = _make_tool_execution(requires_confirmation=True, external_execution_required=True)
        req = RunRequirement(tool_execution=te)
        assert req.is_resolved() is False

        # Resolve confirmation only
        req.confirm()
        assert req.is_resolved() is False

        # Now resolve external execution
        req.set_external_execution_result("done")
        assert req.is_resolved() is True
