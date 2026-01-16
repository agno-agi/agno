import json
from typing import Any, Dict, cast
from uuid import uuid4

from fastapi import HTTPException
from typing_extensions import AsyncIterator, List, Union

from agno.run.team import MemoryUpdateCompletedEvent as TeamMemoryUpdateCompletedEvent
from agno.run.team import MemoryUpdateStartedEvent as TeamMemoryUpdateStartedEvent
from agno.run.team import ReasoningCompletedEvent as TeamReasoningCompletedEvent
from agno.run.team import ReasoningStartedEvent as TeamReasoningStartedEvent
from agno.run.team import ReasoningStepEvent as TeamReasoningStepEvent
from agno.run.team import RunCancelledEvent as TeamRunCancelledEvent
from agno.run.team import RunCompletedEvent as TeamRunCompletedEvent
from agno.run.team import RunContentEvent as TeamRunContentEvent
from agno.run.team import RunStartedEvent as TeamRunStartedEvent
from agno.run.team import TeamRunOutputEvent
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
    StepsExecutionCompletedEvent,
    StepsExecutionStartedEvent,
    WorkflowCancelledEvent,
    WorkflowCompletedEvent,
    WorkflowRunOutput,
    WorkflowRunOutputEvent,
    WorkflowStartedEvent,
)
from agno.run.workflow import StepCompletedEvent as WorkflowStepCompletedEvent
from agno.run.workflow import StepErrorEvent as WorkflowStepErrorEvent
from agno.run.workflow import StepStartedEvent as WorkflowStepStartedEvent

try:
    from a2a.types import (
        Artifact,
        DataPart,
        FilePart,
        FileWithBytes,
        FileWithUri,
        Part,
        Role,
        SendMessageRequest,
        SendStreamingMessageRequest,
        SendStreamingMessageSuccessResponse,
        Task,
        TaskState,
        TaskStatus,
        TaskStatusUpdateEvent,
        TextPart,
    )
    from a2a.types import Message as A2AMessage
except ImportError as e:
    raise ImportError("`a2a` not installed. Please install it with `pip install -U a2a`") from e


from agno.media import Audio, File, Image, Video
from agno.run.agent import (
    MemoryUpdateCompletedEvent,
    MemoryUpdateStartedEvent,
    ReasoningCompletedEvent,
    ReasoningStartedEvent,
    ReasoningStepEvent,
    RunCancelledEvent,
    RunCompletedEvent,
    RunContentEvent,
    RunInput,
    RunOutput,
    RunOutputEvent,
    RunStartedEvent,
    ToolCallCompletedEvent,
    ToolCallStartedEvent,
)


async def map_a2a_request_to_run_input(request_body: dict, stream: bool = True) -> RunInput:
    """Map A2A SendMessageRequest to Agno RunInput.

    1. Validate the request
    2. Process message parts
    3. Build and return RunInput

    Args:
        request_body: A2A-valid JSON-RPC request body dict:

        ```json
        {
            "jsonrpc": "2.0",
            "id": "id",
            "params": {
                "message": {
                    "messageId": "id",
                    "role": "user",
                    "contextId": "id",
                    "parts": [{"kind": "text", "text": "Hello"}]
                }
            }
        }
        ```

    Returns:
        RunInput: The Agno RunInput
        stream: Whether we are in stream mode
    """

    # 1. Validate the request
    if stream:
        try:
            a2a_request = SendStreamingMessageRequest.model_validate(request_body)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Invalid A2A request: {str(e)}")
    else:
        try:
            a2a_request = SendMessageRequest.model_validate(request_body)  # type: ignore[assignment]
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Invalid A2A request: {str(e)}")

    a2a_message = a2a_request.params.message
    if a2a_message.role != "user":
        raise HTTPException(status_code=400, detail="Only user messages are accepted")

    # 2. Process message parts
    text_parts = []
    images = []
    videos = []
    audios = []
    files = []

    for part in a2a_message.parts:
        # Handle message text content
        if isinstance(part.root, TextPart):
            text_parts.append(part.root.text)

        # Handle message files
        elif isinstance(part.root, FilePart):
            file_data = part.root.file
            if isinstance(file_data, FileWithUri):
                if not file_data.mime_type:
                    continue
                elif file_data.mime_type.startswith("image/"):
                    images.append(Image(url=file_data.uri))
                elif file_data.mime_type.startswith("video/"):
                    videos.append(Video(url=file_data.uri))
                elif file_data.mime_type.startswith("audio/"):
                    audios.append(Audio(url=file_data.uri))
                else:
                    files.append(File(url=file_data.uri, mime_type=file_data.mime_type))
            elif isinstance(file_data, FileWithBytes):
                if not file_data.mime_type:
                    continue
                files.append(File(content=file_data.bytes, mime_type=file_data.mime_type))

        # Handle message structured data parts
        elif isinstance(part.root, DataPart):
            import json

            text_parts.append(json.dumps(part.root.data))

    # 3. Build and return RunInput
    complete_input_content = "\n".join(text_parts) if text_parts else ""
    return RunInput(
        input_content=complete_input_content,
        images=images if images else None,
        videos=videos if videos else None,
        audios=audios if audios else None,
        files=files if files else None,
    )


