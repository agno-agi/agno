"""verified_tool: a tool call that carries a falsifiable prediction.

The tool declares an optional `expect` parameter so the model-facing schema declares it. When
the model fills it, the decorator runs the tool, compares the result against the prediction,
and on mismatch prefixes the result with a divergence block. It verifies one call: it cannot
stop other calls the model issued in the same turn, so cookbooks that want a bound plan ask
for one predicted step per turn.
"""

import functools
import inspect
import traceback
from typing import Any, Callable, TypeVar, Union, cast, get_type_hints

from agno.tools.function import Function, ToolResult
from agno.tools.toolkit import Toolkit
from agno.verifiers.base import is_async_callable
from agno.verifiers.report import escape_closing_tag
from agno.verifiers.types import MAX_REPORT_BYTES, Verdict, cap_text

# The decorated tool keeps its own type. This package ships py.typed, so returning a bare
# Callable would erase the signature for every downstream caller: a wrong argument type and a
# wrong assignment from the result would both type-check clean.
F = TypeVar("F", bound=Callable[..., Any])

DIVERGENCE_DIRECTIVE = (
    "Your prediction for this call was wrong. Do not continue the plan that produced it; "
    "re-derive the next step from the actual result below."
)


def divergence_report(expected: str, actual: str, context: str = "") -> str:
    """The standard block: expected, actual, optional context, and the directive. Capped. The
    tool's own output cannot close the block.
    """
    lines = [
        "<divergence>",
        f"expected: {escape_closing_tag(expected, 'divergence')}",
        f"actual: {escape_closing_tag(actual, 'divergence')}",
    ]
    if context:
        lines.append(escape_closing_tag(context, "divergence"))
    lines.extend([DIVERGENCE_DIRECTIVE, "</divergence>"])
    return cap_text("\n".join(lines), MAX_REPORT_BYTES)


def _prediction_present(value: Any) -> bool:
    return value is not None and str(value).strip() != ""


def _result_text(result: Any) -> str:
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
        tail = traceback.format_exc(limit=-5).rstrip()
        outcome = Verdict(passed=False, report=f"compare raised {type(exc).__name__}: {exc}\n{tail}")
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
    block = divergence_report(expect, cap_text(text, MAX_REPORT_BYTES // 2), context)
    return _with_prefix(result, block)


_PROVABLY_WRONG_RETURNS = (dict, list, tuple, set, frozenset, int, float, bool, bytes)


def _check_return_annotation(fn: Callable) -> None:
    try:
        hints = get_type_hints(fn)
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
    """Decorate a tool function that declares an optional ``expect: Optional[str] = None``.

    Apply it beneath ``@tool``. When ``expect`` is present, ``compare(result, str(expect))``
    runs after the tool and a mismatch (False, a failing Verdict, an exception, any other
    return) prefixes the result with a divergence block for the model; without a prediction
    the call passes through unchanged. Tool exceptions propagate. ``tool_hooks``, ``pre_hook``,
    ``post_hook``, ``external_execution`` and ``stop_after_tool_call`` are refused on a verified
    tool: each can hand the model or the user a result the comparison never saw.
    """

    if is_async_callable(compare):
        raise TypeError("verified_tool needs a sync compare function, because it runs right after the tool returns.")

    def decorate(fn: F) -> F:
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

            async_wrapper._agno_verified_tool = True  # type: ignore
            return cast(F, async_wrapper)

        @functools.wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            expect = prediction(args, kwargs)
            result = fn(*args, **kwargs)
            if not _prediction_present(expect):
                return result
            return _apply(compare, result, str(expect))

        wrapper._agno_verified_tool = True  # type: ignore
        return cast(F, wrapper)

    return decorate


def is_verified_tool(fn: Any) -> bool:
    """True when `fn` is a callable produced by `verified_tool`, however it was partially bound.

    The marker is what lets the tool-execution path refuse to run a verified tool behind hooks
    that can bypass its comparison.
    """
    while isinstance(fn, functools.partial):
        fn = fn.func
    return bool(getattr(fn, "_agno_verified_tool", False))


def validate_verified_tool_hooks(function: Function) -> None:
    """Raise when a Function wraps a verified tool in a way that bypasses its comparison.

    Hooks can rewrite the prediction or the result, or answer without calling the tool;
    external execution never calls it and stop_after_tool_call hands the result to the user.
    """
    if not is_verified_tool(function.entrypoint):
        return
    offenders = []
    if function.tool_hooks:
        offenders.append("tool_hooks")
    if function.pre_hook:
        offenders.append("pre_hook")
    if function.post_hook:
        offenders.append("post_hook")
    if function.external_execution:
        offenders.append("external_execution=True")
    if function.stop_after_tool_call:
        offenders.append("stop_after_tool_call=True")
    if offenders:
        raise ValueError(
            f"{function.name!r} is decorated with @verified_tool and cannot also use {' or '.join(offenders)}."
        )
