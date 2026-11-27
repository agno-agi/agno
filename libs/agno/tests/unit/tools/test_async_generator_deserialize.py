"""Regression tests for async generator tools with Pydantic argument coercion (#8711).

The bug: async generator tools received a raw ``dict`` where the signature
declared a Pydantic ``BaseModel``, producing ``AttributeError: 'dict' object
has no attribute '...'`` on the first attribute access. Sync generator tools
already worked because ``pydantic.validate_call`` wrapped them.

The naive fix (remove the ``isasyncgenfunction`` guard in ``_wrap_callable``)
made deserialization work but broke dispatch: ``validate_call`` around an async
generator turns it into a plain function that returns an ``async_generator``,
so ``inspect.isasyncgenfunction(wrapped)`` returns False. Multiple call sites
(``models/base.py:arun_function_call``, ``function.py:_build_..._chain_async``,
``function.py: aexecute`` result handling, cache gating) rely on that predicate
to route the call correctly.

These tests pin both properties: (a) the wrapped entrypoint still reports as an
async generator function, and (b) argument coercion works end-to-end through
``FunctionCall.aexecute`` — the real dispatch path used by ``arun_function_call``.
"""

from inspect import isasyncgen, isasyncgenfunction, iscoroutinefunction, isgeneratorfunction
from typing import Annotated, Any, Literal

import pytest
from pydantic import BaseModel, Field, ValidationError
from pydantic.errors import PydanticUndefinedAnnotation

from agno.agent.agent import Agent
from agno.team.team import Team
from agno.tools.function import Function, FunctionCall


class SearchParams(BaseModel):
    query: str
    time_range: Literal["OneDay", "OneWeek"] = "OneWeek"


async def async_gen_tool(params: SearchParams):
    yield {"query": params.query, "time_range": params.time_range}


class FrameworkToolParams(BaseModel):
    count: int


async def async_gen_agent_tool(agent: Any, params: FrameworkToolParams, count: Annotated[int, Field(gt=0)]):
    yield {"owner": agent.name, "params_count": params.count, "count": count}


async def async_gen_team_tool(host_team: Team, params: FrameworkToolParams, count: Annotated[int, Field(gt=0)]):
    yield {"owner": host_team.name, "params_count": params.count, "count": count}


async def async_gen_unknown_user_type(value: "UnknownUserType"):  # noqa: F821
    yield value


class UnresolvedPayload(BaseModel):
    item: "MissingOrdinaryFieldType"  # noqa: F821


async def async_gen_unresolved_payload(payload: UnresolvedPayload, count: int):
    yield {"payload": payload, "count": count}


async def async_gen_list_agent(owners: list[Agent], count: int):
    yield {"owners": owners, "count": count}


async def async_gen_positional_agent(owner: Agent, /, count: int):
    yield {"owner": owner, "count": count}


async def async_gen_annotated_team(host_team: Annotated[Team, Field(description="Injected team")], count: int):
    yield {"owner": host_team.name, "count": count}


def test_async_gen_wrapped_still_reports_as_async_gen_function():
    """The wrapped entrypoint must still be detectable as an async generator function.

    Regression guard: without the outer ``async def ... yield`` shim,
    ``pydantic.validate_call`` flips ``isasyncgenfunction`` to False and Agno's
    dispatcher would take the sync ``asyncio.to_thread(execute)`` path.
    """
    func = Function(name="async_gen_tool", entrypoint=async_gen_tool)
    func.process_entrypoint()

    assert isasyncgenfunction(func.entrypoint)
    assert not iscoroutinefunction(func.entrypoint)
    assert not isgeneratorfunction(func.entrypoint)
    assert getattr(func.entrypoint, "_wrapped_for_validation", False)


def test_wrap_callable_is_idempotent_for_async_gen():
    """Wrapping an already-wrapped async generator must return the same object.

    Prevents unbounded shim nesting if ``_wrap_callable`` is invoked more than once.
    """
    once = Function._wrap_callable(async_gen_tool)
    twice = Function._wrap_callable(once)
    assert twice is once


@pytest.mark.asyncio
async def test_async_gen_deserializes_pydantic_model_direct_call():
    """Calling the wrapped entrypoint with a dict must coerce it into the BaseModel.

    Before the fix, this raised ``AttributeError: 'dict' object has no attribute 'query'``
    on the first attribute access inside the generator body.
    """
    func = Function(name="async_gen_tool", entrypoint=async_gen_tool)
    func.process_entrypoint()

    result = func.entrypoint(params={"query": "hello", "time_range": "OneDay"})
    assert isasyncgen(result)

    items = [item async for item in result]
    assert items == [{"query": "hello", "time_range": "OneDay"}]


@pytest.mark.asyncio
async def test_async_gen_full_dispatch_through_function_call_aexecute():
    """End-to-end: ``FunctionCall.aexecute`` must route to the async-gen branch.

    This is the path taken by ``Model.arun_function_call`` when the model
    invokes an async generator tool with args from the LLM. It exercises the
    same dispatch predicates the naive fix would break — so removing the shim
    would make this test fail.
    """
    func = Function(name="async_gen_tool", entrypoint=async_gen_tool)
    func.process_entrypoint()

    call = FunctionCall(
        function=func,
        arguments={"params": {"query": "hello", "time_range": "OneWeek"}},
    )

    exec_result = await call.aexecute()

    assert exec_result.status == "success", f"error: {exec_result.error}"
    assert isasyncgen(call.result), (
        "aexecute must store the async_generator on self.result — if this is "
        "not an async_generator, the dispatcher hit the wrong branch and treated "
        "the tool as a plain sync function."
    )

    items = [item async for item in call.result]
    assert items == [{"query": "hello", "time_range": "OneWeek"}]


