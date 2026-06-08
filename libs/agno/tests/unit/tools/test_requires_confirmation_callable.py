"""Unit tests for callable `requires_confirmation` on @tool.

Covers the new feature where `@tool(requires_confirmation=callable)` allows
conditional Human-in-the-Loop based on tool arguments at runtime.

Also covers backward compatibility — existing bool / None usage must be
unchanged.
"""

from agno.tools import tool
from agno.tools.function import Function, FunctionCall, resolve_requires_confirmation


# Helper: build a FunctionCall from a Function + args, for testing the resolver.
def _make_fc(fn: Function, arguments: dict | None = None) -> FunctionCall:
    return FunctionCall(
        function=fn,
        arguments=arguments or {},
        call_id="test_call_id",
    )


# =============================================================================
# Test 1: Backward compat — `requires_confirmation=True` resolves to True
# =============================================================================


def test_static_true_resolves_to_true():
    """Existing API: bool True must always resolve to True."""

    @tool(requires_confirmation=True)
    def my_tool(x: int) -> int:
        return x

    fc = _make_fc(my_tool, {"x": 1})
    assert resolve_requires_confirmation(fc) is True


# =============================================================================
# Test 2: Backward compat — `requires_confirmation=False` resolves to False
# =============================================================================


def test_static_false_resolves_to_false():
    """Bool False must always resolve to False."""

    @tool(requires_confirmation=False)
    def my_tool(x: int) -> int:
        return x

    fc = _make_fc(my_tool, {"x": 1})
    assert resolve_requires_confirmation(fc) is False


# =============================================================================
# Test 3: Backward compat — `requires_confirmation=None` (default) is False
# =============================================================================


def test_none_default_resolves_to_false():
    """None (the default) must resolve to False — no opt-in confirmation."""

    @tool()
    def my_tool(x: int) -> int:
        return x

    fc = _make_fc(my_tool, {"x": 1})
    assert resolve_requires_confirmation(fc) is False


# =============================================================================
# Test 4: NEW — callable receives FunctionCall and returns True → confirms
# =============================================================================


def test_callable_returning_true_confirms():
    """Callable that returns True should cause confirmation."""

    def always_confirm(fc: FunctionCall) -> bool:
        return True

    @tool(requires_confirmation=always_confirm)
    def my_tool(x: int) -> int:
        return x

    fc = _make_fc(my_tool, {"x": 1})
    assert resolve_requires_confirmation(fc) is True


# =============================================================================
# Test 5: NEW — callable returning False → no confirmation
# =============================================================================


def test_callable_returning_false_skips_confirmation():
    """Callable that returns False should NOT cause confirmation."""

    def never_confirm(fc: FunctionCall) -> bool:
        return False

    @tool(requires_confirmation=never_confirm)
    def my_tool(x: int) -> int:
        return x

    fc = _make_fc(my_tool, {"x": 1})
    assert resolve_requires_confirmation(fc) is False


# =============================================================================
# Test 6: NEW — callable can inspect arguments for conditional logic
# =============================================================================


def test_callable_inspects_arguments():
    """The callable should receive the FunctionCall and be able to read
    its arguments — this is the whole point of the feature."""

    def confirm_if_risky_path(fc: FunctionCall) -> bool:
        path = fc.arguments.get("path", "")
        return path.startswith("/etc/") or path.startswith("/root/")

    @tool(requires_confirmation=confirm_if_risky_path)
    def delete_file(path: str) -> str:
        return f"deleted {path}"

    # Safe path — no confirmation
    fc_safe = _make_fc(delete_file, {"path": "/tmp/foo"})
    assert resolve_requires_confirmation(fc_safe) is False

    # Risky path — confirmation required
    fc_risky = _make_fc(delete_file, {"path": "/etc/passwd"})
    assert resolve_requires_confirmation(fc_risky) is True

    # Another risky path
    fc_risky2 = _make_fc(delete_file, {"path": "/root/.ssh/id_rsa"})
    assert resolve_requires_confirmation(fc_risky2) is True


# =============================================================================
# Test 7: NEW — lambda also works (most common usage)
# =============================================================================


def test_lambda_callable():
    """Lambda is the canonical short-form usage; must work identically."""

    @tool(requires_confirmation=lambda fc: fc.arguments.get("force", False))
    def risky_op(force: bool = False) -> str:
        return "done"

    assert resolve_requires_confirmation(_make_fc(risky_op, {"force": False})) is False
    assert resolve_requires_confirmation(_make_fc(risky_op, {"force": True})) is True


# =============================================================================
# Test 8: NEW — raising callable defaults to True (fail-safe)
# =============================================================================


def test_raising_callable_fail_safe():
    """If the callable raises, default to True (require confirmation).
    Better to over-prompt than to silently skip a safety check."""

    def buggy_check(fc: FunctionCall) -> bool:
        raise RuntimeError("oops")

    @tool(requires_confirmation=buggy_check)
    def my_tool(x: int) -> int:
        return x

    fc = _make_fc(my_tool, {"x": 1})
    # Should not raise, should default to True
    assert resolve_requires_confirmation(fc) is True


# =============================================================================
# Test 9: NEW — non-bool/non-callable unexpected value falls back to False with warning
# =============================================================================


def test_unexpected_type_falls_back(caplog):
    """Any other type (string, int, etc.) is unexpected — fall back to False
    with a logged warning. Don't crash."""

    @tool()
    def my_tool(x: int) -> int:
        return x

    # Force an unexpected value (bypassing type checker)
    my_tool.requires_confirmation = "not a bool or callable"  # type: ignore[assignment]

    fc = _make_fc(my_tool, {"x": 1})
    result = resolve_requires_confirmation(fc)
    assert result is False


# =============================================================================
# Test 10: NEW — callable that returns truthy non-bool is coerced via bool()
# =============================================================================


def test_truthy_non_bool_return_coerced():
    """Callable returning truthy values (1, "yes", non-empty list) coerces
    to True via bool(). Falsy values (0, "", None, []) coerce to False."""

    @tool(requires_confirmation=lambda fc: 1)  # truthy
    def t1(x: int) -> int:
        return x

    @tool(requires_confirmation=lambda fc: 0)  # falsy
    def t2(x: int) -> int:
        return x

    @tool(requires_confirmation=lambda fc: "yes")  # truthy
    def t3(x: int) -> int:
        return x

    @tool(requires_confirmation=lambda fc: [])  # falsy
    def t4(x: int) -> int:
        return x

    assert resolve_requires_confirmation(_make_fc(t1, {"x": 1})) is True
    assert resolve_requires_confirmation(_make_fc(t2, {"x": 1})) is False
    assert resolve_requires_confirmation(_make_fc(t3, {"x": 1})) is True
    assert resolve_requires_confirmation(_make_fc(t4, {"x": 1})) is False


# =============================================================================
# Test 11: NEW — Function.requires_confirmation field accepts callable type
# =============================================================================


def test_function_field_accepts_callable():
    """The Function pydantic model must accept a callable in the
    requires_confirmation field without validation error."""

    def my_check(fc: FunctionCall) -> bool:
        return False

    # Should not raise pydantic ValidationError
    fn = Function(
        name="test",
        requires_confirmation=my_check,
    )
    assert callable(fn.requires_confirmation)
