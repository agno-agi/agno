"""Unit tests for verified_tool and divergence_report (test 13).

Behaviour is driven through FunctionCall.execute / aexecute, the way an agent calls tools;
decoration-time checks and exceptions are asserted on the decorated function directly.
"""

import inspect
from typing import Optional

import pytest

from agno.tools.decorator import tool
from agno.tools.function import Function, FunctionCall, ToolResult
from agno.verify import DIVERGENCE_DIRECTIVE, Verdict, divergence_report, verified_tool

# ---------------------------------------------------------------------------
# Fixtures: a toy stateful environment with one hidden rule
# ---------------------------------------------------------------------------


def make_counter():
    state = {"n": 0}

    def step(amount: int, expect: Optional[str] = None) -> str:
        """Advance the counter.

        Args:
            amount: How much to add. Values above 5 are capped to 5.
            expect: Your prediction of the new counter value, as a string. Send an empty string
                when you have no prediction.
        """
        state["n"] += min(amount, 5)
        return str(state["n"])

    return step, state


def same(result, expect):
    text = result.content if isinstance(result, ToolResult) else result
    return text == expect


def execute(fn, **arguments):
    return FunctionCall(function=Function.from_callable(fn), arguments=arguments).execute()


async def aexecute(fn, **arguments):
    return await FunctionCall(function=Function.from_callable(fn), arguments=arguments).aexecute()


# ---------------------------------------------------------------------------
# Behaviour through the framework
# ---------------------------------------------------------------------------


def test_no_expect_is_passthrough():
    plain, _ = make_counter()
    decorated = verified_tool(same)(make_counter()[0])
    assert execute(plain, amount=3).result == execute(decorated, amount=3).result == "3"


def test_blank_expect_is_passthrough():
    decorated = verified_tool(same)(make_counter()[0])
    assert execute(decorated, amount=3, expect="").result == "3"
    decorated2 = verified_tool(same)(make_counter()[0])
    assert execute(decorated2, amount=3, expect="   ").result == "3"


def test_matching_prediction_is_unchanged():
    decorated = verified_tool(same)(make_counter()[0])
    assert execute(decorated, amount=3, expect="3").result == "3"


def test_mismatch_prefixes_divergence_block_on_str():
    decorated = verified_tool(same)(make_counter()[0])
    out = execute(decorated, amount=9, expect="9")
    assert out.status == "success"
    assert out.result.startswith("<divergence>")
    assert "expected: 9" in out.result and "actual: 5" in out.result
    assert DIVERGENCE_DIRECTIVE in out.result
    assert out.result.endswith("</divergence>\n5")


def test_mismatch_prefixes_tool_result_content():
    def probe(expect: Optional[str] = None) -> ToolResult:
        return ToolResult(content="real", metadata={"k": 1})

    decorated = verified_tool(same)(probe)
    out = execute(decorated, expect="fake")
    assert isinstance(out.result, ToolResult)
    assert out.result.content.startswith("<divergence>")
    assert out.result.content.endswith("\nreal")
    assert out.result.metadata == {"k": 1}


def test_tool_body_receives_expect_as_sent():
    seen = {}

    def probe(expect: Optional[str] = None) -> str:
        seen["expect"] = expect
        return "x"

    execute(verified_tool(same)(probe), expect="x")
    assert seen["expect"] == "x"


def test_non_str_expect_through_framework_is_schema_validation_failure():
    # The framework validates arguments against the tool's own signature (expect: Optional[str])
    # before the decorator runs, so a non-str prediction never reaches compare this way.
    decorated = verified_tool(same)(make_counter()[0])
    assert execute(decorated, amount=3, expect=3).status == "failure"


def test_non_str_expect_on_direct_call_is_compared_as_string():
    decorated = verified_tool(same)(make_counter()[0])
    assert decorated(amount=3, expect=3) == "3"
    assert decorated(amount=3, expect=7).startswith("<divergence>")


def test_compare_verdict_passed_decides_and_report_is_context():
    def judge(result, expect):
        return Verdict(passed=False, report="off by one")

    decorated = verified_tool(judge)(make_counter()[0])
    out = execute(decorated, amount=1, expect="1")
    assert "off by one" in out.result
    assert out.result.startswith("<divergence>")

    def lenient(result, expect):
        return Verdict(passed=True)

    assert execute(verified_tool(lenient)(make_counter()[0]), amount=1, expect="wrong").result == "1"


def test_compare_raising_is_a_mismatch_with_traceback():
    def broken(result, expect):
        raise ValueError("cannot compare")

    out = execute(verified_tool(broken)(make_counter()[0]), amount=1, expect="1")
    assert out.result.startswith("<divergence>")
    assert "compare raised ValueError: cannot compare" in out.result


