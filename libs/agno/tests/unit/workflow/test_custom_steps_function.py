"""A function used as a workflow's steps runs exactly once, and errors from its body propagate unchanged."""

from typing import List, Optional

import pytest

from agno.workflow.types import WorkflowExecutionInput
from agno.workflow.workflow import Workflow


def test_sync_function_body_type_error_runs_once_and_propagates():
    calls: List[Optional[WorkflowExecutionInput]] = []

    def steps(workflow=None, execution_input=None):
        calls.append(execution_input)
        if execution_input is None:
            return "called without input"
        return "Total: " + 42  # type: ignore[operator]

    with pytest.raises(TypeError, match="can only concatenate str"):
        Workflow(name="sync", steps=steps).run("order-1")

    assert len(calls) == 1
    assert calls[0] is not None


def test_sync_function_with_required_params_reports_the_body_error():
    calls: List[str] = []

    def steps(workflow, execution_input):
        calls.append(execution_input.input)
        return len(None)  # type: ignore[arg-type]

    with pytest.raises(TypeError, match="has no len"):
        Workflow(name="sync-required", steps=steps).run("order-2")

    assert calls == ["order-2"]


@pytest.mark.asyncio
async def test_async_function_body_type_error_runs_once_and_propagates():
    calls: List[str] = []

    async def steps(workflow, execution_input):
        calls.append(execution_input.input)
        return len(None)  # type: ignore[arg-type]

    with pytest.raises(TypeError, match="has no len"):
        await Workflow(name="async", steps=steps).arun("order-3")

    assert calls == ["order-3"]


@pytest.mark.asyncio
async def test_sync_function_under_arun_runs_once_and_propagates():
    calls: List[str] = []

    def steps(workflow, execution_input):
        calls.append(execution_input.input)
        return "Total: " + 42  # type: ignore[operator]

    with pytest.raises(TypeError, match="can only concatenate str"):
        await Workflow(name="sync-under-arun", steps=steps).arun("order-4")

    assert calls == ["order-4"]


def test_function_receives_only_the_parameters_it_declares():
    received = {}

    def steps(execution_input):
        received["input"] = execution_input.input
        return "done"

    result = Workflow(name="narrow-signature", steps=steps).run("order-5")

    assert result.content == "done"
    assert received == {"input": "order-5"}


@pytest.mark.asyncio
async def test_async_function_receives_only_the_parameters_it_declares():
    received = {}

    async def steps(workflow):
        received["name"] = workflow.name
        return "done"

    result = await Workflow(name="async-narrow-signature", steps=steps).arun("order-6")

    assert result.content == "done"
    assert received == {"name": "async-narrow-signature"}


@pytest.mark.asyncio
async def test_sync_function_under_streaming_arun_receives_only_the_parameters_it_declares():
    received = {}

    def steps(execution_input):
        received["input"] = execution_input.input
        return "done"

    events = [event async for event in Workflow(name="sync-streaming-arun", steps=steps).arun("order-7", stream=True)]

    assert events[-1].content == "done"
    assert received == {"input": "order-7"}


@pytest.mark.asyncio
async def test_sync_generator_under_arun_receives_only_the_parameters_it_declares():
    def steps(execution_input):
        yield f"done {execution_input.input}"

    result = await Workflow(name="sync-generator-arun", steps=steps).arun("order-8")

    assert result.content == "done order-8"
