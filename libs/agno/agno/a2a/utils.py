"""Utility functions for mapping between A2A and Agno data structures.

This module provides bidirectional mapping between:
- A2A TaskResult ↔ Agno RunOutput
- A2A StreamEvent ↔ Agno RunOutputEvent
"""

from typing import AsyncIterator, List, Optional

from agno.a2a.schemas import Artifact, StreamEvent, TaskResult
from agno.media import Audio, File, Image, Video
from agno.run.agent import (
    RunCompletedEvent,
    RunContentEvent,
    RunOutput,
    RunOutputEvent,
    RunStartedEvent,
)


def map_task_result_to_run_output(
    task_result: TaskResult,
    agent_id: Optional[str] = None,
) -> RunOutput:
    """Convert A2A TaskResult to Agno RunOutput.

    Maps the A2A protocol response structure to Agno's internal format,
    enabling seamless integration with Agno's agent infrastructure.

    Args:
        task_result: A2A TaskResult from send_message()
        agent_id: Optional agent identifier to include in output

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
    agent_id: Optional[str] = None,
) -> AsyncIterator[RunOutputEvent]:
    """Convert A2A stream events to Agno run events.

    Transforms the A2A streaming protocol events into Agno's event system,
    enabling real-time streaming from A2A servers to work with Agno consumers.

    Args:
        stream: AsyncIterator of A2A StreamEvents
        agent_id: Optional agent identifier to include in events

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
                agent_id=agent_id or "",
            )

        elif event.is_content and event.content:
            accumulated_content += event.content
            yield RunContentEvent(
                content=event.content,
                run_id=run_id,
                session_id=session_id,
                agent_id=agent_id or "",
            )

        elif event.is_final:
            # Use content from final event or accumulated content
            final_content = event.content if event.content else accumulated_content
            yield RunCompletedEvent(
                content=final_content,
                run_id=run_id,
                session_id=session_id,
                agent_id=agent_id or "",
            )
            break  # Stream complete