def test_compare_returning_none_is_a_mismatch():
    def forgot_return(result, expect):
        result == expect  # noqa: B015

    out = execute(verified_tool(forgot_return)(make_counter()[0]), amount=1, expect="1")
    assert "compare returned NoneType" in out.result


def test_tool_exception_surfaces_as_tool_failure_without_decorator_frame():
    def explode(expect: Optional[str] = None) -> str:
        raise RuntimeError("tool broke")

    out = execute(verified_tool(same)(explode), expect="x")
    assert out.status == "failure"
    assert "tool broke" in str(out.error)
    assert "verified_tool" not in str(out.error)


def test_non_str_result_with_prediction_is_tool_failure_naming_verified_tool():
    def gives_dict(expect: Optional[str] = None) -> dict:
        return {"n": 1}

    out = execute(verified_tool(same)(gives_dict), expect="x")
    assert out.status == "failure"
    assert "verified_tool" in str(out.error)
    # Without a prediction the dict passes through.
    assert execute(verified_tool(same)(gives_dict)).result == {"n": 1}


@pytest.mark.asyncio
async def test_async_tool_through_aexecute():
    state = {"n": 0}

    async def astep(amount: int, expect: Optional[str] = None) -> str:
        """Async step."""
        state["n"] += min(amount, 5)
        return str(state["n"])

    decorated = verified_tool(same)(astep)
    assert inspect.iscoroutinefunction(decorated)
    ok = await aexecute(decorated, amount=2, expect="2")
    assert ok.result == "2"
    bad = await aexecute(decorated, amount=9, expect="11")
    assert bad.result.startswith("<divergence>") and bad.result.endswith("\n7")
    plain = await aexecute(decorated, amount=1)
    assert plain.result == "8"


def test_sync_tool_stays_sync():
    decorated = verified_tool(same)(make_counter()[0])
    assert not inspect.iscoroutinefunction(decorated)


def test_strict_schema_still_lists_expect():
    decorated = verified_tool(same)(make_counter()[0])
    fn = Function.from_callable(decorated, strict=True)
    fn.process_entrypoint(strict=True)
    params = fn.parameters["properties"]
    assert "expect" in params
    assert "Your prediction" in params["expect"]["description"]


def test_schema_shows_original_signature_and_docstring():
    decorated = verified_tool(same)(make_counter()[0])
    fn = Function.from_callable(decorated)
    fn.process_entrypoint()
    assert fn.name == "step"
    assert set(fn.parameters["properties"]) == {"amount", "expect"}


def test_stacks_beneath_tool_decorator():
    step, _ = make_counter()
    decorated = tool(verified_tool(same)(step))
    assert isinstance(decorated, Function)
    out = FunctionCall(function=decorated, arguments={"amount": 9, "expect": "9"}).execute()
    assert out.result.startswith("<divergence>")


# ---------------------------------------------------------------------------
# Decoration-time checks
# ---------------------------------------------------------------------------


def test_applying_above_tool_decorator_raises_ordering_error():
    step, _ = make_counter()
    with pytest.raises(TypeError, match="beneath @tool"):
        verified_tool(same)(tool(step))


def test_generator_tool_rejected():
    def gen(expect: Optional[str] = None):
        yield "a"

    async def agen(expect: Optional[str] = None):
        yield "a"

    with pytest.raises(TypeError, match="generator"):
        verified_tool(same)(gen)
    with pytest.raises(TypeError, match="generator"):
        verified_tool(same)(agen)


def test_missing_param_rejected():
    def no_expect(amount: int) -> str:
        return str(amount)

    with pytest.raises(TypeError, match="expect"):
        verified_tool(same)(no_expect)


def test_custom_param_name():
    def guess(amount: int, prediction: Optional[str] = None) -> str:
        return str(amount)

    decorated = verified_tool(same, param="prediction")(guess)
    assert decorated(amount=2, prediction="2") == "2"
    assert decorated(amount=2, prediction="3").startswith("<divergence>")


def test_direct_call_with_dict_result_and_prediction_raises():
    def gives_dict(expect: Optional[str] = None) -> dict:
        return {"n": 1}

    with pytest.raises(TypeError, match="str or ToolResult"):
        verified_tool(same)(gives_dict)(expect="x")


def test_direct_call_positional_prediction_is_detected():
    step, _ = make_counter()
    decorated = verified_tool(same)(step)
    assert decorated(9, "9").startswith("<divergence>")


# ---------------------------------------------------------------------------
# divergence_report
# ---------------------------------------------------------------------------


def test_divergence_report_shape_and_cap():
    block = divergence_report("a", "b", "ctx")
    assert block.splitlines() == [
        "<divergence>",
        "expected: a",
        "actual: b",
        "ctx",
        DIVERGENCE_DIRECTIVE,
        "</divergence>",
    ]
    assert len(divergence_report("a", "x" * 50000).encode("utf-8")) <= 6144
