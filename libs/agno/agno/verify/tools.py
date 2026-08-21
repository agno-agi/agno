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
from typing import Any, Callable, Optional, TypeVar, Union, cast

from agno.verify.types import REPORT_CAP_BYTES, Verdict, cap_text
from agno.verify.verifiers import _traceback_tail

# The decorated tool keeps its own type. This package ships py.typed, so returning a bare
# Callable would erase the signature for every downstream caller: a wrong argument type and a
# wrong assignment from the result would both type-check clean.
F = TypeVar("F", bound=Callable[..., Any])

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

    if result is None:
        # `Optional[str]` is a legal annotation the decorator accepts, so a None result must
        # compare as an empty result rather than fail the call it was meant to check.
        return ""
    if isinstance(result, ToolResult):
        return result.content or ""
    if isinstance(result, str):
        return result
    raise TypeError(
        f"verified_tool requires the tool to return str or ToolResult when a prediction is present; "
        f"got {type(result).__name__}"
    )


def _with_prefix(result: Any, block: str) -> Any:
    from agno.tools.function import ToolResult

    if isinstance(result, ToolResult):
        content = f"{block}\n{result.content}" if result.content else block
        return result.model_copy(update={"content": content})
    if result is None:
        # The tool returned nothing; "None" is not evidence, the block alone is.
        return block
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
    elif isinstance(outcome, str):
        context = outcome  # a reason for the mismatch, the same shape a verifier may return
    else:
        context = f"compare returned {type(outcome).__name__}; return True, False, a str, or a Verdict"
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


def verified_tool(compare: Callable[[Any, str], Union[bool, Verdict]], param: str = "expect") -> Callable[[F], F]:
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

    Hooks are refused, not tolerated. `tool_hooks` wrap the decorated function, so a hook can
    rewrite the prediction, replace the result the comparison produced, or answer without
    calling the wrapped function at all — in every case the prediction would look checked when
    it was not. A tool that is both decorated and hooked therefore fails its call with an
    explanation rather than passing quietly. Check the result inside the hook instead, or keep
    the hooks off this tool.
    """

    if inspect.iscoroutinefunction(compare):
        raise TypeError(
            "verified_tool runs compare synchronously after the tool returns; an async compare "
            "would never be awaited and every call would read as a divergence. Make it a plain "
            "function, or await inside the tool and compare the resolved value."
        )

    def decorate(fn: F) -> F:
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

            async_wrapper.__agno_verified_tool__ = True  # type: ignore[attr-defined]
            return cast(F, async_wrapper)

        @functools.wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            expect = prediction(args, kwargs)
            result = fn(*args, **kwargs)
            if not _prediction_present(expect):
                return result
            return _apply(compare, result, str(expect))

        wrapper.__agno_verified_tool__ = True  # type: ignore[attr-defined]
        return cast(F, wrapper)

    return decorate


def is_verified_tool(fn: Any) -> bool:
    """True when `fn` is a callable produced by `verified_tool`.

    The marker is what lets the tool-execution path refuse to run a verified tool behind hooks
    that can silently defeat its comparison.
    """
    return bool(getattr(fn, "__agno_verified_tool__", False))


def hook_conflict(function: Any) -> Optional[str]:
    """The reason a hook-bearing Function may not wrap a verified tool, or None.

    A hook that rewrites the result replaces the divergence block after the comparison ran, a
    hook that rewrites `expect` in place changes the prediction being checked, and a hook that
    answers without calling the wrapped function skips the comparison altogether. Each of those
    turns a falsifiable prediction back into an unchecked claim, which is the one thing this
    decorator exists to prevent — so the call fails loudly rather than passing quietly.
    """
    if not is_verified_tool(getattr(function, "entrypoint", None)):
        return None
    offenders = []
    if getattr(function, "tool_hooks", None):
        offenders.append("tool_hooks")
    if getattr(function, "pre_hook", None):
        offenders.append("pre_hook")
    if getattr(function, "post_hook", None):
        offenders.append("post_hook")
    if not offenders:
        return None
    return (
        f"{getattr(function, 'name', 'tool')!r} is decorated with @verified_tool and also has "
        f"{' and '.join(offenders)}. Hooks wrap the decorated function, so they can rewrite the "
        "prediction, replace the result the comparison produced, or skip the call entirely — the "
        "prediction would look checked when it was not. Remove the hooks from this tool, or drop "
        "@verified_tool and check the result inside the hook instead."
    )


__all__ = ["DIVERGENCE_DIRECTIVE", "divergence_report", "verified_tool"]
