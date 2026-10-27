"""Bind dynamic registration to the tool call that requested it."""

from collections.abc import AsyncIterator as AsyncIteratorABC
from collections.abc import Iterator as IteratorABC
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from threading import RLock, local
from types import AsyncGeneratorType, GeneratorType
from typing import TYPE_CHECKING, Any, Callable, Iterator, Optional, Set

if TYPE_CHECKING:
    from agno.run.authorization import RunAuthorization
    from agno.tools.function import Function


@dataclass
class _ToolCallContext:
    function: "Function"
    active: bool = True


_current_tool_call: ContextVar[Optional[_ToolCallContext]] = ContextVar("agno_current_tool_call", default=None)
_registration_lock = RLock()
_registration_state = local()


@contextmanager
def tool_registration(agent: Any) -> Iterator[None]:
    # Ordinary async model calls run synchronous tools on worker threads. Keep
    # name validation, preparation and configuration append in one transaction.
    with _registration_lock:
        active_agents: Set[int] = getattr(_registration_state, "agents", set())
        agent_id = id(agent)
        if agent_id in active_agents:
            raise RuntimeError("Cannot register tools recursively while preparing tools for the same Agent.")
        _registration_state.agents = active_agents
        active_agents.add(agent_id)
        try:
            yield
        finally:
            active_agents.remove(agent_id)


@contextmanager
def tool_call_context(function: "Function") -> Iterator[None]:
    context = _ToolCallContext(function)
    token = _current_tool_call.set(context)
    try:
        yield
    finally:
        # A child task inherits the value, so resetting this task's ContextVar
        # alone would still leave that child able to change a finished call.
        context.active = False
        _current_tool_call.reset(token)


def get_dynamic_tool_adder(agent: Any) -> Optional[Callable[[Any], bool]]:
    context = _current_tool_call.get()
    if context is None or context.function._agent is not agent:
        return None
    if not context.active:
        raise RuntimeError("Cannot add a tool from a finished tool call.")
    return context.function._dynamic_tool_adder


@dataclass
class _IterationState:
    started: bool = False


@dataclass
class _ClosingResult:
    wrapped: Any
    original: Any
    function: "Function"
    authority: Optional["RunAuthorization"]
    state: _IterationState
    closed: bool = False

    @contextmanager
    def early_close_scope(self) -> Iterator[None]:
        from agno.run.authorization import authorization_scope

        with tool_call_context(self.function):
            if self.authority is not None and self.authority.enforce_tools:
                with authorization_scope(lambda: self.authority):
                    yield
            else:
                yield


class _ClosingIterator(_ClosingResult, IteratorABC):
    def __iter__(self) -> "_ClosingIterator":
        return self

    def __next__(self) -> Any:
        return self.send(None)

    def send(self, value: Any) -> Any:
        return self.wrapped.send(value)

    def throw(self, *args: Any) -> Any:
        return self.wrapped.throw(*args)

    def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        self.wrapped.close()
        # Closing an unstarted generator never enters its finally block.
        if not self.state.started:
            with self.early_close_scope():
                close = getattr(self.original, "close", None)
                if close is not None:
                    close()


class _ClosingAsyncIterator(_ClosingResult, AsyncIteratorABC):
    def __aiter__(self) -> "_ClosingAsyncIterator":
        return self

    async def __anext__(self) -> Any:
        return await self.asend(None)

    async def asend(self, value: Any) -> Any:
        return await self.wrapped.asend(value)

    async def athrow(self, *args: Any) -> Any:
        return await self.wrapped.athrow(*args)

    async def aclose(self) -> None:
        if self.closed:
            return
        self.closed = True
        await self.wrapped.aclose()
        if not self.state.started:
            with self.early_close_scope():
                aclose = getattr(self.original, "aclose", None)
                if aclose is not None:
                    await aclose()


def bind_tool_result(result: Any, function: "Function", authority: Optional["RunAuthorization"] = None) -> Any:
    # Generator bodies execute later, sometimes in another task. Renew the
    # binding for each advance and reset it before yielding to the consumer.
    from agno.run.authorization import _authorized_tool_result

    if isinstance(result, IteratorABC):
        state = _IterationState()
        wrapped = _authorized_tool_result(_iterate_tool_result(result, function, state), authority)
        return (
            wrapped
            if isinstance(result, GeneratorType)
            else _ClosingIterator(wrapped, result, function, authority, state)
        )
    if isinstance(result, AsyncIteratorABC):
        state = _IterationState()
        wrapped = _authorized_tool_result(_aiterate_tool_result(result, function, state), authority)
        return (
            wrapped
            if isinstance(result, AsyncGeneratorType)
            else _ClosingAsyncIterator(wrapped, result, function, authority, state)
        )
    return result


def _iterate_tool_result(iterator: Any, function: "Function", state: _IterationState) -> Iterator[Any]:
    state.started = True
    try:
        while True:
            try:
                with tool_call_context(function):
                    value = next(iterator)
            except StopIteration:
                return
            yield value
    finally:
        close = getattr(iterator, "close", None)
        if close is not None:
            with tool_call_context(function):
                close()


async def _aiterate_tool_result(iterator: Any, function: "Function", state: _IterationState):
    state.started = True
    try:
        while True:
            try:
                with tool_call_context(function):
                    value = await iterator.__anext__()
            except StopAsyncIteration:
                return
            yield value
    finally:
        aclose = getattr(iterator, "aclose", None)
        if aclose is not None:
            with tool_call_context(function):
                await aclose()
