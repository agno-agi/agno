import json
from typing import Any, AsyncIterator, Dict, List, Optional, Tuple, Union

from agno.run.team import MemoryUpdateCompletedEvent as TeamMemoryUpdateCompletedEvent
from agno.run.team import MemoryUpdateStartedEvent as TeamMemoryUpdateStartedEvent
from agno.run.team import ReasoningCompletedEvent as TeamReasoningCompletedEvent
from agno.run.team import ReasoningStartedEvent as TeamReasoningStartedEvent
from agno.run.team import ReasoningStepEvent as TeamReasoningStepEvent
from agno.run.team import RunCancelledEvent as TeamRunCancelledEvent
from agno.run.team import RunCompletedEvent as TeamRunCompletedEvent
from agno.run.team import RunContentEvent as TeamRunContentEvent
from agno.run.team import RunErrorEvent as TeamRunErrorEvent
from agno.run.team import RunPausedEvent as TeamRunPausedEvent
from agno.run.team import RunStartedEvent as TeamRunStartedEvent
from agno.run.team import TeamRunOutput, TeamRunOutputEvent, team_run_output_event_from_dict
from agno.run.team import ToolCallCompletedEvent as TeamToolCallCompletedEvent
from agno.run.team import ToolCallStartedEvent as TeamToolCallStartedEvent
from agno.run.workflow import (
    ConditionExecutionCompletedEvent,
    ConditionExecutionStartedEvent,
    LoopExecutionCompletedEvent,
    LoopExecutionStartedEvent,
    LoopIterationCompletedEvent,
    LoopIterationStartedEvent,
    ParallelExecutionCompletedEvent,
    ParallelExecutionStartedEvent,
    RouterExecutionCompletedEvent,
    RouterExecutionStartedEvent,
    RouterPausedEvent,
    StepExecutorPausedEvent,
    StepsExecutionCompletedEvent,
    StepsExecutionStartedEvent,
    WorkflowCancelledEvent,
    WorkflowCompletedEvent,
    WorkflowErrorEvent,
    WorkflowPausedEvent,
    WorkflowRunOutputEvent,
    WorkflowStartedEvent,
)
from agno.run.workflow import StepCompletedEvent as WorkflowStepCompletedEvent
from agno.run.workflow import StepErrorEvent as WorkflowStepErrorEvent
from agno.run.workflow import StepPausedEvent as WorkflowStepPausedEvent
from agno.run.workflow import StepStartedEvent as WorkflowStepStartedEvent

try:
    from a2a.helpers import new_text_part
    from a2a.server.tasks import TaskUpdater
    from a2a.types import TaskState
except ImportError as e:
    raise ImportError("`a2a` not installed. Please install it with `pip install -U a2a-sdk`") from e


from agno.os.interfaces.a2a.utils import (
    REASONING_ARTIFACT_NAME,
    RESPONSE_ARTIFACT_NAME,
    map_content_to_part,
    map_media_to_artifacts,
)
from agno.run.agent import (
    MemoryUpdateCompletedEvent,
    MemoryUpdateStartedEvent,
    ReasoningCompletedEvent,
    ReasoningStartedEvent,
    ReasoningStepEvent,
    RunCancelledEvent,
    RunCompletedEvent,
    RunContentEvent,
    RunErrorEvent,
    RunOutput,
    RunOutputEvent,
    RunPausedEvent,
    RunStartedEvent,
    ToolCallCompletedEvent,
    ToolCallStartedEvent,
)
from agno.run.base import RunStatus

