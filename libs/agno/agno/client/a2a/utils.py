"""Utility functions for mapping between A2A and Agno data structures.

This module provides bidirectional mapping between:
- A2A TaskResult ↔ Agno RunOutput / TeamRunOutput / WorkflowRunOutput
- A2A StreamEvent ↔ Agno RunOutputEvent / TeamRunOutputEvent / WorkflowRunOutputEvent
"""

import json
from typing import Any, AsyncIterator, Dict, List, Optional, Union

from agno.client.a2a.schemas import Artifact, StreamEvent, TaskResult
from agno.media import Audio, File, Image, Video
from agno.models.response import ToolExecution
from agno.run.agent import (
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
from agno.run.requirement import RunRequirement
from agno.run.team import (
    RunCancelledEvent as TeamRunCancelledEvent,
)
from agno.run.team import (
    RunCompletedEvent as TeamRunCompletedEvent,
)
from agno.run.team import (
    RunContentEvent as TeamRunContentEvent,
)
from agno.run.team import (
    RunErrorEvent as TeamRunErrorEvent,
)
from agno.run.team import (
    RunPausedEvent as TeamRunPausedEvent,
)
from agno.run.team import (
    RunStartedEvent as TeamRunStartedEvent,
)
from agno.run.team import (
    TeamRunOutput,
    TeamRunOutputEvent,
)
from agno.run.team import (
    ToolCallCompletedEvent as TeamToolCallCompletedEvent,
)
from agno.run.team import (
    ToolCallStartedEvent as TeamToolCallStartedEvent,
)
from agno.run.workflow import (
    WorkflowCancelledEvent,
    WorkflowCompletedEvent,
    WorkflowErrorEvent,
    WorkflowPausedEvent,
    WorkflowRunOutput,
    WorkflowRunOutputEvent,
    WorkflowStartedEvent,
)
from agno.workflow.types import StepRequirement


def map_task_result_to_run_output(
    task_result: TaskResult,
    agent_id: str,
    user_id: Optional[str] = None,
) -> RunOutput:
    """Convert A2A TaskResult to Agno RunOutput.

    Maps the A2A protocol response structure to Agno's internal format,
    enabling seamless integration with Agno's agent infrastructure.

    Args:
        task_result: A2A TaskResult from send_message()
        agent_id: Agent identifier to include in output
        user_id: Optional user identifier to include in output

    Returns:
        RunOutput: Agno-compatible run output
    """
    # Extract media from artifacts
    images: List[Image] = []
    videos: List[Video] = []
    audio: List[Audio] = []
    files: List[File] = []

    for artifact in task_result.artifacts:
        _classify_artifact(artifact, images, videos, audio, files)

    return RunOutput(
        content=task_result.content,
        requirements=_map_paused_requirements(task_result.data) if task_result.is_input_required else None,
        run_id=task_result.task_id,
        session_id=task_result.context_id,
        agent_id=agent_id,
        user_id=user_id,
        status=_map_task_status_to_run_status(task_result.status),
        images=images if images else None,
        videos=videos if videos else None,
        audio=audio if audio else None,
        files=files if files else None,
        metadata=task_result.metadata,
    )


def _map_task_status_to_run_status(status: str) -> RunStatus:
    """Map the status of an A2A task to Agno RunStatus."""
    _mapping = {
        "submitted": RunStatus.pending,
        "working": RunStatus.running,
        "completed": RunStatus.completed,
        "failed": RunStatus.error,
        "rejected": RunStatus.error,
        "canceled": RunStatus.cancelled,
        "input-required": RunStatus.paused,
        "auth-required": RunStatus.paused,
    }
    return _mapping.get(status, RunStatus.completed)


def _map_paused_requirements(data: Optional[Any]) -> Optional[List[RunRequirement]]:
    """Map the requirements a paused A2A task waits on, as an Agno server sends them."""
    if not isinstance(data, dict) or not data.get("requirements"):
        return None
    return [RunRequirement.from_dict(req) for req in data["requirements"] if isinstance(req, dict)]


def _map_paused_step_requirements(data: Optional[Any]) -> Optional[List[StepRequirement]]:
    """Map the step requirements a paused A2A workflow task waits on, as an Agno server sends them."""
    if not isinstance(data, dict) or not data.get("step_requirements"):
        return None
    return [StepRequirement.from_dict(req) for req in data["step_requirements"] if isinstance(req, dict)]


def _map_tool_execution(metadata: Optional[Dict[str, Any]]) -> ToolExecution:
    """Map the tool call an A2A status update describes in its metadata."""
    metadata = metadata or {}
    tool_args = metadata.get("tool_args")
    if isinstance(tool_args, str):
        try:
            tool_args = json.loads(tool_args)
        except json.JSONDecodeError:
            tool_args = None
    return ToolExecution(
        tool_call_id=metadata.get("tool_call_id"),
        tool_name=metadata.get("tool_name"),
        tool_args=tool_args if isinstance(tool_args, dict) else None,
    )


def _classify_artifact(
    artifact: Artifact,
    images: List[Image],
    videos: List[Video],
    audio: List[Audio],
    files: List[File],
) -> None:
    """Classify an A2A artifact into the appropriate media type list.

    Args:
        artifact: A2A artifact to classify
        images: List to append images to
        videos: List to append videos to
        audio: List to append audio to
        files: List to append generic files to
    """
    mime_type = artifact.mime_type or ""
    uri = artifact.uri
    content = artifact.content

    if not uri and not content:
        return

    if mime_type.startswith("image/"):
        images.append(Image(url=uri, name=artifact.name) if uri else Image(content=content, name=artifact.name))
    elif mime_type.startswith("video/"):
        videos.append(Video(url=uri, name=artifact.name) if uri else Video(content=content, name=artifact.name))
    elif mime_type.startswith("audio/"):
        audio.append(Audio(url=uri, name=artifact.name) if uri else Audio(content=content, name=artifact.name))
    elif uri:
        files.append(File(url=uri, name=artifact.name, mime_type=mime_type or None))
    else:
        files.append(File(content=content, name=artifact.name, mime_type=mime_type or None))


async def map_stream_events_to_run_events(
    stream: AsyncIterator[StreamEvent],
    agent_id: str,
) -> AsyncIterator[RunOutputEvent]:
    """Convert A2A stream events to Agno run events.

    Transforms the A2A streaming protocol events into Agno's event system,
    enabling real-time streaming from A2A servers to work with Agno consumers.

    Args:
        stream: AsyncIterator of A2A StreamEvents
        agent_id: Optional agent identifier to include in events
        user_id: Optional user identifier to include in events

    Yields:
        RunOutputEvent: Agno-compatible run output events
    """
    run_id: Optional[str] = None
    session_id: Optional[str] = None
    accumulated_content = ""
    final_content: Optional[str] = None
    run_started = False

    async for event in stream:
        # Capture IDs from events
        if event.task_id:
            run_id = event.task_id
        if event.context_id:
            session_id = event.context_id

        # Map event types
        if event.event_type == "working":
            # The server reports "working" for every step of the run; the run starts once
            if not run_started:
                run_started = True
                yield RunStartedEvent(
                    run_id=run_id,
                    session_id=session_id,
                    agent_id=agent_id,
                )

        elif event.event_type == "tool_call_started":
            yield ToolCallStartedEvent(
                tool=_map_tool_execution(event.metadata),
                run_id=run_id,
                session_id=session_id,
                agent_id=agent_id,
            )

        elif event.event_type == "tool_call_completed":
            yield ToolCallCompletedEvent(
                tool=_map_tool_execution(event.metadata),
                run_id=run_id,
                session_id=session_id,
                agent_id=agent_id,
            )

        elif event.event_type == "artifact" or (event.event_type == "content" and not event.content):
            # The complete response, sent once the agent is done writing it. Structured
            # content has no text chunks, and is given as its JSON string.
            if event.content or event.data is not None:
                final_content = event.content or json.dumps(event.data)

        elif event.is_content and event.content:
            accumulated_content += event.content
            yield RunContentEvent(
                content=event.content,
                run_id=run_id,
                session_id=session_id,
                agent_id=agent_id,
            )
            # A single message is the whole response: there is no final event to follow
            if event.is_final:
                yield RunCompletedEvent(
                    content=accumulated_content,
                    metadata=event.metadata,
                    run_id=run_id,
                    session_id=session_id,
                    agent_id=agent_id,
                )
                break

        elif event.is_final:
            if event.status in ("failed", "rejected"):
                yield RunErrorEvent(
                    content=event.content or "Run failed",
                    run_id=run_id,
                    session_id=session_id,
                    agent_id=agent_id,
                )
                break

            if event.status == "canceled":
                yield RunCancelledEvent(
                    reason=event.content,
                    run_id=run_id,
                    session_id=session_id,
                    agent_id=agent_id,
                )
                break

            if event.status in ("input-required", "auth-required"):
                yield RunPausedEvent(
                    content=event.content,
                    requirements=_map_paused_requirements(event.data),
                    run_id=run_id,
                    session_id=session_id,
                    agent_id=agent_id,
                )
                break

            # final=true marks the end of the stream; forward any metadata the
            # server attached to it onto the completed event.
            yield RunCompletedEvent(
                content=final_content or event.content or accumulated_content,
                metadata=event.metadata,
                run_id=run_id,
                session_id=session_id,
                agent_id=agent_id,
            )
            break  # Stream complete
    else:
        # Some A2A servers (e.g. Google ADK) close the stream without a final event;
        # emit a terminal event so consumers always see a completed run.
        yield RunCompletedEvent(
            content=final_content or accumulated_content,
            run_id=run_id,
            session_id=session_id,
            agent_id=agent_id,
        )


# =============================================================================
# Team Run Output Mapping Functions
# =============================================================================


def map_task_result_to_team_run_output(
    task_result: TaskResult,
    team_id: str,
    user_id: Optional[str] = None,
) -> TeamRunOutput:
    """Convert A2A TaskResult to Agno TeamRunOutput.

    Maps the A2A protocol response structure to Agno's team format,
    enabling seamless integration with Agno's team infrastructure.

    Args:
        task_result: A2A TaskResult from send_message()
        team_id: Optional team identifier to include in output
        user_id: Optional user identifier to include in output
    Returns:
        TeamRunOutput: Agno-compatible team run output
    """
    # Extract media from artifacts
    images: List[Image] = []
    videos: List[Video] = []
    audio: List[Audio] = []
    files: List[File] = []

    for artifact in task_result.artifacts:
        _classify_artifact(artifact, images, videos, audio, files)

    return TeamRunOutput(
        content=task_result.content,
        requirements=_map_paused_requirements(task_result.data) if task_result.is_input_required else None,
        run_id=task_result.task_id,
        session_id=task_result.context_id,
        team_id=team_id,
        user_id=user_id,
        status=_map_task_status_to_run_status(task_result.status),
        images=images if images else None,
        videos=videos if videos else None,
        audio=audio if audio else None,
        files=files if files else None,
        metadata=task_result.metadata,
    )


async def map_stream_events_to_team_run_events(
    stream: AsyncIterator[StreamEvent],
    team_id: str,
) -> AsyncIterator[TeamRunOutputEvent]:
    """Convert A2A stream events to Agno team run events.

    Transforms the A2A streaming protocol events into Agno's team event system,
    enabling real-time streaming from A2A servers to work with Agno team consumers.

    Args:
        stream: AsyncIterator of A2A StreamEvents
        team_id: Optional team identifier to include in events
        user_id: Optional user identifier to include in events
    Yields:
        TeamRunOutputEvent: Agno-compatible team run output events
    """
    run_id: Optional[str] = None
    session_id: Optional[str] = None
    accumulated_content = ""
    final_content: Optional[str] = None
    run_started = False

    async for event in stream:
        # Capture IDs from events
        if event.task_id:
            run_id = event.task_id
        if event.context_id:
            session_id = event.context_id

        # Map event types
        if event.event_type == "working":
            # The server reports "working" for every step of the run; the run starts once
            if not run_started:
                run_started = True
                yield TeamRunStartedEvent(
                    run_id=run_id,
                    session_id=session_id,
                    team_id=team_id,
                )

        elif event.event_type == "tool_call_started":
            yield TeamToolCallStartedEvent(
                tool=_map_tool_execution(event.metadata),
                run_id=run_id,
                session_id=session_id,
                team_id=team_id,
            )

        elif event.event_type == "tool_call_completed":
            yield TeamToolCallCompletedEvent(
                tool=_map_tool_execution(event.metadata),
                run_id=run_id,
                session_id=session_id,
                team_id=team_id,
            )

        elif event.event_type == "artifact" or (event.event_type == "content" and not event.content):
            # The complete response, sent once the agent is done writing it. Structured
            # content has no text chunks, and is given as its JSON string.
            if event.content or event.data is not None:
                final_content = event.content or json.dumps(event.data)

        elif event.is_content and event.content:
            accumulated_content += event.content
            yield TeamRunContentEvent(
                content=event.content,
                run_id=run_id,
                session_id=session_id,
                team_id=team_id,
            )
            # A single message is the whole response: there is no final event to follow
            if event.is_final:
                yield TeamRunCompletedEvent(
                    content=accumulated_content,
                    metadata=event.metadata,
                    run_id=run_id,
                    session_id=session_id,
                    team_id=team_id,
                )
                break

        elif event.is_final:
            if event.status in ("failed", "rejected"):
                yield TeamRunErrorEvent(
                    content=event.content or "Run failed",
                    run_id=run_id,
                    session_id=session_id,
                    team_id=team_id,
                )
                break

            if event.status == "canceled":
                yield TeamRunCancelledEvent(
                    reason=event.content,
                    run_id=run_id,
                    session_id=session_id,
                    team_id=team_id,
                )
                break

            if event.status in ("input-required", "auth-required"):
                yield TeamRunPausedEvent(
                    content=event.content,
                    requirements=_map_paused_requirements(event.data),
                    run_id=run_id,
                    session_id=session_id,
                    team_id=team_id,
                )
                break

            # final=true marks the end of the stream; forward any metadata the
            # server attached to it onto the completed event.
            yield TeamRunCompletedEvent(
                content=final_content or event.content or accumulated_content,
                metadata=event.metadata,
                run_id=run_id,
                session_id=session_id,
                team_id=team_id,
            )
            break  # Stream complete
    else:
        # Some A2A servers (e.g. Google ADK) close the stream without a final event;
        # emit a terminal event so consumers always see a completed run.
        yield TeamRunCompletedEvent(
            content=final_content or accumulated_content,
            run_id=run_id,
            session_id=session_id,
            team_id=team_id,
        )


# =============================================================================
# Workflow Run Output Mapping Functions
# =============================================================================


def map_task_result_to_workflow_run_output(
    task_result: TaskResult,
    workflow_id: str,
    user_id: Optional[str] = None,
) -> WorkflowRunOutput:
    """Convert A2A TaskResult to Agno WorkflowRunOutput.

    Maps the A2A protocol response structure to Agno's workflow format,
    enabling seamless integration with Agno's workflow infrastructure.

    Args:
        task_result: A2A TaskResult from send_message()
        workflow_id: Optional workflow identifier to include in output
        user_id: Optional user identifier to include in output
    Returns:
        WorkflowRunOutput: Agno-compatible workflow run output
    """
    # Extract media from artifacts
    images: List[Image] = []
    videos: List[Video] = []
    audio: List[Audio] = []
    files: List[File] = []

    for artifact in task_result.artifacts:
        _classify_artifact(artifact, images, videos, audio, files)

    return WorkflowRunOutput(
        content=task_result.content,
        step_requirements=_map_paused_step_requirements(task_result.data) if task_result.is_input_required else None,
        run_id=task_result.task_id,
        session_id=task_result.context_id,
        workflow_id=workflow_id,
        user_id=user_id,
        status=_map_task_status_to_run_status(task_result.status),
        images=images if images else None,
        videos=videos if videos else None,
        audio=audio if audio else None,
        metadata=task_result.metadata,
    )


async def map_stream_events_to_workflow_run_events(
    stream: AsyncIterator[StreamEvent],
    workflow_id: str,
) -> AsyncIterator[Union[WorkflowRunOutputEvent, TeamRunOutputEvent, RunOutputEvent]]:
    """Convert A2A stream events to Agno workflow run events.

    Transforms the A2A streaming protocol events into Agno's workflow event system,
    enabling real-time streaming from A2A servers to work with Agno workflow consumers.

    Args:
        stream: AsyncIterator of A2A StreamEvents
        workflow_id: Optional workflow identifier to include in events
        user_id: Optional user identifier to include in events
    Yields:
        WorkflowRunOutputEvent: Agno-compatible workflow run output events
    """
    run_id: Optional[str] = None
    session_id: Optional[str] = None
    accumulated_content = ""
    final_content: Optional[str] = None
    run_started = False

    async for event in stream:
        # Capture IDs from events
        if event.task_id:
            run_id = event.task_id
        if event.context_id:
            session_id = event.context_id

        # Map event types
        if event.event_type == "working":
            # The server reports "working" for every step of the run; the run starts once
            if not run_started:
                run_started = True
                yield WorkflowStartedEvent(
                    run_id=run_id,
                    session_id=session_id,
                    workflow_id=workflow_id,
                )

        elif event.event_type == "artifact" or (event.event_type == "content" and not event.content):
            # The complete response, sent once the agent is done writing it. Structured
            # content has no text chunks, and is given as its JSON string.
            if event.content or event.data is not None:
                final_content = event.content or json.dumps(event.data)

        elif event.is_content and event.content:
            accumulated_content += event.content
            # TODO: We don't have workflow content events and we don't know which agent or team created the content, so we're using the workflow_id as the agent_id.
            yield RunContentEvent(
                content=event.content,
                run_id=run_id,
                session_id=session_id,
                agent_id=workflow_id,
            )
            # A single message is the whole response: there is no final event to follow
            if event.is_final:
                yield WorkflowCompletedEvent(
                    content=accumulated_content,
                    metadata=event.metadata,
                    run_id=run_id,
                    session_id=session_id,
                    workflow_id=workflow_id,
                )
                break

        elif event.is_final:
            if event.status in ("failed", "rejected"):
                yield WorkflowErrorEvent(
                    error=event.content or "Run failed",
                    run_id=run_id,
                    session_id=session_id,
                    workflow_id=workflow_id,
                )
                break

            if event.status == "canceled":
                yield WorkflowCancelledEvent(
                    reason=event.content,
                    run_id=run_id,
                    session_id=session_id,
                    workflow_id=workflow_id,
                )
                break

            if event.status in ("input-required", "auth-required"):
                yield WorkflowPausedEvent(
                    step_requirements=_map_paused_step_requirements(event.data),
                    run_id=run_id,
                    session_id=session_id,
                    workflow_id=workflow_id,
                )
                break

            # final=true marks the end of the stream; forward any metadata the
            # server attached to it onto the completed event.
            yield WorkflowCompletedEvent(
                content=final_content or event.content or accumulated_content,
                metadata=event.metadata,
                run_id=run_id,
                session_id=session_id,
                workflow_id=workflow_id,
            )
            break  # Stream complete
    else:
        # Some A2A servers (e.g. Google ADK) close the stream without a final event;
        # emit a terminal event so consumers always see a completed run.
        yield WorkflowCompletedEvent(
            content=final_content or accumulated_content,
            run_id=run_id,
            session_id=session_id,
            workflow_id=workflow_id,
        )