def map_run_output_to_a2a_task(run_output: Union[RunOutput, WorkflowRunOutput]) -> Task:
    """Map the given RunOutput or WorkflowRunOutput into an A2A Task.

    1. Handle output content
    2. Handle output media
    3. Build the A2A message
    4. Build and return the A2A task

    Args:
        run_output: The Agno RunOutput or WorkflowRunOutput

    Returns:
        Task: The A2A Task
    """
    parts: List[Part] = []

    # 1. Handle output content
    if run_output.content:
        parts.append(Part(root=TextPart(text=str(run_output.content))))

    # 2. Handle output media
    artifacts: List[Artifact] = []
    if hasattr(run_output, "images") and run_output.images:
        for idx, img in enumerate(run_output.images):
            artifact_parts = []
            if img.url:
                artifact_parts.append(Part(root=FilePart(file=FileWithUri(uri=img.url, mime_type="image/jpeg"))))
            artifacts.append(
                Artifact(
                    artifact_id=str(uuid4()),
                    name=f"image_{idx}",
                    description=f"Generated image {idx}",
                    parts=artifact_parts,
                )
            )
    if hasattr(run_output, "videos") and run_output.videos:
        for idx, vid in enumerate(run_output.videos):
            artifact_parts = []
            if vid.url:
                artifact_parts.append(Part(root=FilePart(file=FileWithUri(uri=vid.url, mime_type="video/mp4"))))
            artifacts.append(
                Artifact(
                    artifact_id=str(uuid4()),
                    name=f"video_{idx}",
                    description=f"Generated video {idx}",
                    parts=artifact_parts,
                )
            )
    if hasattr(run_output, "audio") and run_output.audio:
        for idx, aud in enumerate(run_output.audio):
            artifact_parts = []
            if aud.url:
                artifact_parts.append(Part(root=FilePart(file=FileWithUri(uri=aud.url, mime_type="audio/mpeg"))))
            artifacts.append(
                Artifact(
                    artifact_id=str(uuid4()),
                    name=f"audio_{idx}",
                    description=f"Generated audio {idx}",
                    parts=artifact_parts,
                )
            )
    if hasattr(run_output, "files") and run_output.files:
        for idx, file in enumerate(run_output.files):
            artifact_parts = []
            if file.url:
                artifact_parts.append(
                    Part(
                        root=FilePart(
                            file=FileWithUri(uri=file.url, mime_type=file.mime_type or "application/octet-stream")
                        )
                    )
                )
            artifacts.append(
                Artifact(
                    artifact_id=str(uuid4()),
                    name=getattr(file, "name", f"file_{idx}"),
                    description=f"Generated file {idx}",
                    parts=artifact_parts,
                )
            )

    # 3. Build the A2A message
    metadata = {}
    if hasattr(run_output, "user_id") and run_output.user_id:
        metadata["userId"] = run_output.user_id

    agent_message = A2AMessage(
        message_id=str(uuid4()),  # TODO: use our message_id once it's implemented
        role=Role.agent,
        parts=parts,
        context_id=run_output.session_id,
        task_id=run_output.run_id,
        metadata=metadata if metadata else None,
    )

    # 4. Build and return the A2A task
    run_id = cast(str, run_output.run_id) if run_output.run_id else str(uuid4())
    session_id = cast(str, run_output.session_id) if run_output.session_id else str(uuid4())
    return Task(
        id=run_id,
        context_id=session_id,
        status=TaskStatus(state=TaskState.completed),
        history=[agent_message],
        artifacts=artifacts if artifacts else None,
    )