# Workflow events sent as progress: the event type sent to the client, and the event fields sent with it.
# A field marked True is sent whenever it is set, the others only when they hold a value.
_WORKFLOW_PROGRESS_EVENTS: Dict[Any, Tuple[str, List[Tuple[str, bool]]]] = {
    WorkflowStepStartedEvent: ("workflow_step_started", [("step_name", False)]),
    WorkflowStepCompletedEvent: ("workflow_step_completed", [("step_name", False)]),
    WorkflowStepErrorEvent: ("workflow_step_error", [("step_name", False), ("error", False)]),
    LoopExecutionStartedEvent: ("loop_execution_started", [("step_name", False), ("max_iterations", False)]),
    LoopIterationStartedEvent: (
        "loop_iteration_started",
        [("step_name", False), ("iteration", True), ("max_iterations", False)],
    ),
    LoopIterationCompletedEvent: (
        "loop_iteration_completed",
        [("step_name", False), ("iteration", True), ("should_continue", True)],
    ),
    LoopExecutionCompletedEvent: ("loop_execution_completed", [("step_name", False), ("total_iterations", True)]),
    ParallelExecutionStartedEvent: (
        "parallel_execution_started",
        [("step_name", False), ("parallel_step_count", False)],
    ),
    ParallelExecutionCompletedEvent: (
        "parallel_execution_completed",
        [("step_name", False), ("parallel_step_count", False)],
    ),
    ConditionExecutionStartedEvent: ("condition_execution_started", [("step_name", False), ("condition_result", True)]),
    ConditionExecutionCompletedEvent: (
        "condition_execution_completed",
        [("step_name", False), ("condition_result", True), ("executed_steps", True)],
    ),
    RouterExecutionStartedEvent: ("router_execution_started", [("step_name", False), ("selected_steps", False)]),
    RouterExecutionCompletedEvent: (
        "router_execution_completed",
        [("step_name", False), ("selected_steps", False), ("executed_steps", True)],
    ),
    StepsExecutionStartedEvent: ("steps_execution_started", [("step_name", False), ("steps_count", False)]),
    StepsExecutionCompletedEvent: (
        "steps_execution_completed",
        [("step_name", False), ("steps_count", False), ("executed_steps", True)],
    ),
}


def _get_tool_metadata(event: Any, event_type: str) -> Dict[str, Any]:
    """Get the metadata sent with a tool call event."""
    metadata: Dict[str, Any] = {"agno_event_type": event_type}
    if event.tool:
        metadata["tool_name"] = event.tool.tool_name or "tool"
        if hasattr(event.tool, "tool_call_id") and event.tool.tool_call_id:
            metadata["tool_call_id"] = event.tool.tool_call_id
        if hasattr(event.tool, "tool_args") and event.tool.tool_args:
            metadata["tool_args"] = json.dumps(event.tool.tool_args)
    return metadata


def _get_progress_metadata(event: Any) -> Optional[Dict[str, Any]]:
    """Get the metadata of the status update an event is sent as, or None when the event is not a progress event."""
    # Tool call events
    if isinstance(event, (ToolCallStartedEvent, TeamToolCallStartedEvent)):
        return _get_tool_metadata(event, "tool_call_started")
    if isinstance(event, (ToolCallCompletedEvent, TeamToolCallCompletedEvent)):
        return _get_tool_metadata(event, "tool_call_completed")

    # Reasoning events
    if isinstance(event, (ReasoningStartedEvent, TeamReasoningStartedEvent)):
        return {"agno_event_type": "reasoning_started"}
    if isinstance(event, (ReasoningCompletedEvent, TeamReasoningCompletedEvent)):
        return {"agno_event_type": "reasoning_completed"}

    # Memory update events
    if isinstance(event, (MemoryUpdateStartedEvent, TeamMemoryUpdateStartedEvent)):
        return {"agno_event_type": "memory_update_started"}
    if isinstance(event, (MemoryUpdateCompletedEvent, TeamMemoryUpdateCompletedEvent)):
        return {"agno_event_type": "memory_update_completed"}

    # Workflow events
    for event_class, (event_type, fields) in _WORKFLOW_PROGRESS_EVENTS.items():
        if isinstance(event, event_class):
            metadata: Dict[str, Any] = {"agno_event_type": event_type}
            for field, send_when_set in fields:
                value = getattr(event, field, None)
                if value is not None if send_when_set else value:
                    metadata[field] = value
            return metadata
    return None


