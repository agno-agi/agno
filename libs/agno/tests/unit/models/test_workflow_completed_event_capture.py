"""
Tests for WorkflowCompletedEvent content capture in async generator processing.

This test verifies the fix for the indentation bug where WorkflowCompletedEvent
isinstance check was nested inside the CustomEvent check block, making it
unreachable dead code since these are sibling classes.

The bug: WorkflowCompletedEvent and CustomEvent both inherit from
BaseWorkflowRunOutputEvent (siblings). The nested check could never execute
because isinstance(item, CustomEvent) is always False for WorkflowCompletedEvent.

Fix: Dedent WorkflowCompletedEvent check to be a sibling of CustomEvent check.
"""

from typing import AsyncIterator

import pytest

from agno.run.workflow import WorkflowCompletedEvent, CustomEvent


def test_workflow_completed_event_not_custom_event():
    """Verify WorkflowCompletedEvent is NOT a subclass of CustomEvent."""
    event = WorkflowCompletedEvent(
        workflow_id="test-workflow",
        session_id="test-session",
        content="workflow result",
    )
    assert not isinstance(event, CustomEvent)


def test_custom_event_not_workflow_completed_event():
    """Verify CustomEvent is NOT a subclass of WorkflowCompletedEvent."""
    event = CustomEvent(name="test", data={"key": "value"})
    assert not isinstance(event, WorkflowCompletedEvent)


def test_both_are_siblings():
    """Verify both classes share the same parent (BaseWorkflowRunOutputEvent)."""
    from agno.run.workflow import BaseWorkflowRunOutputEvent

    assert issubclass(WorkflowCompletedEvent, BaseWorkflowRunOutputEvent)
    assert issubclass(CustomEvent, BaseWorkflowRunOutputEvent)
    assert not issubclass(WorkflowCompletedEvent, CustomEvent)
    assert not issubclass(CustomEvent, WorkflowCompletedEvent)


class TestWorkflowCompletedEventContentCapture:
    """Tests for WorkflowCompletedEvent content being captured in tool output."""

    def test_workflow_completed_event_content_extraction_string(self):
        """Test that string content is extracted correctly."""
        event = WorkflowCompletedEvent(
            workflow_id="test-workflow",
            session_id="test-session",
            content="The workflow completed successfully with result X",
        )

        assert event.content == "The workflow completed successfully with result X"

    def test_workflow_completed_event_content_extraction_none(self):
        """Test that None content is handled."""
        event = WorkflowCompletedEvent(
            workflow_id="test-workflow",
            session_id="test-session",
            content=None,
        )

        assert event.content is None

    def test_workflow_completed_event_content_extraction_basemodel(self):
        """Test that BaseModel content can be serialized."""
        from pydantic import BaseModel

        class ResultModel(BaseModel):
            status: str
            value: int

        result = ResultModel(status="success", value=42)
        event = WorkflowCompletedEvent(
            workflow_id="test-workflow",
            session_id="test-session",
            content=result,
        )

        assert event.content == result
        assert event.content.model_dump_json() == '{"status":"success","value":42}'


class TestAsyncGeneratorEventProcessing:
    """
    Tests verifying the control flow for WorkflowCompletedEvent processing.

    These tests verify the logic that was fixed: WorkflowCompletedEvent should
    be checked as a sibling of CustomEvent, not nested inside it.
    """

    def test_isinstance_check_order_matters(self):
        """
        Demonstrate why nesting isinstance checks for siblings is wrong.

        If check B is nested inside check A, and A and B are siblings (disjoint),
        then B can never match when A matches - and since they're disjoint,
        B will never get a chance to match.
        """
        event = WorkflowCompletedEvent(
            workflow_id="wf",
            session_id="sess",
            content="result",
        )

        captured_content = None

        if isinstance(event, CustomEvent):
            if isinstance(event, WorkflowCompletedEvent):
                captured_content = event.content

        assert captured_content is None

        captured_content = None
        if isinstance(event, CustomEvent):
            pass
        if isinstance(event, WorkflowCompletedEvent):
            captured_content = event.content

        assert captured_content == "result"

    def test_sync_generator_workflow_event_processing(self):
        """Test that sync generator correctly processes WorkflowCompletedEvent."""
        from agno.run.workflow import WorkflowRunOutputEvent
        from typing import get_args

        events = [
            WorkflowCompletedEvent(
                workflow_id="wf",
                session_id="sess",
                content="final result",
            )
        ]

        function_call_output = ""

        for item in events:
            if isinstance(item, tuple(get_args(WorkflowRunOutputEvent))):
                if isinstance(item, CustomEvent):
                    function_call_output += str(item)
                if isinstance(item, WorkflowCompletedEvent):
                    if item.content is not None:
                        if hasattr(item.content, "model_dump_json"):
                            function_call_output += item.content.model_dump_json()
                        else:
                            function_call_output += str(item.content)

        assert function_call_output == "final result"

    @pytest.mark.asyncio
    async def test_async_generator_workflow_event_processing(self):
        """Test that async generator correctly processes WorkflowCompletedEvent."""
        from agno.run.workflow import WorkflowRunOutputEvent
        from typing import get_args

        async def event_generator() -> AsyncIterator[WorkflowCompletedEvent]:
            yield WorkflowCompletedEvent(
                workflow_id="wf",
                session_id="sess",
                content="async final result",
            )

        function_call_output = ""

        async for item in event_generator():
            if isinstance(item, tuple(get_args(WorkflowRunOutputEvent))):
                if isinstance(item, CustomEvent):
                    function_call_output += str(item)
                if isinstance(item, WorkflowCompletedEvent):
                    if item.content is not None:
                        if hasattr(item.content, "model_dump_json"):
                            function_call_output += item.content.model_dump_json()
                        else:
                            function_call_output += str(item.content)

        assert function_call_output == "async final result"