def map_run_schema_to_a2a_task(run_schema: Dict) -> Task:
    """Map a RunSchema, TeamRunSchema, or WorkflowRunSchema to an A2A Task.

    This function converts run data from the API layer schema format into an A2A Task
    that can be used for interoperability with A2A-compliant systems.

    Args:
        run_schema: The run schema object (RunSchema, TeamRunSchema, or WorkflowRunSchema)

    Returns:
        Task: The A2A Task representation of the run
    """
    # Build message history from run messages
    message_history: List[A2AMessage] = []

    if messages := run_schema.get("messages"):
        for msg in messages:
            if isinstance(msg, dict):
                if msg.get("role") == "assistant":
                    role = Role.agent
                elif msg.get("role") == "user":
                    role = Role.user
                else:
                    continue  # skip system instructions
                parts: List[Part] = []

                # Assuming content is always a string
                if msg.get("content"):
                    parts.append(Part(root=TextPart(text=str(msg["content"]))))

                # Add message metadata if available
                msg_metadata: Dict[str, Any] = {}
                if msg.get("metrics"):
                    msg_metadata["metrics"] = msg["metrics"]
                if msg.get("provider_data"):
                    msg_metadata["provider_data"] = msg["provider_data"]

                message_history.append(
                    A2AMessage(
                        message_id=msg.get("id"),  # type: ignore
                        role=role,
                        parts=parts,
                        context_id=run_schema.get("session_id") or str(uuid4()),
                        task_id=run_schema.get("run_id") or str(uuid4()),
                        metadata=msg_metadata if msg_metadata else None,
                    )
                )

    # If no messages but we have content, create a single agent message
    if not message_history and run_schema.get("content"):
        message_history.append(
            A2AMessage(
                message_id=str(uuid4()),
                role=Role.agent,
                parts=[Part(root=TextPart(text=str(run_schema.get("content"))))],
                context_id=run_schema.get("session_id"),
                task_id=run_schema.get("run_id"),
            )
        )

    # Handle artifacts (images, videos, audio, files)
    artifacts: List[Artifact] = []

    if images := run_schema.get("images"):
        for img in images:
            artifact_parts = []
            img_url = img.get("url")
            if img_url:
                artifact_parts.append(Part(root=FilePart(file=FileWithUri(uri=img_url, mime_type="image/*"))))
            artifacts.append(
                Artifact(
                    artifact_id=f"image-{str(uuid4())}",
                    name=f"image-{img_url}",
                    description=img.get("alt_text"),
                    parts=artifact_parts,
                )
            )

    if videos := run_schema.get("videos"):
        for vid in videos:
            artifact_parts = []
            vid_url = vid.get("url")
            if vid_url:
                artifact_parts.append(Part(root=FilePart(file=FileWithUri(uri=vid_url, mime_type="video/*"))))
            artifacts.append(
                Artifact(
                    artifact_id=f"video-{str(uuid4())}",
                    name=f"video-{vid_url}",
                    description=vid.get("description"),
                    parts=artifact_parts,
                )
            )

    if audio := run_schema.get("audio"):
        for aud in audio:
            artifact_parts = []
            aud_url = aud.get("url")
            if aud_url:
                artifact_parts.append(Part(root=FilePart(file=FileWithUri(uri=aud_url, mime_type="audio/*"))))
            artifacts.append(
                Artifact(
                    artifact_id=f"audio-{str(uuid4())}",
                    name=f"audio-{aud_url}",
                    description=aud.get("description"),
                    parts=artifact_parts,
                )
            )

    if files := run_schema.get("files"):
        for file in files:
            artifact_parts = []
            file_url = file.get("url")
            file_mime = file.get("mime_type")
            if file_url:
                artifact_parts.append(
                    Part(
                        root=FilePart(
                            file=FileWithUri(
                                uri=file_url,
                                mime_type=file_mime or "application/octet-stream",
                            )
                        )
                    )
                )
            artifacts.append(
                Artifact(
                    artifact_id=f"file-{str(uuid4())}",
                    name=f"file-{file_url}",
                    description=file.get("description"),
                    parts=artifact_parts,
                )
            )

    # Handle response_audio for agent runs
    if response_audio := run_schema.get("response_audio"):
        aud_url = response_audio.get("url")
        aud_name = response_audio.get("name")
        if aud_url:
            artifact_parts = []
            artifact_parts.append(Part(root=FilePart(file=FileWithUri(uri=aud_url, mime_type="audio/*"))))
            artifacts.append(
                Artifact(
                    artifact_id="response-audio",
                    name=aud_name or "response-audio",
                    description="Audio response from agent",
                    parts=artifact_parts,
                )
            )

    # Determine task state based on run status
    task_state = TaskState.completed
    if status := run_schema.get("status"):
        status_str = status.upper() if isinstance(status, str) else str(status).upper()
        if status_str in ["FAILED", "ERROR"]:
            task_state = TaskState.failed
        elif status_str in ["CANCELLED", "CANCELED"]:
            task_state = TaskState.canceled
        elif status_str in ["WORKING", "RUNNING", "IN_PROGRESS"]:
            task_state = TaskState.working

    # Build task metadata from metrics if available
    task_metadata: Dict[str, Any] = {}
    if metrics := run_schema.get("metrics"):
        task_metadata["metrics"] = metrics if isinstance(metrics, dict) else metrics.to_dict()

    # Build the task
    return Task(
        id=run_schema.get("run_id") or str(uuid4()),
        context_id=run_schema.get("session_id") or str(uuid4()),
        status=TaskStatus(state=task_state),
        history=message_history if message_history else None,
        artifacts=artifacts if artifacts else None,
        metadata=task_metadata if task_metadata else None,
    )