async def map_background_stream_to_run_events(
    event_stream: AsyncIterator[Any],
    entity: Any,
    run_id: str,
    session_id: str,
) -> AsyncIterator[Any]:
    """Map the stream of a background run back to Agno events.

    A background run streams its events as SSE strings, the form they are buffered in for
    clients that reconnect. A run that ends without a final event (one cancelled before it
    started) is given the one its stored run calls for.

    Args:
        event_stream: The async iterator from agent/team.arun(stream=True, background=True)
        entity: The Agno Agent or Team being run
        run_id: The id of the run
        session_id: The id of the session the run belongs to

    Yields:
        The Agno events of the run
    """
    is_finished = False
    async for event in event_stream:
        if isinstance(event, str):
            # Keepalive comments carry no event
            data_line = next((line for line in event.splitlines() if line.startswith("data: ")), None)
            if data_line is None:
                continue
            event = team_run_output_event_from_dict(json.loads(data_line[len("data: ") :]))
        elif isinstance(event, (RunOutput, TeamRunOutput)):
            continue
        if getattr(event, "run_id", None) == run_id and isinstance(
            event,
            (
                RunCompletedEvent,
                RunCancelledEvent,
                RunErrorEvent,
                RunPausedEvent,
                TeamRunCompletedEvent,
                TeamRunCancelledEvent,
                TeamRunErrorEvent,
                TeamRunPausedEvent,
            ),
        ):
            is_finished = True
        yield event

    if is_finished:
        return
    run_output = await entity.aget_run_output(run_id=run_id, session_id=session_id)
    if run_output is not None and run_output.status == RunStatus.cancelled:
        yield RunCancelledEvent(run_id=run_id, session_id=session_id, reason="Run was cancelled")
    elif run_output is not None and run_output.status == RunStatus.error:
        yield RunErrorEvent(run_id=run_id, session_id=session_id, content=str(run_output.content or "Run failed"))


