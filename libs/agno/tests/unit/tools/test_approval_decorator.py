"""Unit tests for the @approval decorator and its interaction with @tool."""

import pytest

from agno.approval import ApprovalType, approval
from agno.tools import Toolkit, tool
from agno.tools.function import Function

# =============================================================================
# Test 1: @approval on top of @tool sets approval_type and requires_confirmation
# =============================================================================


def test_approval_on_top_of_tool():
    """When @approval is stacked on top of @tool(), it receives the Function
    object and sets approval_type='required' with requires_confirmation=True."""

    @approval
    @tool()
    def delete_file(path: str) -> str:
        """Delete a file at the given path."""
        return f"deleted {path}"

    assert isinstance(delete_file, Function)
    assert delete_file.approval_type == "required"
    assert delete_file.requires_confirmation is True


# =============================================================================
# Test 2: @approval below @tool (sentinel path) produces same result
# =============================================================================


def test_approval_below_tool():
    """When @approval is below @tool(), the sentinel attribute is detected
    by @tool and the resulting Function has approval_type='required' and
    requires_confirmation=True."""

    @tool()
    @approval
    def delete_file(path: str) -> str:
        """Delete a file at the given path."""
        return f"deleted {path}"

    assert isinstance(delete_file, Function)
    assert delete_file.approval_type == "required"
    assert delete_file.requires_confirmation is True


# =============================================================================
# Test 3: @approval() with parens works in both orderings
# =============================================================================


def test_approval_with_parens():
    """@approval() (with empty parens) should work identically to bare @approval
    in both decorator orderings."""

    # approval() on top of tool()
    @approval()
    @tool()
    def func_a(x: int) -> int:
        """Function A."""
        return x

    assert isinstance(func_a, Function)
    assert func_a.approval_type == "required"
    assert func_a.requires_confirmation is True

    # tool() on top of approval()
    @tool()
    @approval()
    def func_b(x: int) -> int:
        """Function B."""
        return x

    assert isinstance(func_b, Function)
    assert func_b.approval_type == "required"
    assert func_b.requires_confirmation is True


# =============================================================================
# Test 4: @approval(type="audit") on @tool(requires_confirmation=True)
# =============================================================================


def test_approval_audit_with_confirmation():
    """@approval(type='audit') combined with @tool(requires_confirmation=True)
    sets approval_type='audit' without raising, since a HITL flag is present."""

    # approval on top
    @approval(type="audit")
    @tool(requires_confirmation=True)
    def sensitive_action(data: str) -> str:
        """Perform a sensitive action."""
        return data

    assert isinstance(sensitive_action, Function)
    assert sensitive_action.approval_type == "audit"
    assert sensitive_action.requires_confirmation is True

    # approval below
    @tool(requires_confirmation=True)
    @approval(type="audit")
    def sensitive_action_2(data: str) -> str:
        """Perform a sensitive action."""
        return data

    assert isinstance(sensitive_action_2, Function)
    assert sensitive_action_2.approval_type == "audit"
    assert sensitive_action_2.requires_confirmation is True


# =============================================================================
# Test 5: @approval(type=ApprovalType.audit) with enum works
# =============================================================================


def test_approval_enum_type():
    """Passing an ApprovalType enum value works the same as passing a string."""

    @approval(type=ApprovalType.audit)
    @tool(requires_confirmation=True)
    def audited_func(x: int) -> int:
        """Audited function."""
        return x

    assert isinstance(audited_func, Function)
    assert audited_func.approval_type == "audit"
    assert audited_func.requires_confirmation is True


# =============================================================================
# Test 6: @approval + @tool(requires_user_input=True) does NOT auto-set
#          requires_confirmation
# =============================================================================


def test_approval_with_user_input():
    """When @tool already has requires_user_input=True, @approval should NOT
    auto-set requires_confirmation, since a HITL flag is already present."""

    # approval on top
    @approval
    @tool(requires_user_input=True)
    def ask_user(question: str) -> str:
        """Ask the user a question."""
        return question

    assert isinstance(ask_user, Function)
    assert ask_user.approval_type == "required"
    assert ask_user.requires_user_input is True
    # requires_confirmation should not have been auto-set
    assert ask_user.requires_confirmation is not True

    # approval below
    @tool(requires_user_input=True)
    @approval
    def ask_user_2(question: str) -> str:
        """Ask the user a question."""
        return question

    assert isinstance(ask_user_2, Function)
    assert ask_user_2.approval_type == "required"
    assert ask_user_2.requires_user_input is True
    assert ask_user_2.requires_confirmation is not True


# =============================================================================
# Test 7: @approval + @tool(external_execution=True) does NOT auto-set
#          requires_confirmation
# =============================================================================


def test_approval_with_external_execution():
    """When @tool has external_execution=True, @approval should NOT auto-set
    requires_confirmation, since a HITL flag is already present."""

    # approval on top
    @approval
    @tool(external_execution=True)
    def run_external(cmd: str) -> str:
        """Run an external command."""
        return cmd

    assert isinstance(run_external, Function)
    assert run_external.approval_type == "required"
    assert run_external.external_execution is True
    assert run_external.requires_confirmation is not True

    # approval below
    @tool(external_execution=True)
    @approval
    def run_external_2(cmd: str) -> str:
        """Run an external command."""
        return cmd

    assert isinstance(run_external_2, Function)
    assert run_external_2.approval_type == "required"
    assert run_external_2.external_execution is True
    assert run_external_2.requires_confirmation is not True


# =============================================================================
# Test 8: @tool(requires_approval=True) raises ValueError
# =============================================================================


def test_old_requires_approval_raises():
    """The old requires_approval kwarg has been removed from VALID_KWARGS,
    so passing it should raise a ValueError."""

    with pytest.raises(ValueError, match="Invalid tool configuration arguments"):

        @tool(requires_approval=True)
        def old_style(x: int) -> int:
            """Old style approval."""
            return x


# =============================================================================
# Test 9: @approval(type="audit") + @tool() (no HITL flag) raises ValueError
# =============================================================================


def test_audit_without_hitl_raises():
    """@approval(type='audit') requires at least one HITL flag to be set.
    Without any, it should raise a ValueError."""

    # approval on top of tool (no HITL flags)
    with pytest.raises(ValueError, match="requires at least one HITL flag"):

        @approval(type="audit")
        @tool()
        def bare_audit(x: int) -> int:
            """Audit without HITL."""
            return x

    # approval below tool (no HITL flags)
    with pytest.raises(ValueError, match="requires at least one HITL flag"):

        @tool()
        @approval(type="audit")
        def bare_audit_2(x: int) -> int:
            """Audit without HITL."""
            return x


# =============================================================================
# Test 10: @approval @tool(...) inside a Toolkit preserves approval_type
# =============================================================================


def test_toolkit_propagation():
    """When a @approval + @tool decorated method is registered inside a Toolkit,
    the approval_type should be preserved on the registered Function."""

    class MyToolkit(Toolkit):
        def __init__(self):
            super().__init__(name="approval_toolkit", tools=[self.dangerous_action])

        @approval
        @tool()
        def dangerous_action(self, target: str) -> str:
            """Perform a dangerous action."""
            return f"done: {target}"

    toolkit = MyToolkit()

    assert len(toolkit.functions) == 1
    assert "dangerous_action" in toolkit.functions

    func = toolkit.functions["dangerous_action"]
    assert isinstance(func, Function)
    assert func.approval_type == "required"
    assert func.requires_confirmation is True