async def stream_a2a_response(
    event_stream: AsyncIterator[Union[RunOutputEvent, TeamRunOutputEvent, WorkflowRunOutputEvent, RunOutput]],
    request_id: Union[str, int],
) -> AsyncIterator[str]:
    """Stream the given event stream as A2A responses.

    1. Send initial event
    2. Send content and secondary events
    3. Send final status event
    4. Send final complete task

    Args:
        event_stream: The async iterator of Agno events from agent/team/workflow.arun(stream=True)
        request_id: The JSON-RPC request ID

    Yields:
        str: JSON-RPC response objects (A2A-valid)
    """
    task_id: str = str(uuid4())
    context_id: str = str(uuid4())
    message_id: str = str(uuid4())
    accumulated_content = ""
    completion_event = None
    cancelled_event = None

    # Stream events
    async for event in event_stream:
        # 1. Send initial event
        if isinstance(event, (RunStartedEvent, TeamRunStartedEvent, WorkflowStartedEvent)):
            if hasattr(event, "run_id") and event.run_id:
                task_id = event.run_id
            if hasattr(event, "session_id") and event.session_id:
                context_id = event.session_id

            status_event = TaskStatusUpdateEvent(
                task_id=task_id,
                context_id=context_id,
                status=TaskStatus(state=TaskState.working),
                final=False,
            )
            response = SendStreamingMessageSuccessResponse(id=request_id, result=status_event)
            yield f"event: TaskStatusUpdateEvent\ndata: {json.dumps(response.model_dump(exclude_none=True))}\n\n"

        # 2. Send all content and secondary events

        # Send content events
        elif isinstance(event, (RunContentEvent, TeamRunContentEvent)) and event.content:
            accumulated_content += event.content
            message = A2AMessage(
                message_id=message_id,
                role=Role.agent,
                parts=[Part(root=TextPart(text=event.content))],
                context_id=context_id,
                task_id=task_id,
                metadata={"agno_content_category": "content"},
            )
            response = SendStreamingMessageSuccessResponse(id=request_id, result=message)
            yield f"event: Message\ndata: {json.dumps(response.model_dump(exclude_none=True))}\n\n"

        # Send tool call events
        elif isinstance(event, (ToolCallStartedEvent, TeamToolCallStartedEvent)):
            metadata: Dict[str, Any] = {"agno_event_type": "tool_call_started"}
            if event.tool:
                metadata["tool_name"] = event.tool.tool_name or "tool"
                if hasattr(event.tool, "tool_call_id") and event.tool.tool_call_id:
                    metadata["tool_call_id"] = event.tool.tool_call_id
                if hasattr(event.tool, "tool_args") and event.tool.tool_args:
                    metadata["tool_args"] = json.dumps(event.tool.tool_args)

            status_event = TaskStatusUpdateEvent(
                task_id=task_id,
                context_id=context_id,
                status=TaskStatus(state=TaskState.working),
                final=False,
                metadata=metadata,
            )
            response = SendStreamingMessageSuccessResponse(id=request_id, result=status_event)
            yield f"event: TaskStatusUpdateEvent\ndata: {json.dumps(response.model_dump(exclude_none=True))}\n\n"

        elif isinstance(event, (ToolCallCompletedEvent, TeamToolCallCompletedEvent)):
            metadata = {"agno_event_type": "tool_call_completed"}
            if event.tool:
                metadata["tool_name"] = event.tool.tool_name or "tool"
                if hasattr(event.tool, "tool_call_id") and event.tool.tool_call_id:
                    metadata["tool_call_id"] = event.tool.tool_call_id
                if hasattr(event.tool, "tool_args") and event.tool.tool_args:
                    metadata["tool_args"] = json.dumps(event.tool.tool_args)

            status_event = TaskStatusUpdateEvent(
                task_id=task_id,
                context_id=context_id,
                status=TaskStatus(state=TaskState.working),
                final=False,
                metadata=metadata,
            )
            response = SendStreamingMessageSuccessResponse(id=request_id, result=status_event)
            yield f"event: TaskStatusUpdateEvent\ndata: {json.dumps(response.model_dump(exclude_none=True))}\n\n"

        # Send reasoning events
        elif isinstance(event, (ReasoningStartedEvent, TeamReasoningStartedEvent)):
            status_event = TaskStatusUpdateEvent(
                task_id=task_id,
                context_id=context_id,
                status=TaskStatus(state=TaskState.working),
                final=False,
                metadata={"agno_event_type": "reasoning_started"},
            )
            response = SendStreamingMessageSuccessResponse(id=request_id, result=status_event)
            yield f"event: TaskStatusUpdateEvent\ndata: {json.dumps(response.model_dump(exclude_none=True))}\n\n"

        elif isinstance(event, (ReasoningStepEvent, TeamReasoningStepEvent)):
            if event.reasoning_content:
                # Send reasoning step as a message
                reasoning_message = A2AMessage(
                    message_id=str(uuid4()),
                    role=Role.agent,
                    parts=[
                        Part(
                            root=TextPart(
                                text=event.reasoning_content,
                                metadata={
                                    "step_type": event.content_type if event.content_type else "str",
                                },
                            )
                        )
                    ],
                    context_id=context_id,
                    task_id=task_id,
                    metadata={"agno_content_category": "reasoning", "agno_event_type": "reasoning_step"},
                )
                response = SendStreamingMessageSuccessResponse(id=request_id, result=reasoning_message)
                yield f"event: Message\ndata: {json.dumps(response.model_dump(exclude_none=True))}\n\n"

        elif isinstance(event, (ReasoningCompletedEvent, TeamReasoningCompletedEvent)):
            status_event = TaskStatusUpdateEvent(
                task_id=task_id,
                context_id=context_id,
                status=TaskStatus(state=TaskState.working),
                final=False,
                metadata={"agno_event_type": "reasoning_completed"},
            )
            response = SendStreamingMessageSuccessResponse(id=request_id, result=status_event)
            yield f"event: TaskStatusUpdateEvent\ndata: {json.dumps(response.model_dump(exclude_none=True))}\n\n"

        # Send memory update events
        elif isinstance(event, (MemoryUpdateStartedEvent, TeamMemoryUpdateStartedEvent)):
            status_event = TaskStatusUpdateEvent(
                task_id=task_id,
                context_id=context_id,
                status=TaskStatus(state=TaskState.working),
                final=False,
                metadata={"agno_event_type": "memory_update_started"},
            )
            response = SendStreamingMessageSuccessResponse(id=request_id, result=status_event)
            yield f"event: TaskStatusUpdateEvent\ndata: {json.dumps(response.model_dump(exclude_none=True))}\n\n"

        elif isinstance(event, (MemoryUpdateCompletedEvent, TeamMemoryUpdateCompletedEvent)):
            status_event = TaskStatusUpdateEvent(
                task_id=task_id,
                context_id=context_id,
                status=TaskStatus(state=TaskState.working),
                final=False,
                metadata={"agno_event_type": "memory_update_completed"},
            )
            response = SendStreamingMessageSuccessResponse(id=request_id, result=status_event)
            yield f"event: TaskStatusUpdateEvent\ndata: {json.dumps(response.model_dump(exclude_none=True))}\n\n"

        # Send workflow events
        elif isinstance(event, WorkflowStepStartedEvent):
            metadata = {"agno_event_type": "workflow_step_started"}
            if hasattr(event, "step_name") and event.step_name:
                metadata["step_name"] = event.step_name

            status_event = TaskStatusUpdateEvent(
                task_id=task_id,
                context_id=context_id,
                status=TaskStatus(state=TaskState.working),
                final=False,
                metadata=metadata,
            )
            response = SendStreamingMessageSuccessResponse(id=request_id, result=status_event)
            yield f"event: TaskStatusUpdateEvent\ndata: {json.dumps(response.model_dump(exclude_none=True))}\n\n"

        elif isinstance(event, WorkflowStepCompletedEvent):
            metadata = {"agno_event_type": "workflow_step_completed"}
            if hasattr(event, "step_name") and event.step_name:
                metadata["step_name"] = event.step_name

            status_event = TaskStatusUpdateEvent(
                task_id=task_id,
                context_id=context_id,
                status=TaskStatus(state=TaskState.working),
                final=False,
                metadata=metadata,
            )
            response = SendStreamingMessageSuccessResponse(id=request_id, result=status_event)
            yield f"event: TaskStatusUpdateEvent\ndata: {json.dumps(response.model_dump(exclude_none=True))}\n\n"

        elif isinstance(event, WorkflowStepErrorEvent):
            metadata = {"agno_event_type": "workflow_step_error"}
            if hasattr(event, "step_name") and event.step_name:
                metadata["step_name"] = event.step_name
            if hasattr(event, "error") and event.error:
                metadata["error"] = event.error

            status_event = TaskStatusUpdateEvent(
                task_id=task_id,
                context_id=context_id,
                status=TaskStatus(state=TaskState.working),
                final=False,
                metadata=metadata,
            )
            response = SendStreamingMessageSuccessResponse(id=request_id, result=status_event)
            yield f"event: TaskStatusUpdateEvent\ndata: {json.dumps(response.model_dump(exclude_none=True))}\n\n"

        # Send loop events
        elif isinstance(event, LoopExecutionStartedEvent):
            metadata = {"agno_event_type": "loop_execution_started"}
            if hasattr(event, "step_name") and event.step_name:
                metadata["step_name"] = event.step_name
            if hasattr(event, "max_iterations") and event.max_iterations:
                metadata["max_iterations"] = event.max_iterations

            status_event = TaskStatusUpdateEvent(
                task_id=task_id,
                context_id=context_id,
                status=TaskStatus(state=TaskState.working),
                final=False,
                metadata=metadata,
            )
            response = SendStreamingMessageSuccessResponse(id=request_id, result=status_event)
            yield f"event: TaskStatusUpdateEvent\ndata: {json.dumps(response.model_dump(exclude_none=True))}\n\n"

        elif isinstance(event, LoopIterationStartedEvent):
            metadata = {"agno_event_type": "loop_iteration_started"}
            if hasattr(event, "step_name") and event.step_name:
                metadata["step_name"] = event.step_name
            if hasattr(event, "iteration") and event.iteration is not None:
                metadata["iteration"] = event.iteration
            if hasattr(event, "max_iterations") and event.max_iterations:
                metadata["max_iterations"] = event.max_iterations

            status_event = TaskStatusUpdateEvent(
                task_id=task_id,
                context_id=context_id,
                status=TaskStatus(state=TaskState.working),
                final=False,
                metadata=metadata,
            )
            response = SendStreamingMessageSuccessResponse(id=request_id, result=status_event)
            yield f"event: TaskStatusUpdateEvent\ndata: {json.dumps(response.model_dump(exclude_none=True))}\n\n"

        elif isinstance(event, LoopIterationCompletedEvent):
            metadata = {"agno_event_type": "loop_iteration_completed"}
            if hasattr(event, "step_name") and event.step_name:
                metadata["step_name"] = event.step_name
            if hasattr(event, "iteration") and event.iteration is not None:
                metadata["iteration"] = event.iteration
            if hasattr(event, "should_continue") and event.should_continue is not None:
                metadata["should_continue"] = event.should_continue

            status_event = TaskStatusUpdateEvent(
                task_id=task_id,
                context_id=context_id,
                status=TaskStatus(state=TaskState.working),
                final=False,
                metadata=metadata,
            )
            response = SendStreamingMessageSuccessResponse(id=request_id, result=status_event)
            yield f"event: TaskStatusUpdateEvent\ndata: {json.dumps(response.model_dump(exclude_none=True))}\n\n"

        elif isinstance(event, LoopExecutionCompletedEvent):
            metadata = {"agno_event_type": "loop_execution_completed"}
            if hasattr(event, "step_name") and event.step_name:
                metadata["step_name"] = event.step_name
            if hasattr(event, "total_iterations") and event.total_iterations is not None:
                metadata["total_iterations"] = event.total_iterations

            status_event = TaskStatusUpdateEvent(
                task_id=task_id,
                context_id=context_id,
                status=TaskStatus(state=TaskState.working),
                final=False,
                metadata=metadata,
            )
            response = SendStreamingMessageSuccessResponse(id=request_id, result=status_event)
            yield f"event: TaskStatusUpdateEvent\ndata: {json.dumps(response.model_dump(exclude_none=True))}\n\n"

        # Send parallel events
        elif isinstance(event, ParallelExecutionStartedEvent):
            metadata = {"agno_event_type": "parallel_execution_started"}
            if hasattr(event, "step_name") and event.step_name:
                metadata["step_name"] = event.step_name
            if hasattr(event, "parallel_step_count") and event.parallel_step_count:
                metadata["parallel_step_count"] = event.parallel_step_count

            status_event = TaskStatusUpdateEvent(
                task_id=task_id,
                context_id=context_id,
                status=TaskStatus(state=TaskState.working),
                final=False,
                metadata=metadata,
            )
            response = SendStreamingMessageSuccessResponse(id=request_id, result=status_event)
            yield f"event: TaskStatusUpdateEvent\ndata: {json.dumps(response.model_dump(exclude_none=True))}\n\n"

        elif isinstance(event, ParallelExecutionCompletedEvent):
            metadata = {"agno_event_type": "parallel_execution_completed"}
            if hasattr(event, "step_name") and event.step_name:
                metadata["step_name"] = event.step_name
            if hasattr(event, "parallel_step_count") and event.parallel_step_count:
                metadata["parallel_step_count"] = event.parallel_step_count

            status_event = TaskStatusUpdateEvent(
                task_id=task_id,
                context_id=context_id,
                status=TaskStatus(state=TaskState.working),
                final=False,
                metadata=metadata,
            )
            response = SendStreamingMessageSuccessResponse(id=request_id, result=status_event)
            yield f"event: TaskStatusUpdateEvent\ndata: {json.dumps(response.model_dump(exclude_none=True))}\n\n"

        # Send condition events
        elif isinstance(event, ConditionExecutionStartedEvent):
            metadata = {"agno_event_type": "condition_execution_started"}
            if hasattr(event, "step_name") and event.step_name:
                metadata["step_name"] = event.step_name
            if hasattr(event, "condition_result") and event.condition_result is not None:
                metadata["condition_result"] = event.condition_result

            status_event = TaskStatusUpdateEvent(
                task_id=task_id,
                context_id=context_id,
                status=TaskStatus(state=TaskState.working),
                final=False,
                metadata=metadata,
            )
            response = SendStreamingMessageSuccessResponse(id=request_id, result=status_event)
            yield f"event: TaskStatusUpdateEvent\ndata: {json.dumps(response.model_dump(exclude_none=True))}\n\n"

        elif isinstance(event, ConditionExecutionCompletedEvent):
            metadata = {"agno_event_type": "condition_execution_completed"}
            if hasattr(event, "step_name") and event.step_name:
                metadata["step_name"] = event.step_name
            if hasattr(event, "condition_result") and event.condition_result is not None:
                metadata["condition_result"] = event.condition_result
            if hasattr(event, "executed_steps") and event.executed_steps is not None:
                metadata["executed_steps"] = event.executed_steps

            status_event = TaskStatusUpdateEvent(
                task_id=task_id,
                context_id=context_id,
                status=TaskStatus(state=TaskState.working),
                final=False,
                metadata=metadata,
            )
            response = SendStreamingMessageSuccessResponse(id=request_id, result=status_event)
            yield f"event: TaskStatusUpdateEvent\ndata: {json.dumps(response.model_dump(exclude_none=True))}\n\n"

        # Send router events
        elif isinstance(event, RouterExecutionStartedEvent):
            metadata = {"agno_event_type": "router_execution_started"}
            if hasattr(event, "step_name") and event.step_name:
                metadata["step_name"] = event.step_name
            if hasattr(event, "selected_steps") and event.selected_steps:
                metadata["selected_steps"] = event.selected_steps

            status_event = TaskStatusUpdateEvent(
                task_id=task_id,
                context_id=context_id,
                status=TaskStatus(state=TaskState.working),
                final=False,
                metadata=metadata,
            )
            response = SendStreamingMessageSuccessResponse(id=request_id, result=status_event)
            yield f"event: TaskStatusUpdateEvent\ndata: {json.dumps(response.model_dump(exclude_none=True))}\n\n"

        elif isinstance(event, RouterExecutionCompletedEvent):
            metadata = {"agno_event_type": "router_execution_completed"}
            if hasattr(event, "step_name") and event.step_name:
                metadata["step_name"] = event.step_name
            if hasattr(event, "selected_steps") and event.selected_steps:
                metadata["selected_steps"] = event.selected_steps
            if hasattr(event, "executed_steps") and event.executed_steps is not None:
                metadata["executed_steps"] = event.executed_steps

            status_event = TaskStatusUpdateEvent(
                task_id=task_id,
                context_id=context_id,
                status=TaskStatus(state=TaskState.working),
                final=False,
                metadata=metadata,
            )
            response = SendStreamingMessageSuccessResponse(id=request_id, result=status_event)
            yield f"event: TaskStatusUpdateEvent\ndata: {json.dumps(response.model_dump(exclude_none=True))}\n\n"

        # Send steps events
        elif isinstance(event, StepsExecutionStartedEvent):
            metadata = {"agno_event_type": "steps_execution_started"}
            if hasattr(event, "step_name") and event.step_name:
                metadata["step_name"] = event.step_name
            if hasattr(event, "steps_count") and event.steps_count:
                metadata["steps_count"] = event.steps_count

            status_event = TaskStatusUpdateEvent(
                task_id=task_id,
                context_id=context_id,
                status=TaskStatus(state=TaskState.working),
                final=False,
                metadata=metadata,
            )
            response = SendStreamingMessageSuccessResponse(id=request_id, result=status_event)
            yield f"event: TaskStatusUpdateEvent\ndata: {json.dumps(response.model_dump(exclude_none=True))}\n\n"

        elif isinstance(event, StepsExecutionCompletedEvent):
            metadata = {"agno_event_type": "steps_execution_completed"}
            if hasattr(event, "step_name") and event.step_name:
                metadata["step_name"] = event.step_name
            if hasattr(event, "steps_count") and event.steps_count:
                metadata["steps_count"] = event.steps_count
            if hasattr(event, "executed_steps") and event.executed_steps is not None:
                metadata["executed_steps"] = event.executed_steps

            status_event = TaskStatusUpdateEvent(
                task_id=task_id,
                context_id=context_id,
                status=TaskStatus(state=TaskState.working),
                final=False,
                metadata=metadata,
            )
            response = SendStreamingMessageSuccessResponse(id=request_id, result=status_event)
            yield f"event: TaskStatusUpdateEvent\ndata: {json.dumps(response.model_dump(exclude_none=True))}\n\n"

        # Capture completion event for final task construction
        elif isinstance(event, (RunCompletedEvent, TeamRunCompletedEvent, WorkflowCompletedEvent)):
            completion_event = event

        # Capture cancelled event for final task construction
        elif isinstance(event, (RunCancelledEvent, TeamRunCancelledEvent, WorkflowCancelledEvent)):
            cancelled_event = event

    # 3. Send final status event
    # If cancelled, send canceled status; otherwise send completed
    if cancelled_event:
        final_state = TaskState.canceled
        metadata = {"agno_event_type": "run_cancelled"}
        if hasattr(cancelled_event, "reason") and cancelled_event.reason:
            metadata["reason"] = cancelled_event.reason
        final_status_event = TaskStatusUpdateEvent(
            task_id=task_id,
            context_id=context_id,
            status=TaskStatus(state=final_state),
            final=True,
            metadata=metadata,
        )
    else:
        final_status_event = TaskStatusUpdateEvent(
            task_id=task_id,
            context_id=context_id,
            status=TaskStatus(state=TaskState.completed),
            final=True,
        )
    response = SendStreamingMessageSuccessResponse(id=request_id, result=final_status_event)
    yield f"event: TaskStatusUpdateEvent\ndata: {json.dumps(response.model_dump(exclude_none=True))}\n\n"

    # 4. Send final task
    # Handle cancelled case
    if cancelled_event:
        cancel_message = "Run was cancelled"
        if hasattr(cancelled_event, "reason") and cancelled_event.reason:
            cancel_message = f"Run was cancelled: {cancelled_event.reason}"

        parts: List[Part] = []
        if accumulated_content:
            parts.append(Part(root=TextPart(text=accumulated_content)))
        parts.append(Part(root=TextPart(text=cancel_message)))

        final_message = A2AMessage(
            message_id=message_id,
            role=Role.agent,
            parts=parts,
            context_id=context_id,
            task_id=task_id,
            metadata={"agno_event_type": "run_cancelled"},
        )

        task = Task(
            id=task_id,
            context_id=context_id,
            status=TaskStatus(state=TaskState.canceled),
            history=[final_message],
        )
        response = SendStreamingMessageSuccessResponse(id=request_id, result=task)
        yield f"event: Task\ndata: {json.dumps(response.model_dump(exclude_none=True))}\n\n"
        return

    # Build from completion_event if available, otherwise use accumulated content
    if completion_event:
        final_content = completion_event.content if completion_event.content else accumulated_content

        final_parts: List[Part] = []
        if final_content:
            final_parts.append(Part(root=TextPart(text=str(final_content))))

        # Handle all media artifacts
        artifacts: List[Artifact] = []
        if hasattr(completion_event, "images") and completion_event.images:
            for idx, image in enumerate(completion_event.images):
                artifact_parts = []
                if image.url:
                    artifact_parts.append(Part(root=FilePart(file=FileWithUri(uri=image.url, mime_type="image/*"))))
                artifacts.append(
                    Artifact(
                        artifact_id=f"image-{idx}",
                        name=getattr(image, "name", None) or f"image-{idx}",
                        description="Image generated during task",
                        parts=artifact_parts,
                    )
                )
        if hasattr(completion_event, "videos") and completion_event.videos:
            for idx, video in enumerate(completion_event.videos):
                artifact_parts = []
                if video.url:
                    artifact_parts.append(Part(root=FilePart(file=FileWithUri(uri=video.url, mime_type="video/*"))))
                artifacts.append(
                    Artifact(
                        artifact_id=f"video-{idx}",
                        name=getattr(video, "name", None) or f"video-{idx}",
                        description="Video generated during task",
                        parts=artifact_parts,
                    )
                )
        if hasattr(completion_event, "audio") and completion_event.audio:
            for idx, audio in enumerate(completion_event.audio):
                artifact_parts = []
                if audio.url:
                    artifact_parts.append(Part(root=FilePart(file=FileWithUri(uri=audio.url, mime_type="audio/*"))))
                artifacts.append(
                    Artifact(
                        artifact_id=f"audio-{idx}",
                        name=getattr(audio, "name", None) or f"audio-{idx}",
                        description="Audio generated during task",
                        parts=artifact_parts,
                    )
                )
        if hasattr(completion_event, "response_audio") and completion_event.response_audio:
            audio = completion_event.response_audio
            artifact_parts = []
            if audio.url:
                artifact_parts.append(Part(root=FilePart(file=FileWithUri(uri=audio.url, mime_type="audio/*"))))
            artifacts.append(
                Artifact(
                    artifact_id="response-audio",
                    name=getattr(audio, "name", None) or "response-audio",
                    description="Audio response from agent",
                    parts=artifact_parts,
                )
            )

        # Handle all other data as Message metadata
        final_metadata: Dict[str, Any] = {}
        if hasattr(completion_event, "metrics") and completion_event.metrics:  # type: ignore
            final_metadata["metrics"] = completion_event.metrics.to_dict()  # type: ignore
        if hasattr(completion_event, "metadata") and completion_event.metadata:
            final_metadata.update(completion_event.metadata)

        final_message = A2AMessage(
            message_id=message_id,
            role=Role.agent,
            parts=final_parts,
            context_id=context_id,
            task_id=task_id,
            metadata=final_metadata if final_metadata else None,
        )

    else:
        # Fallback in case we didn't find the completion event, using accumulated content
        final_message = A2AMessage(
            message_id=message_id,
            role=Role.agent,
            parts=[Part(root=TextPart(text=accumulated_content))] if accumulated_content else [],
            context_id=context_id,
            task_id=task_id,
        )
        artifacts = []

    # Build and return the final Task
    task = Task(
        id=task_id,
        context_id=context_id,
        status=TaskStatus(state=TaskState.completed),
        history=[final_message],
        artifacts=artifacts if artifacts else None,
    )
    response = SendStreamingMessageSuccessResponse(id=request_id, result=task)
    yield f"event: Task\ndata: {json.dumps(response.model_dump(exclude_none=True))}\n\n"


