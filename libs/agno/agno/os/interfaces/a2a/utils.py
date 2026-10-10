import json
from typing import Any, Dict, Optional, cast
from uuid import uuid4

from typing_extensions import List, Union

from agno.run.team import TeamRunOutput
from agno.run.workflow import WorkflowRunOutput

try:
    from a2a.helpers import new_data_part, new_raw_part, new_text_part, new_url_part
    from a2a.server.tasks import TaskUpdater
    from a2a.types import (
        Artifact,
        Part,
        Role,
        Task,
        TaskState,
        TaskStatus,
    )
    from a2a.types import Message as A2AMessage
    from google.protobuf.json_format import MessageToDict
except ImportError as e:
    raise ImportError("`a2a` not installed. Please install it with `pip install -U a2a-sdk`") from e


from agno.media import Audio, File, Image, Video
from agno.run.agent import RunInput, RunOutput
from agno.run.base import RunStatus

RESPONSE_ARTIFACT_NAME = "response"
REASONING_ARTIFACT_NAME = "reasoning"
FINISHED_TASK_STATES = (
    TaskState.TASK_STATE_COMPLETED,
    TaskState.TASK_STATE_CANCELED,
    TaskState.TASK_STATE_FAILED,
    TaskState.TASK_STATE_REJECTED,
)


def map_a2a_message_to_run_input(message: A2AMessage) -> RunInput:
    """Map an A2A Message to Agno RunInput.

    1. Validate the message
    2. Process message parts
    3. Build and return RunInput

    Args:
        message: The A2A Message sent by the client

    Returns:
        RunInput: The Agno RunInput
    """

    # 1. Validate the message
    if message.role != Role.ROLE_USER:
        raise ValueError("Only user messages are accepted")

    # 2. Process message parts
    text_parts = []
    images = []
    videos = []
    audios = []
    files = []

    for part in message.parts:
        content_type = part.WhichOneof("content")

        # Handle message text content
        if content_type == "text":
            text_parts.append(part.text)

        # Handle message files
        elif content_type == "url":
            if part.media_type.startswith("image/"):
                images.append(Image(url=part.url))
            elif part.media_type.startswith("video/"):
                videos.append(Video(url=part.url))
            elif part.media_type.startswith("audio/"):
                audios.append(Audio(url=part.url))
            else:
                files.append(File(url=part.url, mime_type=part.media_type or None))
        elif content_type == "raw":
            if part.media_type.startswith("image/"):
                images.append(Image(content=part.raw, mime_type=part.media_type))
            elif part.media_type.startswith("video/"):
                videos.append(Video(content=part.raw, mime_type=part.media_type))
            elif part.media_type.startswith("audio/"):
                audios.append(Audio(content=part.raw, mime_type=part.media_type))
            # Bytes without a media type cannot be handed to a model
            elif not part.media_type:
                raise ValueError("A raw part requires a media type")
            else:
                files.append(File(content=part.raw, mime_type=part.media_type))

        # Handle message structured data parts
        elif content_type == "data":
            text_parts.append(json.dumps(MessageToDict(part.data)))

    # 3. Build and return RunInput
    complete_input_content = "\n".join(text_parts) if text_parts else ""
    return RunInput(
        input_content=complete_input_content,
        images=images if images else None,
        videos=videos if videos else None,
        audios=audios if audios else None,
        files=files if files else None,
    )


def _map_run_status_to_task_state(status: Optional[RunStatus]) -> TaskState:
    """Map Agno RunStatus to A2A TaskState."""
    if status is None:
        return TaskState.TASK_STATE_COMPLETED
    _mapping = {
        RunStatus.pending: TaskState.TASK_STATE_SUBMITTED,
        RunStatus.running: TaskState.TASK_STATE_WORKING,
        RunStatus.completed: TaskState.TASK_STATE_COMPLETED,
        RunStatus.error: TaskState.TASK_STATE_FAILED,
        RunStatus.cancelled: TaskState.TASK_STATE_CANCELED,
        RunStatus.paused: TaskState.TASK_STATE_INPUT_REQUIRED,
    }
    return _mapping.get(status, TaskState.TASK_STATE_COMPLETED)


