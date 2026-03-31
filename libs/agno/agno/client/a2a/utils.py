"""Utility functions for mapping between A2A and Agno data structures.

This module provides bidirectional mapping between:
- A2A TaskResult ↔ Agno RunOutput / TeamRunOutput / WorkflowRunOutput
- A2A StreamEvent ↔ Agno RunOutputEvent / TeamRunOutputEvent / WorkflowRunOutputEvent
"""

from typing import AsyncIterator, List, Optional, Union

from agno.client.a2a.schemas import Artifact, StreamEvent, TaskResult
from agno.media import Audio, File, Image, Video
from agno.run.agent import (
    RunCompletedEvent,
    RunContentEvent,
    RunOutput,
    RunOutputEvent,
    RunStartedEvent,
)
from agno.run.team import (
    RunCompletedEvent as TeamRunCompletedEvent,
)
from agno.run.team import (
    RunContentEvent as TeamRunContentEvent,
)
from agno.run.team import (
    RunStartedEvent as TeamRunStartedEvent,
)
from agno.run.team import (
    TeamRunOutput,
    TeamRunOutputEvent,
)
from agno.run.workflow import (
    WorkflowCompletedEvent,
    WorkflowRunOutput,
    WorkflowRunOutputEvent,
    WorkflowStartedEvent,
)


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
        run_id=task_result.task_id,
        session_id=task_result.context_id,
        agent_id=agent_id,
        user_id=user_id,
        images=images if images else None,
        videos=videos if videos else None,
        audio=audio if audio else None,
        files=files if files else None,
        metadata=task_result.metadata,
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

    if not uri:
        return

    if mime_type.startswith("image/"):
        images.append(Image(url=uri, name=artifact.name))
    elif mime_type.startswith("video/"):
        videos.append(Video(url=uri, name=artifact.name))
    elif mime_type.startswith("audio/"):
        audio.append(Audio(url=uri, name=artifact.name))
    else:
        files.append(File(url=uri, name=artifact.name, mime_type=mime_type or None))


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

    async for event in stream:
        # Capture IDs from events
        if event.task_id:
            run_id = event.task_id
        if event.context_id:
            session_id = event.context_id

        # Map event types
        if event.event_type == "working":
            yield RunStartedEvent(
                run_id=run_id,
                session_id=session_id,
                agent_id=agent_id,
            )

        elif event.is_content and event.content:
            accumulated_content += event.content
            yield RunContentEvent(
                content=event.content,
                run_id=run_id,
                session_id=session_id,
                agent_id=agent_id,
            )

        elif event.is_final:
            # Use content from final event or accumulated content
            final_content = event.content if event.content else accumulated_content
            yield RunCompletedEvent(
                content=final_content,
                run_id=run_id,
                session_id=session_id,
                agent_id=agent_id,
            )
            break  # Stream complete


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
        run_id=task_result.task_id,
        session_id=task_result.context_id,
        team_id=team_id,
        user_id=user_id,
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

    async for event in stream:
        # Capture IDs from events
        if event.task_id:
            run_id = event.task_id
        if event.context_id:
            session_id = event.context_id

        # Map event types
        if event.event_type == "working":
            yield TeamRunStartedEvent(
                run_id=run_id,
                session_id=session_id,
                team_id=team_id,
            )

        elif event.is_content and event.content:
            accumulated_content += event.content
            yield TeamRunContentEvent(
                content=event.content,
                run_id=run_id,
                session_id=session_id,
                team_id=team_id,
            )

        elif event.is_final:
            # Use content from final event or accumulated content
            final_content = event.content if event.content else accumulated_content
            yield TeamRunCompletedEvent(
                content=final_content,
                run_id=run_id,
                session_id=session_id,
                team_id=team_id,
            )
            break  # Stream complete


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
        run_id=task_result.task_id,
        session_id=task_result.context_id,
        workflow_id=workflow_id,
        user_id=user_id,
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

    async for event in stream:
        # Capture IDs from events
        if event.task_id:
            run_id = event.task_id
        if event.context_id:
            session_id = event.context_id

        # Map event types
        if event.event_type == "working":
            yield WorkflowStartedEvent(
                run_id=run_id,
                session_id=session_id,
                workflow_id=workflow_id,
            )

        elif event.is_content and event.content:
            accumulated_content += event.content
            # TODO: We don't have workflow content events and we don't know which agent or team created the content, so we're using the workflow_id as the agent_id.
            yield RunContentEvent(
                content=event.content,
                run_id=run_id,
                session_id=session_id,
                agent_id=workflow_id,
            )

        elif event.is_final:
            # Use content from final event or accumulated content
            final_content = event.content if event.content else accumulated_content
            yield WorkflowCompletedEvent(
                content=final_content,
                run_id=run_id,
                session_id=session_id,
                workflow_id=workflow_id,
            )
            break  # Stream complete
