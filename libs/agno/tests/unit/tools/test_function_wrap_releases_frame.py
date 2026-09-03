"""Cached ``validate_call`` wrappers must not keep the frame that built them alive.

``validate_call`` stores the caller's ``f_locals`` on the wrapper for forward
reference resolution. On Python 3.13 that is a proxy holding the frame, and the
frame holds its whole call chain. ``Function`` caches wrappers for the life of
the process, so the Agent, session and run state on the stack at first use were
never freed. The validators are built eagerly, so the namespace can be dropped
as soon as the wrapper exists.
"""

from __future__ import annotations

import gc
import weakref
from collections.abc import AsyncIterator  # pydantic resolves the annotation at wrap time

import pytest

from agno.tools.function import Function


class _Sentinel:
    """Stands in for anything living in the frame that wraps a tool."""


def _tool(value: int, label: str = "x") -> str:
    """Echo the arguments."""
    return f"{label}:{value}"


async def _streaming_tool(value: int) -> AsyncIterator[str]:
    """Yield the argument twice."""
    yield str(value)
    yield str(value)


def _wrap_from_a_frame_holding(sentinel, tool=_tool):
    assert sentinel is not None
    return Function._wrap_callable_uncached(tool)


def _validator_holders(wrapped):
    holders = []
    for cell in wrapped.__closure__ or ():
        contents = cell.cell_contents
        holder = getattr(contents, "__self__", contents)
        if hasattr(holder, "ns_resolver"):
            holders.append(holder)
        elif callable(contents) and getattr(contents, "__closure__", None):
            holders.extend(_validator_holders(contents))
    return holders


def test_wrapped_tool_drops_the_caller_namespace_and_still_validates():
    sentinel = _Sentinel()
    sentinel_ref = weakref.ref(sentinel)

    wrapped = _wrap_from_a_frame_holding(sentinel)
    del sentinel
    gc.collect()

    assert [holder.ns_resolver for holder in _validator_holders(wrapped)] == [None]
    assert sentinel_ref() is None  # bites on Python 3.13, where f_locals is a frame proxy
    assert wrapped("3", label="y") == "y:3"  # coercion still applies


@pytest.mark.asyncio
async def test_async_generator_tool_drops_the_caller_namespace_too():
    sentinel = _Sentinel()
    sentinel_ref = weakref.ref(sentinel)

    wrapped = _wrap_from_a_frame_holding(sentinel, _streaming_tool)
    del sentinel
    gc.collect()

    assert [holder.ns_resolver for holder in _validator_holders(wrapped)] == [None]
    assert sentinel_ref() is None
    assert [item async for item in wrapped("4")] == ["4", "4"]