async def stream_run_events_to_task(
    event_stream: AsyncIterator[Union[RunOutputEvent, TeamRunOutputEvent, WorkflowRunOutputEvent, RunOutput]],
    updater: TaskUpdater,
    user_id: Optional[str] = None,
) -> Optional[Any]:
    """Stream the given event stream into the A2A Task behind the given TaskUpdater.

    1. Send initial event
    2. Send content and secondary events
    3. Send the final content and media
    4. Send final status event

    Args:
        event_stream: The async iterator of Agno events from agent/team/workflow.arun(stream=True)
        updater: The A2A TaskUpdater for the task being run
        user_id: The user the run is attributed to, sent back on the final status event

    Returns:
        The event that paused the run, when it paused. The task is then left for the
        caller to mark as waiting for input, with the requirements of the paused run.
    """
    response_artifact_id: str = f"{updater.task_id}-{RESPONSE_ARTIFACT_NAME}"
    reasoning_artifact_id: str = f"{updater.task_id}-{REASONING_ARTIFACT_NAME}"
    accumulated_content = ""
    content_started = False
    reasoning_started = False
    root_run_id: Optional[str] = None
    completion_event = None
    cancelled_event = None
    error_event = None
    paused_event = None

    # Stream events
    async for event in event_stream:
        # Members and steps stream their own runs inside the root run. Only the root run
        # starts and ends the task, so a member that fails or completes never ends it early.
        is_root_event = root_run_id is None or getattr(event, "run_id", None) == root_run_id

        # 1. Send initial event
        if isinstance(event, (RunStartedEvent, TeamRunStartedEvent, WorkflowStartedEvent)):
            if root_run_id is None:
                root_run_id = getattr(event, "run_id", None)
                await updater.start_work()

        # 2. Send all content and secondary events

        # Send content events
        elif isinstance(event, (RunContentEvent, TeamRunContentEvent)) and event.content:
            # Structured content (from output_schema) is sent as a data part, so it is
            # never str-concatenated into the accumulated text.
            raw_content = event.content
            if isinstance(raw_content, str):
                accumulated_content += raw_content
            await updater.add_artifact(
                parts=[map_content_to_part(raw_content)],
                artifact_id=response_artifact_id,
                name=RESPONSE_ARTIFACT_NAME,
                metadata={"agno_content_category": "content"},
                append=content_started,
            )
            content_started = True

        # Send reasoning steps
        elif isinstance(event, (ReasoningStepEvent, TeamReasoningStepEvent)):
            if event.reasoning_content:
                # Send reasoning step as its own artifact, so it never mixes with the response
                reasoning_part = new_text_part(event.reasoning_content)
                reasoning_part.metadata.update({"step_type": event.content_type if event.content_type else "str"})
                await updater.add_artifact(
                    parts=[reasoning_part],
                    artifact_id=reasoning_artifact_id,
                    name=REASONING_ARTIFACT_NAME,
                    metadata={"agno_content_category": "reasoning", "agno_event_type": "reasoning_step"},
                    append=reasoning_started,
                )
                reasoning_started = True

        # Capture completion event for final task construction
        elif isinstance(event, (RunCompletedEvent, TeamRunCompletedEvent, WorkflowCompletedEvent)):
            if is_root_event:
                completion_event = event

        # Capture cancelled event for final task construction
        elif isinstance(event, (RunCancelledEvent, TeamRunCancelledEvent, WorkflowCancelledEvent)):
            if is_root_event:
                cancelled_event = event

        # Capture error event for final task construction
        elif isinstance(event, (RunErrorEvent, TeamRunErrorEvent, WorkflowErrorEvent)):
            if is_root_event:
                error_event = event

        # Capture paused event for final task construction
        elif isinstance(
            event,
            (
                RunPausedEvent,
                TeamRunPausedEvent,
                WorkflowPausedEvent,
                WorkflowStepPausedEvent,
                StepExecutorPausedEvent,
                RouterPausedEvent,
            ),
        ):
            if is_root_event:
                paused_event = event

        # Send tool call, reasoning, memory and workflow events as progress
        else:
            progress_metadata = _get_progress_metadata(event)
            if progress_metadata is not None:
                await updater.update_status(TaskState.TASK_STATE_WORKING, metadata=progress_metadata)

    # 3. Send the final content and media
    # The final chunk replaces the streamed chunks, so the stored task holds the response once
    final_content = completion_event.content if completion_event and completion_event.content else accumulated_content
    if final_content:
        await updater.add_artifact(
            parts=[map_content_to_part(final_content)],
            artifact_id=response_artifact_id,
            name=RESPONSE_ARTIFACT_NAME,
            metadata={"agno_content_category": "content"},
            append=False,
            last_chunk=True,
        )
    if completion_event:
        for artifact in map_media_to_artifacts(completion_event):
            await updater.add_artifact(
                parts=list(artifact.parts),
                artifact_id=artifact.artifact_id,
                name=artifact.name,
                append=False,
                last_chunk=True,
            )

    # 4. Send final status event
    # If cancelled, send canceled status
    if cancelled_event:
        cancel_message = "Run was cancelled"
        metadata = {"agno_event_type": "run_cancelled"}
        if hasattr(cancelled_event, "reason") and cancelled_event.reason:
            cancel_message = f"Run was cancelled: {cancelled_event.reason}"
            metadata["reason"] = cancelled_event.reason
        await updater.update_status(
            TaskState.TASK_STATE_CANCELED,
            message=updater.new_agent_message(parts=[new_text_part(cancel_message)]),
            metadata=metadata,
        )
        return None

    # If the run failed, send failed status with the error
    if error_event:
        error_content = getattr(error_event, "content", None) or getattr(error_event, "error", None) or "Run failed"
        metadata = {"agno_event_type": "run_error"}
        if hasattr(error_event, "error_type") and error_event.error_type:
            metadata["error_type"] = error_event.error_type
        await updater.update_status(
            TaskState.TASK_STATE_FAILED,
            message=updater.new_agent_message(parts=[new_text_part(str(error_content))]),
            metadata=metadata,
        )
        return None

    # If the run paused, the caller marks the task as waiting for input
    if paused_event:
        return paused_event

    # Caller-stamped metadata and metrics ride the terminal status-update
    status_metadata: Dict[str, Any] = {}
    if completion_event:
        completion_metadata = getattr(completion_event, "metadata", None)
        if completion_metadata:
            status_metadata.update(completion_metadata)
        if hasattr(completion_event, "metrics") and completion_event.metrics:  # type: ignore
            status_metadata["metrics"] = completion_event.metrics.to_dict()  # type: ignore
    if user_id:
        status_metadata["userId"] = user_id

    await updater.update_status(
        TaskState.TASK_STATE_COMPLETED,
        metadata=status_metadata if status_metadata else None,
    )
    return None