@pytest.mark.parametrize(
    ("entrypoint", "framework_attr", "framework_value"),
    [
        (async_gen_agent_tool, "_agent", Agent(name="host-agent")),
        (async_gen_team_tool, "_team", Team(name="host-team", members=[])),
    ],
)
@pytest.mark.asyncio
async def test_async_gen_framework_injection_preserves_user_validation(entrypoint, framework_attr, framework_value):
    func = Function.from_callable(entrypoint)
    setattr(func, framework_attr, framework_value)
    assert isasyncgenfunction(func.entrypoint)
    assert set(func.parameters["properties"]) == {"params", "count"}

    call = FunctionCall(function=func, arguments={"params": {"count": "3"}, "count": "4"})
    result = await call.aexecute()
    assert result.status == "success", result.error
    assert isasyncgen(call.result)
    assert [item async for item in call.result] == [{"owner": framework_value.name, "params_count": 3, "count": 4}]

    invalid = FunctionCall(function=func, arguments={"params": {"count": "3"}, "count": "-1"})
    result = await invalid.aexecute()
    assert result.status == "success", result.error
    with pytest.raises(ValidationError, match="greater_than"):
        async for _ in invalid.result:
            pass


def test_async_gen_unknown_user_annotation_keeps_wrap_error():
    with pytest.raises(NameError, match="UnknownUserType") as from_callable_error:
        Function.from_callable(async_gen_unknown_user_type)
    assert type(from_callable_error.value) is NameError

    with pytest.raises(NameError, match="UnknownUserType") as wrap_error:
        Function._wrap_callable_uncached(async_gen_unknown_user_type)
    assert type(wrap_error.value) is NameError


@pytest.mark.parametrize(
    "entrypoint",
    [async_gen_unresolved_payload, async_gen_list_agent, async_gen_positional_agent],
    ids=["ordinary-model-field", "unbound-container", "positional-only-identity"],
)
def test_async_gen_unbindable_annotations_keep_registration_error(entrypoint):
    with pytest.raises(PydanticUndefinedAnnotation):
        Function._wrap_callable_uncached(entrypoint)
    with pytest.raises(PydanticUndefinedAnnotation):
        Function.from_callable(entrypoint)


@pytest.mark.asyncio
async def test_async_gen_annotated_team_still_injects_and_validates_user_argument():
    func = Function.from_callable(async_gen_annotated_team)
    func._team = Team(name="annotated-team", members=[])
    assert set(func.parameters["properties"]) == {"count"}

    call = FunctionCall(function=func, arguments={"count": "3"})
    result = await call.aexecute()
    assert result.status == "success", result.error
    assert [item async for item in call.result] == [{"owner": "annotated-team", "count": 3}]


@pytest.mark.asyncio
async def test_async_gen_shim_propagates_aclose_to_inner_generator():
    """``aclose()`` on the outer shim must run the inner generator's ``finally``.

    The shim's ``try/finally: await inner.aclose()`` block exists so that when a
    caller (or Python's GC) closes the outer generator, resource-holding
    ``finally`` blocks inside the underlying tool still execute — open files,
    HTTP sessions, DB cursors get their cleanup.

    This test defines a tool whose ``finally`` block flips a flag, iterates one
    item from the outer generator, then explicitly ``aclose()``s the outer one
    and asserts the inner's ``finally`` fired.
    """
    cleanup_ran = False

    class Params(BaseModel):
        n: int

    async def resource_holding_tool(params: Params):
        nonlocal cleanup_ran
        try:
            for i in range(params.n):
                yield i
        finally:
            cleanup_ran = True

    func = Function(name="resource_holding_tool", entrypoint=resource_holding_tool)
    func.process_entrypoint()

    outer = func.entrypoint(params={"n": 10})
    first = await outer.__anext__()
    assert first == 0
    assert not cleanup_ran

    await outer.aclose()

    assert cleanup_ran, (
        "outer.aclose() did not propagate to inner generator's finally block — "
        "the shim's try/finally is not correctly proxying aclose()."
    )


@pytest.mark.asyncio
async def test_async_gen_validation_error_surfaces_on_iteration():
    """Invalid arguments must produce a Pydantic ``ValidationError`` when iterated.

    Async generators are lazy — the wrapped call returns an ``async_generator``
    object immediately, so validation only fires on the first ``__anext__``.
    That means ``FunctionCall.aexecute`` sees ``success`` (it only stores the
    generator on ``self.result``), and the caller catches the error on iteration.
    This confirms the wrapping is actually doing validation, not just passing
    dicts straight through.
    """
    from pydantic import ValidationError

    func = Function(name="async_gen_tool", entrypoint=async_gen_tool)
    func.process_entrypoint()

    result = func.entrypoint(params={"query": "hello", "time_range": "InvalidValue"})
    assert isasyncgen(result)

    with pytest.raises(ValidationError, match="time_range"):
        async for _ in result:
            pass