def map_paused_run_to_parts(paused_run: Any) -> List[Part]:
    """Map a paused run to the parts of the message a client reads to continue it.

    The message carries a note, then the requirements the run waits on as a data part:
    ``{"requirements": [...]}`` for an Agent or Team, ``{"step_requirements": [...]}`` for
    a Workflow. The client resolves them and sends them back the same way.

    Args:
        paused_run: The paused RunOutput, WorkflowRunOutput, or the event that paused the run

    Returns:
        List[Part]: The parts of the input-required message
    """
    requirements = getattr(paused_run, "requirements", None) or []
    step_requirements = getattr(paused_run, "step_requirements", None) or []

    # Say what the run waits on, so a person reading the task knows what is asked
    pending = []
    for requirement in requirements:
        tool_execution = getattr(requirement, "tool_execution", None)
        if tool_execution is not None and tool_execution.tool_name:
            pending.append(f"tool {tool_execution.tool_name}")
    for step_requirement in step_requirements:
        if getattr(step_requirement, "step_name", None):
            pending.append(f"step {step_requirement.step_name}")
    note = "Run is paused and requires input to continue"
    if pending:
        note = f"{note}: {', '.join(pending)}"
    parts: List[Part] = [new_text_part(note)]
    if requirements:
        parts.append(
            new_data_part(
                {"requirements": [req.to_dict() if hasattr(req, "to_dict") else req for req in requirements]},
                media_type="application/json",
            )
        )
    if step_requirements:
        parts.append(
            new_data_part(
                {"step_requirements": [req.to_dict() if hasattr(req, "to_dict") else req for req in step_requirements]},
                media_type="application/json",
            )
        )
    return parts


def restore_integers(value: Any) -> Any:
    """Restore the integers of data read from an A2A data part.

    A2A carries structured data as JSON numbers, which are read back as floats. Whole
    numbers a float holds exactly are turned back into integers, so tool arguments keep the
    type they were sent with.
    """
    if isinstance(value, float) and value.is_integer() and abs(value) < 2**53:
        return int(value)
    if isinstance(value, dict):
        return {key: restore_integers(item) for key, item in value.items()}
    if isinstance(value, list):
        return [restore_integers(item) for item in value]
    return value


def map_content_to_part(content: Any) -> Part:
    """Map run content to an A2A Part: structured output becomes a data part, anything else text."""
    if hasattr(content, "model_dump"):
        return new_data_part(content.model_dump(mode="json"), media_type="application/json")
    if isinstance(content, (dict, list)):
        return new_data_part(content, media_type="application/json")
    return new_text_part(content if isinstance(content, str) else str(content))


def _map_media_to_part(media: Union[Image, Video, Audio, File], default_mime_type: str) -> Optional[Part]:
    """Map an Agno media object to an A2A Part, by URL when it has one and by raw bytes otherwise."""
    mime_type = getattr(media, "mime_type", None) or default_mime_type
    if media.url:
        return new_url_part(media.url, media_type=mime_type)
    if isinstance(media.content, bytes):
        return new_raw_part(media.content, media_type=mime_type)
    return None


def map_media_to_artifacts(run_output: Any) -> List[Artifact]:
    """Map the media of a RunOutput or completion event to A2A Artifacts."""
    artifacts: List[Artifact] = []
    if hasattr(run_output, "images") and run_output.images:
        for idx, img in enumerate(run_output.images):
            part = _map_media_to_part(img, "image/*")
            if part is None:
                continue
            artifacts.append(
                Artifact(
                    artifact_id=f"image-{idx}",
                    name=getattr(img, "name", None) or f"image-{idx}",
                    description="Image generated during task",
                    parts=[part],
                )
            )
    if hasattr(run_output, "videos") and run_output.videos:
        for idx, vid in enumerate(run_output.videos):
            part = _map_media_to_part(vid, "video/*")
            if part is None:
                continue
            artifacts.append(
                Artifact(
                    artifact_id=f"video-{idx}",
                    name=getattr(vid, "name", None) or f"video-{idx}",
                    description="Video generated during task",
                    parts=[part],
                )
            )
    if hasattr(run_output, "audio") and run_output.audio:
        for idx, aud in enumerate(run_output.audio):
            part = _map_media_to_part(aud, "audio/*")
            if part is None:
                continue
            artifacts.append(
                Artifact(
                    artifact_id=f"audio-{idx}",
                    name=getattr(aud, "name", None) or f"audio-{idx}",
                    description="Audio generated during task",
                    parts=[part],
                )
            )
    if hasattr(run_output, "response_audio") and run_output.response_audio:
        part = _map_media_to_part(run_output.response_audio, "audio/*")
        if part is not None:
            artifacts.append(
                Artifact(
                    artifact_id="response-audio",
                    name=getattr(run_output.response_audio, "name", None) or "response-audio",
                    description="Audio response from agent",
                    parts=[part],
                )
            )
    if hasattr(run_output, "files") and run_output.files:
        for idx, file in enumerate(run_output.files):
            part = _map_media_to_part(file, "application/octet-stream")
            if part is None:
                continue
            artifacts.append(
                Artifact(
                    artifact_id=f"file-{idx}",
                    name=getattr(file, "name", None) or f"file-{idx}",
                    description="File generated during task",
                    parts=[part],
                )
            )
    return artifacts