async def stream_a2a_response_with_error_handling(
    event_stream: AsyncIterator[Union[RunOutputEvent, TeamRunOutputEvent, WorkflowRunOutputEvent, RunOutput]],
    request_id: Union[str, int],
) -> AsyncIterator[str]:
    """Wrapper around stream_a2a_response to handle critical errors."""
    task_id: str = str(uuid4())
    context_id: str = str(uuid4())

    try:
        async for response_chunk in stream_a2a_response(event_stream, request_id):
            yield response_chunk

    # Catch any critical errors, emit the expected status task and close the stream
    except Exception as e:
        failed_status_event = TaskStatusUpdateEvent(
            task_id=task_id,
            context_id=context_id,
            status=TaskStatus(state=TaskState.failed),
            final=True,
        )
        response = SendStreamingMessageSuccessResponse(id=request_id, result=failed_status_event)
        yield f"event: TaskStatusUpdateEvent\ndata: {json.dumps(response.model_dump(exclude_none=True))}\n\n"

        # Send failed Task
        error_message = A2AMessage(
            message_id=str(uuid4()),
            role=Role.agent,
            parts=[Part(root=TextPart(text=f"Error: {str(e)}"))],
            context_id=context_id,
        )
        failed_task = Task(
            id=task_id,
            context_id=context_id,
            status=TaskStatus(state=TaskState.failed),
            history=[error_message],
        )

        response = SendStreamingMessageSuccessResponse(id=request_id, result=failed_task)
        yield f"event: Task\ndata: {json.dumps(response.model_dump(exclude_none=True))}\n\n"
