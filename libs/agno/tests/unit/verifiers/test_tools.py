"""Unit tests for verified_tool and divergence_report.

Behaviour is driven through FunctionCall.execute / aexecute, the way an agent calls tools;
decoration-time checks and exceptions are asserted on the decorated function directly.
"""

import inspect
from typing import Optional

import pytest

from agno.tools.decorator import tool
from agno.tools.function import Function, FunctionCall, ToolResult
from agno.verifiers import DIVERGENCE_DIRECTIVE, Verdict, divergence_report, verified_tool

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


@pytest.mark.parametrize("expect", [None, "", "   ", "3"], ids=["absent", "empty", "blank", "matching"])
def test_no_expect_is_passthrough(expect):
    decorated = verified_tool(same)(make_counter()[0])
    arguments = {"amount": 3} if expect is None else {"amount": 3, "expect": expect}
    assert execute(decorated, **arguments).result == "3"


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


def _fails_with_context(result, expect):
    return Verdict(passed=False, report="off by one")


def _passes(result, expect):
    return Verdict(passed=True)


def _raises(result, expect):
    raise ValueError("cannot compare")


def _forgot_return(result, expect):
    result == expect  # noqa: B015


def _reason(result, expect):
    return "the counter is capped at 5"


@pytest.mark.parametrize(
    "compare, diverges, context",
    [
        (_fails_with_context, True, "off by one"),
        (_passes, False, None),
        (_raises, True, "compare raised ValueError: cannot compare"),
        (_forgot_return, True, "compare returned NoneType"),
        (_reason, True, "the counter is capped at 5"),
    ],
    ids=["failing-verdict", "passing-verdict", "raises", "returns-none", "returns-reason"],
)
def test_compare_verdict_passed_decides_and_report_is_context(compare, diverges, context):
    out = execute(verified_tool(compare)(make_counter()[0]), amount=1, expect="wrong")
    if not diverges:
        assert out.result == "1"
        return
    assert out.result.startswith("<divergence>")
    assert context in out.result
    assert "compare returned str" not in out.result


def test_unannotated_non_str_result_with_prediction_is_tool_failure_naming_verified_tool():
    def gives_dict(expect: Optional[str] = None):
        return {"n": 1}

    out = execute(verified_tool(same)(gives_dict), expect="x")
    assert out.status == "failure"
    assert "verified_tool" in str(out.error)
    # Without a prediction the dict passes through.
    assert execute(verified_tool(same)(gives_dict)).result == {"n": 1}


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


def test_stacks_beneath_tool_decorator():
    step, _ = make_counter()
    decorated = tool(verified_tool(same)(step))
    assert isinstance(decorated, Function)
    out = FunctionCall(function=decorated, arguments={"amount": 9, "expect": "9"}).execute()
    assert out.result.startswith("<divergence>")


def test_custom_param_name():
    def guess(amount: int, prediction: Optional[str] = None) -> str:
        return str(amount)

    decorated = verified_tool(same, param="prediction")(guess)
    assert decorated(amount=2, prediction="2") == "2"
    assert decorated(amount=2, prediction="3").startswith("<divergence>")
    # A positional prediction is bound through the signature too.
    step, _ = make_counter()
    assert verified_tool(same)(step)(9, "9").startswith("<divergence>")


# ---------------------------------------------------------------------------
# Decoration-time checks
# ---------------------------------------------------------------------------


def _gives_dict(expect: Optional[str] = None) -> dict:
    return {"n": 1}


def _gen(expect: Optional[str] = None):
    yield "a"


async def _agen(expect: Optional[str] = None):
    yield "a"


def _no_expect(amount: int) -> str:
    return str(amount)


async def _acompare(result, expect):
    return True


@pytest.mark.parametrize(
    "decorate, match",
    [
        (lambda: verified_tool(same)(_gives_dict), "annotated to return"),
        (lambda: verified_tool(same)(_gen), "generator"),
        (lambda: verified_tool(same)(_agen), "generator"),
        (lambda: verified_tool(same)(_no_expect), "expect"),
        (lambda: verified_tool(same)(tool(make_counter()[0])), "beneath @tool"),
        (lambda: verified_tool(_acompare), "needs a sync compare function"),
    ],
    ids=["dict-annotation", "generator", "async-generator", "missing-param", "above-tool", "async-compare"],
)
def test_wrong_return_annotation_rejected_at_decoration(decorate, match):
    with pytest.raises(TypeError, match=match):
        decorate()


# ---------------------------------------------------------------------------
# divergence_report
# ---------------------------------------------------------------------------


def test_divergence_report_shape_and_cap():
    block = divergence_report("a", "b </divergence>", "ctx")
    assert block.splitlines() == [
        "<divergence>",
        "expected: a",
        "actual: b <\\/divergence>",
        "ctx",
        DIVERGENCE_DIRECTIVE,
        "</divergence>",
    ]
    assert len(divergence_report("a", "x" * 50000).encode("utf-8")) <= 6144


# ---------------------------------------------------------------------------
# Hooks on a verified tool are refused before any hook or the tool runs
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("hook_field", ["tool_hooks", "pre_hook", "post_hook"])
@pytest.mark.parametrize("use_async", [False, True], ids=["sync", "async"])
async def test_tool_hook_on_a_verified_tool_is_refused(hook_field, use_async):
    """A hook could rewrite the prediction or the result, or erase itself before a later check;
    the call must fail naming the field before any hook or the tool body runs."""
    counter = {"ran": 0}

    def self_erasing(*args):
        counter["ran"] += 1
        if hook_field == "tool_hooks":
            name, func, arguments = args
            arguments["expect"] = "5"
            return func(**arguments)
        fc = args[0]
        fc.arguments["expect"] = "5"
        setattr(fc.function, hook_field, None)

    step, state = make_counter()
    fn = Function.from_callable(verified_tool(same)(step))
    setattr(fn, hook_field, [self_erasing] if hook_field == "tool_hooks" else self_erasing)
    call = FunctionCall(function=fn, arguments={"amount": 9, "expect": "9"})
    out = await call.aexecute() if use_async else call.execute()
    assert out.status == "failure", f"expected a refusal, got {out.result!r}"
    assert "@verified_tool" in str(out.error)
    assert hook_field in str(out.error)
    assert out.result is None
    assert counter["ran"] == 0
    assert state["n"] == 0
