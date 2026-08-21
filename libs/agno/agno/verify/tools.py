"""verified_tool: a tool call that carries a falsifiable prediction.

The tool declares an optional `expect` parameter so the model-facing schema is honest. When
the model fills it, the decorator runs the tool, compares the result against the prediction,
and on mismatch prefixes the result with a divergence block. It verifies one call: it cannot
stop other calls the model issued in the same turn, so cookbooks that want a bound plan ask
for one predicted step per turn.
"""

import functools
import inspect
import re
from typing import Any, Callable, Union

from agno.verify.types import REPORT_CAP_BYTES, Verdict, cap_text
from agno.verify.verifiers import _traceback_tail

DIVERGENCE_DIRECTIVE = (
    "Your prediction for this call was wrong. Do not continue the plan that produced it; "
    "re-derive the next step from the actual result below."
)


_CLOSE_TAG = re.compile(r"<\s*/\s*divergence\s*>", re.IGNORECASE)


def _escape(text: str) -> str:
    return _CLOSE_TAG.sub("<\\/divergence>", text)


def divergence_report(expected: str, actual: str, context: str = "") -> str:
    """The standard block: expected, actual, optional context, and the directive. Capped. The
    tool's own output cannot close the block."""
    lines = ["<divergence>", f"expected: {_escape(expected)}", f"actual: {_escape(actual)}"]
    if context:
        lines.append(_escape(context))
    lines.extend([DIVERGENCE_DIRECTIVE, "</divergence>"])
    return cap_text("\n".join(lines), REPORT_CAP_BYTES)


def _prediction_present(value: Any) -> bool:
    return value is not None and str(value).strip() != ""


def _result_text(result: Any) -> str:
    from agno.tools.function import ToolResult

    if isinstance(result, ToolResult):
        return result.content
    if isinstance(result, str):
        return result
    raise TypeError(
        f"verified_tool requires the tool to return str or ToolResult when a prediction is present; "
        f"got {type(result).__name__}"
    )


def _with_prefix(result: Any, block: str) -> Any:
    from agno.tools.function import ToolResult

    if isinstance(result, ToolResult):
        return result.model_copy(update={"content": f"{block}\n{result.content}"})
    return f"{block}\n{result}"


def _apply(compare: Callable[[Any, str], Union[bool, Verdict]], result: Any, expect: str) -> Any:
    text = _result_text(result)
    try:
        outcome = compare(result, expect)
    except Exception as exc:
        outcome = Verdict(passed=False, report=f"compare raised {type(exc).__name__}: {exc}\n{_traceback_tail(exc)}")
    if outcome is True:
        return result
    if isinstance(outcome, Verdict):
        if outcome.passed is True:
            return result
        context = outcome.report
    elif outcome is False:
        context = ""
    else:
        context = f"compare returned {type(outcome).__name__}; return True, False, or a Verdict"
    block = divergence_report(expect, cap_text(text, REPORT_CAP_BYTES // 2), context)
    return _with_prefix(result, block)


_PROVABLY_WRONG_RETURNS = (dict, list, tuple, set, frozenset, int, float, bool, bytes)


def _check_return_annotation(fn: Callable) -> None:
    try:
        import typing

        hints = typing.get_type_hints(fn)
    except Exception:
        return
    annotation = hints.get("return")
    if annotation is None:
        return
    origin = getattr(annotation, "__origin__", annotation)
    if isinstance(origin, type) and origin is not str and issubclass(origin, _PROVABLY_WRONG_RETURNS):
        raise TypeError(
            f"verified_tool requires the tool to return str or ToolResult; "
            f"{getattr(fn, '__name__', fn)!r} is annotated to return {annotation!r}"
        )


def verified_tool(compare: Callable[[Any, str], Union[bool, Verdict]], param: str = "expect") -> Callable:
    """Decorate a tool function that declares an optional `expect: Optional[str] = None`.

    Apply it to the plain function, beneath `@tool` when both are used. A prediction is
    present when `expect` is not None and not blank; then `compare(result, str(expect))`
    runs after the tool and a mismatch (False, a failing Verdict, an exception, or any other
    return) prefixes the result with a divergence block. Without a prediction the call is
    passed through unchanged. The tool body receives `expect` exactly as sent. The wrapper
    matches the tool's kind (sync or async); generator tools are rejected. Tool exceptions
    propagate untouched.

    The block is addressed to the model: do not combine with `stop_after_tool_call` or a
    `show_result` tool used as the final answer, which hand the tool output to the user. With
    `cache_results=True` a cached call is not re-compared, so a divergence recorded once is
    replayed for the same arguments and prediction; leave caching off for stateful tools.

    Hooks outrank the check. `tool_hooks` wrap the decorated function, so a hook that
    rewrites an argument in place changes the prediction the comparison uses, a hook that
    rewrites the result replaces what the model sees after the comparison ran, and a hook
    that answers without calling the wrapped function skips the comparison entirely; the
    same holds for a `pre_hook` rewriting `fc.arguments`. Keep argument- and
    result-transforming hooks off a verified tool.
    """

    def decorate(fn: Callable) -> Callable:
        from agno.tools.function import Function
        from agno.tools.toolkit import Toolkit

        if isinstance(fn, (Function, Toolkit)):
            raise TypeError("verified_tool wraps the function; apply it beneath @tool")
        if inspect.isgeneratorfunction(fn) or inspect.isasyncgenfunction(fn):
            raise TypeError(
                "verified_tool cannot wrap a generator tool: a streamed result has no single value to compare"
            )
        sig = inspect.signature(fn)
        if param not in sig.parameters:
            raise TypeError(f"verified_tool: {getattr(fn, '__name__', fn)!r} has no parameter named {param!r}")

        # Best-effort early failure for a return type the runtime rule will reject: a tool
        # annotated to return a dict/list/tuple/set/number decorates fine but would surface
        # a TypeError as a tool error mid-run the first time the model sends a prediction.
        _check_return_annotation(fn)

        def prediction(args: tuple, kwargs: dict) -> Any:
            try:
                return sig.bind_partial(*args, **kwargs).arguments.get(param)
            except TypeError:
                return kwargs.get(param)

        if inspect.iscoroutinefunction(fn):

            @functools.wraps(fn)
            async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
                expect = prediction(args, kwargs)
                result = await fn(*args, **kwargs)
                if not _prediction_present(expect):
                    return result
                return _apply(compare, result, str(expect))

            return async_wrapper

        @functools.wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            expect = prediction(args, kwargs)
            result = fn(*args, **kwargs)
            if not _prediction_present(expect):
                return result
            return _apply(compare, result, str(expect))

        return wrapper

    return decorate


__all__ = ["DIVERGENCE_DIRECTIVE", "divergence_report", "verified_tool"]