def map_run_output_to_a2a_task(run_output: Union[RunOutput, TeamRunOutput, WorkflowRunOutput]) -> Task:
    """Map the given RunOutput, TeamRunOutput or WorkflowRunOutput into an A2A Task.

    1. Handle output content
    2. Handle output media
    3. Build the task metadata
    4. Build and return the A2A task

    Args:
        run_output: The Agno RunOutput, TeamRunOutput or WorkflowRunOutput

    Returns:
        Task: The A2A Task
    """
    run_id = cast(str, run_output.run_id) if run_output.run_id else str(uuid4())
    session_id = cast(str, run_output.session_id) if run_output.session_id else str(uuid4())
    artifacts: List[Artifact] = []

    # 1. Handle output content
    if run_output.content:
        artifacts.append(
            Artifact(
                artifact_id=f"{run_id}-{RESPONSE_ARTIFACT_NAME}",
                name=RESPONSE_ARTIFACT_NAME,
                parts=[map_content_to_part(run_output.content)],
            )
        )

    # 2. Handle output media
    artifacts.extend(map_media_to_artifacts(run_output))

    # 3. Build the task metadata
    metadata: Dict[str, Any] = {}
    if hasattr(run_output, "user_id") and run_output.user_id:
        metadata["userId"] = run_output.user_id
    if hasattr(run_output, "metrics") and run_output.metrics:
        metadata["metrics"] = run_output.metrics.to_dict()
    if hasattr(run_output, "metadata") and run_output.metadata:
        metadata.update(run_output.metadata)

    # 4. Build and return the A2A task
    run_status = getattr(run_output, "status", None)
    task_state = _map_run_status_to_task_state(run_status)
    task_status = TaskStatus(state=task_state)
    # Set the task timestamp from the run
    created_at = getattr(run_output, "created_at", None)
    if isinstance(created_at, (int, float)):
        task_status.timestamp.FromSeconds(int(created_at))
    if task_state == TaskState.TASK_STATE_INPUT_REQUIRED:
        task_status.message.CopyFrom(
            A2AMessage(
                message_id=str(uuid4()),
                role=Role.ROLE_AGENT,
                parts=map_paused_run_to_parts(run_output),
                task_id=run_id,
                context_id=session_id,
            )
        )
    # Add the run input as the task history
    history: List[A2AMessage] = []
    run_input = getattr(run_output, "input", None)
    input_content = getattr(run_input, "input_content", run_input)
    if isinstance(input_content, str) and input_content:
        history.append(
            A2AMessage(
                message_id=f"{run_id}-input",
                role=Role.ROLE_USER,
                parts=[new_text_part(input_content)],
                task_id=run_id,
                context_id=session_id,
            )
        )
    return Task(
        id=run_id,
        context_id=session_id,
        status=task_status,
        artifacts=artifacts,
        history=history,
        metadata=metadata if metadata else None,
    )


async def send_run_output_to_task(
    run_output: Union[RunOutput, TeamRunOutput, WorkflowRunOutput],
    updater: TaskUpdater,
    user_id: Optional[str] = None,
) -> None:
    """Send a finished RunOutput, TeamRunOutput or WorkflowRunOutput into the A2A Task behind the given TaskUpdater.

    1. Send the content and media
    2. Send final status event

    Args:
        run_output: The Agno RunOutput, TeamRunOutput or WorkflowRunOutput, from a run that was not streamed
        updater: The A2A TaskUpdater for the task being run
        user_id: The user the run is attributed to, sent back on the final status event
    """
    task = map_run_output_to_a2a_task(run_output)

    # 1. Send the content and media
    for artifact in task.artifacts:
        await updater.add_artifact(
            parts=list(artifact.parts),
            artifact_id=artifact.artifact_id,
            name=artifact.name,
            append=False,
            last_chunk=True,
        )

    # 2. Send final status event
    status_metadata = MessageToDict(task.metadata)
    if user_id:
        status_metadata["userId"] = user_id
    if task.status.state == TaskState.TASK_STATE_INPUT_REQUIRED:
        status_metadata = {"agno_event_type": "run_paused"}
    await updater.update_status(
        task.status.state,
        message=task.status.message if task.status.HasField("message") else None,
        metadata=status_metadata if status_metadata else None,
    )
