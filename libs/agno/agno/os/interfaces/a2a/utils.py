"""Utilities for the Agno A2A interface — targets a2a-sdk 1.0 (protobuf-based types)."""

import json
from typing import Any, Dict, Optional, cast
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
        Message,
        Part,
        Role,
        Task,
        TaskState,
        TaskStatus,
        TaskStatusUpdateEvent,
    )
    from google.protobuf import json_format
except ImportError as e:
    raise ImportError("`a2a-sdk>=1.0` is required. Install with `pip install -U 'a2a-sdk>=1.0'`.") from e


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
from agno.run.base import RunStatus


# --- proto <-> wire helpers ----------------------------------------------------


def _proto_to_jsonable(msg) -> dict:
    return json_format.MessageToDict(
        msg,
        preserving_proto_field_name=False,
        always_print_fields_with_no_presence=False,
    )


def _jsonrpc_envelope(request_id: Union[str, int], result_msg) -> dict:
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "result": _proto_to_jsonable(result_msg),
    }


def _sse_event(event_name: str, request_id: Union[str, int], result_msg) -> str:
    return f"event: {event_name}\ndata: {json.dumps(_jsonrpc_envelope(request_id, result_msg))}\n\n"


def _set_struct(struct_field, py_dict: Optional[Dict[str, Any]]) -> None:
    if py_dict:
        struct_field.update(py_dict)


# --- Part / Message factories --------------------------------------------------


def _text_part(text: str, *, part_metadata: Optional[Dict[str, Any]] = None) -> Part:
    p = Part(text=text, media_type="text/plain")
    _set_struct(p.metadata, part_metadata)
    return p


def _file_part_from_url(url: str, media_type: str, *, filename: Optional[str] = None) -> Part:
    if filename:
        return Part(url=url, media_type=media_type, filename=filename)
    return Part(url=url, media_type=media_type)


def _file_part_from_bytes(raw: bytes, media_type: str, *, filename: Optional[str] = None) -> Part:
    if filename:
        return Part(raw=raw, media_type=media_type, filename=filename)
    return Part(raw=raw, media_type=media_type)


def _build_agent_message(
    *,
    parts: List[Part],
    context_id: Optional[str] = None,
    task_id: Optional[str] = None,
    message_id: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> Message:
    msg = Message(
        message_id=message_id or str(uuid4()),
        role=Role.ROLE_AGENT,
        context_id=context_id or "",
        task_id=task_id or "",
        parts=parts,
    )
    _set_struct(msg.metadata, metadata)
    return msg


def _status_update(
    task_id: str,
    context_id: str,
    state: int,
    metadata: Optional[Dict[str, Any]] = None,
) -> TaskStatusUpdateEvent:
    evt = TaskStatusUpdateEvent(
        task_id=task_id,
        context_id=context_id,
        status=TaskStatus(state=state),  # type: ignore[arg-type]
    )
    _set_struct(evt.metadata, metadata)
    return evt


# --- request parsing -----------------------------------------------------------


async def map_a2a_request_to_run_input(request_body: dict, stream: bool = True) -> RunInput:
    """Map an A2A v1 JSON-RPC SendMessage request body to an Agno RunInput.

    Request body shape (JSON-RPC 2.0):

        {
            "jsonrpc": "2.0",
            "id": "...",
            "method": "message/send" | "message/stream",
            "params": {
                "message": {
                    "messageId": "...",
                    "role": "ROLE_USER",
                    "contextId": "...",
                    "parts": [{"text": "Hello", "mediaType": "text/plain"}]
                }
            }
        }
    """
    del stream  # v1 SendMessageRequest is the same for blocking and streaming
    params = request_body.get("params") or {}
    raw_message = params.get("message")
    if not raw_message:
        raise HTTPException(status_code=400, detail="Invalid A2A request: params.message is required")

    # Accept legacy lowercase role names ("user" / "agent") in addition to v1 enum names
    # ("ROLE_USER" / "ROLE_AGENT"). Protobuf's ParseDict only accepts the latter.
    role_value = raw_message.get("role")
    if isinstance(role_value, str) and not role_value.startswith("ROLE_"):
        raw_message = {**raw_message, "role": f"ROLE_{role_value.upper()}"}

    a2a_message = Message()
    try:
        json_format.ParseDict(raw_message, a2a_message, ignore_unknown_fields=True)
    except json_format.ParseError as e:
        raise HTTPException(status_code=400, detail=f"Invalid A2A request: {e}")

    if a2a_message.role != Role.ROLE_USER:
        raise HTTPException(status_code=400, detail="Only user messages are accepted")

    text_parts: List[str] = []
    images: List[Image] = []
    videos: List[Video] = []
    audios: List[Audio] = []
    files: List[File] = []

    for part in a2a_message.parts:
        which = part.WhichOneof("content")
        if which == "text":
            text_parts.append(part.text)
        elif which == "url":
            mt = part.media_type or ""
            if mt.startswith("image/"):
                images.append(Image(url=part.url))
            elif mt.startswith("video/"):
                videos.append(Video(url=part.url))
            elif mt.startswith("audio/"):
                audios.append(Audio(url=part.url))
            elif mt:
                files.append(File(url=part.url, mime_type=mt))
        elif which == "raw":
            mt = part.media_type or ""
            if mt:
                files.append(File(content=part.raw, mime_type=mt))
        elif which == "data":
            data_dict = json_format.MessageToDict(part.data) if part.HasField("data") else {}
            text_parts.append(json.dumps(data_dict))

    return RunInput(
        input_content="\n".join(text_parts) if text_parts else "",
        images=images if images else None,
        videos=videos if videos else None,
        audios=audios if audios else None,
        files=files if files else None,
    )


# --- run output -> A2A task ----------------------------------------------------


def _map_run_status_to_task_state(status: Optional[RunStatus]) -> int:
    if status is None:
        return TaskState.TASK_STATE_COMPLETED
    _mapping = {
        RunStatus.pending: TaskState.TASK_STATE_SUBMITTED,
        RunStatus.running: TaskState.TASK_STATE_WORKING,
        RunStatus.completed: TaskState.TASK_STATE_COMPLETED,
        RunStatus.error: TaskState.TASK_STATE_FAILED,
        RunStatus.cancelled: TaskState.TASK_STATE_CANCELED,
        RunStatus.paused: TaskState.TASK_STATE_WORKING,
    }
    return _mapping.get(status, TaskState.TASK_STATE_COMPLETED)


def _media_artifacts(items, default_media_type: str, name_prefix: str) -> List[Artifact]:
    out: List[Artifact] = []
    for idx, item in enumerate(items):
        artifact_parts: List[Part] = []
        if getattr(item, "url", None):
            artifact_parts.append(_file_part_from_url(item.url, default_media_type))
        out.append(
            Artifact(
                artifact_id=str(uuid4()),
                name=f"{name_prefix}_{idx}",
                description=f"Generated {name_prefix} {idx}",
                parts=artifact_parts,
            )
        )
    return out


def map_run_output_to_a2a_task(run_output: Union[RunOutput, WorkflowRunOutput]) -> Task:
    parts: List[Part] = []
    if run_output.content:
        parts.append(_text_part(str(run_output.content)))

    artifacts: List[Artifact] = []
    if hasattr(run_output, "images") and run_output.images:
        artifacts.extend(_media_artifacts(run_output.images, "image/jpeg", "image"))
    if hasattr(run_output, "videos") and run_output.videos:
        artifacts.extend(_media_artifacts(run_output.videos, "video/mp4", "video"))
    if hasattr(run_output, "audio") and run_output.audio:
        artifacts.extend(_media_artifacts(run_output.audio, "audio/mpeg", "audio"))
    if hasattr(run_output, "files") and run_output.files:
        for idx, file in enumerate(run_output.files):
            artifact_parts: List[Part] = []
            if file.url:
                artifact_parts.append(
                    _file_part_from_url(
                        file.url,
                        file.mime_type or "application/octet-stream",
                        filename=getattr(file, "name", None),
                    )
                )
            artifacts.append(
                Artifact(
                    artifact_id=str(uuid4()),
                    name=getattr(file, "name", None) or f"file_{idx}",
                    description=f"Generated file {idx}",
                    parts=artifact_parts,
                )
            )

    metadata: Dict[str, Any] = {}
    if hasattr(run_output, "user_id") and run_output.user_id:
        metadata["userId"] = run_output.user_id

    agent_message = _build_agent_message(
        parts=parts,
        context_id=run_output.session_id,
        task_id=run_output.run_id,
        metadata=metadata or None,
    )

    run_id = cast(str, run_output.run_id) if run_output.run_id else str(uuid4())
    session_id = cast(str, run_output.session_id) if run_output.session_id else str(uuid4())
    run_status = getattr(run_output, "status", None)
    task_state = _map_run_status_to_task_state(run_status)

    task = Task(
        id=run_id,
        context_id=session_id,
        status=TaskStatus(state=task_state),  # type: ignore[arg-type]
        history=[agent_message],
    )
    if artifacts:
        task.artifacts.extend(artifacts)
    return task


# --- streaming -----------------------------------------------------------------


async def stream_a2a_response(
    event_stream: AsyncIterator[Union[RunOutputEvent, TeamRunOutputEvent, WorkflowRunOutputEvent, RunOutput]],
    request_id: Union[str, int],
) -> AsyncIterator[str]:
    """Yield SSE-formatted v1 A2A stream events wrapped in JSON-RPC envelopes.

    Note: v1 dropped the `final` flag on TaskStatusUpdateEvent. Stream closure
    is the completion signal.
    """
    task_id: str = str(uuid4())
    context_id: str = str(uuid4())
    message_id: str = str(uuid4())
    accumulated_content = ""
    completion_event = None
    cancelled_event = None

    def _emit_status_metadata(meta: Dict[str, Any]) -> str:
        evt = _status_update(task_id, context_id, TaskState.TASK_STATE_WORKING, metadata=meta)
        return _sse_event("TaskStatusUpdateEvent", request_id, evt)

    async for event in event_stream:
        if isinstance(event, (RunStartedEvent, TeamRunStartedEvent, WorkflowStartedEvent)):
            if hasattr(event, "run_id") and event.run_id:
                task_id = event.run_id
            if hasattr(event, "session_id") and event.session_id:
                context_id = event.session_id

            yield _sse_event(
                "TaskStatusUpdateEvent",
                request_id,
                _status_update(task_id, context_id, TaskState.TASK_STATE_WORKING),
            )

        elif isinstance(event, (RunContentEvent, TeamRunContentEvent)) and event.content:
            # Serialize content to str: Pydantic models (from output_schema) must be
            # converted before str-concatenation or TextPart construction, otherwise
            # "TypeError: can only concatenate str (not <Model>) to str" is raised.
            raw_content = event.content
            if hasattr(raw_content, "model_dump_json"):
                content_str = raw_content.model_dump_json()
            elif not isinstance(raw_content, str):
                content_str = str(raw_content)
            else:
                content_str = raw_content
            accumulated_content += content_str

            message = _build_agent_message(
                parts=[_text_part(content_str)],
                context_id=context_id,
                task_id=task_id,
                message_id=message_id,
                metadata={"agno_content_category": "content"},
            )
            yield _sse_event("Message", request_id, message)

        elif isinstance(event, (ToolCallStartedEvent, TeamToolCallStartedEvent)):
            metadata: Dict[str, Any] = {"agno_event_type": "tool_call_started"}
            if event.tool:
                metadata["tool_name"] = event.tool.tool_name or "tool"
                if hasattr(event.tool, "tool_call_id") and event.tool.tool_call_id:
                    metadata["tool_call_id"] = event.tool.tool_call_id
                if hasattr(event.tool, "tool_args") and event.tool.tool_args:
                    metadata["tool_args"] = json.dumps(event.tool.tool_args)
            yield _emit_status_metadata(metadata)

        elif isinstance(event, (ToolCallCompletedEvent, TeamToolCallCompletedEvent)):
            metadata = {"agno_event_type": "tool_call_completed"}
            if event.tool:
                metadata["tool_name"] = event.tool.tool_name or "tool"
                if hasattr(event.tool, "tool_call_id") and event.tool.tool_call_id:
                    metadata["tool_call_id"] = event.tool.tool_call_id
                if hasattr(event.tool, "tool_args") and event.tool.tool_args:
                    metadata["tool_args"] = json.dumps(event.tool.tool_args)
            yield _emit_status_metadata(metadata)

        elif isinstance(event, (ReasoningStartedEvent, TeamReasoningStartedEvent)):
            yield _emit_status_metadata({"agno_event_type": "reasoning_started"})

        elif isinstance(event, (ReasoningStepEvent, TeamReasoningStepEvent)):
            if event.reasoning_content:
                reasoning_message = _build_agent_message(
                    parts=[
                        _text_part(
                            event.reasoning_content,
                            part_metadata={
                                "step_type": event.content_type if event.content_type else "str",
                            },
                        )
                    ],
                    context_id=context_id,
                    task_id=task_id,
                    metadata={"agno_content_category": "reasoning", "agno_event_type": "reasoning_step"},
                )
                yield _sse_event("Message", request_id, reasoning_message)

        elif isinstance(event, (ReasoningCompletedEvent, TeamReasoningCompletedEvent)):
            yield _emit_status_metadata({"agno_event_type": "reasoning_completed"})

        elif isinstance(event, (MemoryUpdateStartedEvent, TeamMemoryUpdateStartedEvent)):
            yield _emit_status_metadata({"agno_event_type": "memory_update_started"})

        elif isinstance(event, (MemoryUpdateCompletedEvent, TeamMemoryUpdateCompletedEvent)):
            yield _emit_status_metadata({"agno_event_type": "memory_update_completed"})

        elif isinstance(event, WorkflowStepStartedEvent):
            metadata = {"agno_event_type": "workflow_step_started"}
            if hasattr(event, "step_name") and event.step_name:
                metadata["step_name"] = event.step_name
            yield _emit_status_metadata(metadata)

        elif isinstance(event, WorkflowStepCompletedEvent):
            metadata = {"agno_event_type": "workflow_step_completed"}
            if hasattr(event, "step_name") and event.step_name:
                metadata["step_name"] = event.step_name
            yield _emit_status_metadata(metadata)

        elif isinstance(event, WorkflowStepErrorEvent):
            metadata = {"agno_event_type": "workflow_step_error"}
            if hasattr(event, "step_name") and event.step_name:
                metadata["step_name"] = event.step_name
            if hasattr(event, "error") and event.error:
                metadata["error"] = event.error
            yield _emit_status_metadata(metadata)

        elif isinstance(event, LoopExecutionStartedEvent):
            metadata = {"agno_event_type": "loop_execution_started"}
            if hasattr(event, "step_name") and event.step_name:
                metadata["step_name"] = event.step_name
            if hasattr(event, "max_iterations") and event.max_iterations:
                metadata["max_iterations"] = event.max_iterations
            yield _emit_status_metadata(metadata)

        elif isinstance(event, LoopIterationStartedEvent):
            metadata = {"agno_event_type": "loop_iteration_started"}
            if hasattr(event, "step_name") and event.step_name:
                metadata["step_name"] = event.step_name
            if hasattr(event, "iteration") and event.iteration is not None:
                metadata["iteration"] = event.iteration
            if hasattr(event, "max_iterations") and event.max_iterations:
                metadata["max_iterations"] = event.max_iterations
            yield _emit_status_metadata(metadata)

        elif isinstance(event, LoopIterationCompletedEvent):
            metadata = {"agno_event_type": "loop_iteration_completed"}
            if hasattr(event, "step_name") and event.step_name:
                metadata["step_name"] = event.step_name
            if hasattr(event, "iteration") and event.iteration is not None:
                metadata["iteration"] = event.iteration
            if hasattr(event, "should_continue") and event.should_continue is not None:
                metadata["should_continue"] = event.should_continue
            yield _emit_status_metadata(metadata)

        elif isinstance(event, LoopExecutionCompletedEvent):
            metadata = {"agno_event_type": "loop_execution_completed"}
            if hasattr(event, "step_name") and event.step_name:
                metadata["step_name"] = event.step_name
            if hasattr(event, "total_iterations") and event.total_iterations is not None:
                metadata["total_iterations"] = event.total_iterations
            yield _emit_status_metadata(metadata)

        elif isinstance(event, ParallelExecutionStartedEvent):
            metadata = {"agno_event_type": "parallel_execution_started"}
            if hasattr(event, "step_name") and event.step_name:
                metadata["step_name"] = event.step_name
            if hasattr(event, "parallel_step_count") and event.parallel_step_count:
                metadata["parallel_step_count"] = event.parallel_step_count
            yield _emit_status_metadata(metadata)

        elif isinstance(event, ParallelExecutionCompletedEvent):
            metadata = {"agno_event_type": "parallel_execution_completed"}
            if hasattr(event, "step_name") and event.step_name:
                metadata["step_name"] = event.step_name
            if hasattr(event, "parallel_step_count") and event.parallel_step_count:
                metadata["parallel_step_count"] = event.parallel_step_count
            yield _emit_status_metadata(metadata)

        elif isinstance(event, ConditionExecutionStartedEvent):
            metadata = {"agno_event_type": "condition_execution_started"}
            if hasattr(event, "step_name") and event.step_name:
                metadata["step_name"] = event.step_name
            if hasattr(event, "condition_result") and event.condition_result is not None:
                metadata["condition_result"] = event.condition_result
            yield _emit_status_metadata(metadata)

        elif isinstance(event, ConditionExecutionCompletedEvent):
            metadata = {"agno_event_type": "condition_execution_completed"}
            if hasattr(event, "step_name") and event.step_name:
                metadata["step_name"] = event.step_name
            if hasattr(event, "condition_result") and event.condition_result is not None:
                metadata["condition_result"] = event.condition_result
            if hasattr(event, "executed_steps") and event.executed_steps is not None:
                metadata["executed_steps"] = event.executed_steps
            yield _emit_status_metadata(metadata)

        elif isinstance(event, RouterExecutionStartedEvent):
            metadata = {"agno_event_type": "router_execution_started"}
            if hasattr(event, "step_name") and event.step_name:
                metadata["step_name"] = event.step_name
            if hasattr(event, "selected_steps") and event.selected_steps:
                metadata["selected_steps"] = event.selected_steps
            yield _emit_status_metadata(metadata)

        elif isinstance(event, RouterExecutionCompletedEvent):
            metadata = {"agno_event_type": "router_execution_completed"}
            if hasattr(event, "step_name") and event.step_name:
                metadata["step_name"] = event.step_name
            if hasattr(event, "selected_steps") and event.selected_steps:
                metadata["selected_steps"] = event.selected_steps
            if hasattr(event, "executed_steps") and event.executed_steps is not None:
                metadata["executed_steps"] = event.executed_steps
            yield _emit_status_metadata(metadata)

        elif isinstance(event, StepsExecutionStartedEvent):
            metadata = {"agno_event_type": "steps_execution_started"}
            if hasattr(event, "step_name") and event.step_name:
                metadata["step_name"] = event.step_name
            if hasattr(event, "steps_count") and event.steps_count:
                metadata["steps_count"] = event.steps_count
            yield _emit_status_metadata(metadata)

        elif isinstance(event, StepsExecutionCompletedEvent):
            metadata = {"agno_event_type": "steps_execution_completed"}
            if hasattr(event, "step_name") and event.step_name:
                metadata["step_name"] = event.step_name
            if hasattr(event, "steps_count") and event.steps_count:
                metadata["steps_count"] = event.steps_count
            if hasattr(event, "executed_steps") and event.executed_steps is not None:
                metadata["executed_steps"] = event.executed_steps
            yield _emit_status_metadata(metadata)

        elif isinstance(event, (RunCompletedEvent, TeamRunCompletedEvent, WorkflowCompletedEvent)):
            completion_event = event

        elif isinstance(event, (RunCancelledEvent, TeamRunCancelledEvent, WorkflowCancelledEvent)):
            cancelled_event = event

    # Final status event
    if cancelled_event:
        final_metadata: Dict[str, Any] = {"agno_event_type": "run_cancelled"}
        if hasattr(cancelled_event, "reason") and cancelled_event.reason:
            final_metadata["reason"] = cancelled_event.reason
        final_status_event = _status_update(task_id, context_id, TaskState.TASK_STATE_CANCELED, metadata=final_metadata)
    else:
        final_status_event = _status_update(task_id, context_id, TaskState.TASK_STATE_COMPLETED)
    yield _sse_event("TaskStatusUpdateEvent", request_id, final_status_event)

    # Final Task
    if cancelled_event:
        cancel_text = "Run was cancelled"
        if hasattr(cancelled_event, "reason") and cancelled_event.reason:
            cancel_text = f"Run was cancelled: {cancelled_event.reason}"

        cancel_parts: List[Part] = []
        if accumulated_content:
            cancel_parts.append(_text_part(accumulated_content))
        cancel_parts.append(_text_part(cancel_text))

        final_message = _build_agent_message(
            parts=cancel_parts,
            context_id=context_id,
            task_id=task_id,
            message_id=message_id,
            metadata={"agno_event_type": "run_cancelled"},
        )
        task = Task(
            id=task_id,
            context_id=context_id,
            status=TaskStatus(state=TaskState.TASK_STATE_CANCELED),
            history=[final_message],
        )
        yield _sse_event("Task", request_id, task)
        return

    artifacts: List[Artifact] = []
    if completion_event:
        final_content = completion_event.content if completion_event.content else accumulated_content
        final_parts: List[Part] = []
        if final_content:
            final_parts.append(_text_part(str(final_content)))

        def _emit_media(items, mt: str, prefix: str) -> None:
            for idx, item in enumerate(items):
                ap: List[Part] = []
                if getattr(item, "url", None):
                    ap.append(_file_part_from_url(item.url, mt))
                artifacts.append(
                    Artifact(
                        artifact_id=f"{prefix}-{idx}",
                        name=getattr(item, "name", None) or f"{prefix}-{idx}",
                        description=f"{prefix.capitalize()} generated during task",
                        parts=ap,
                    )
                )

        if hasattr(completion_event, "images") and completion_event.images:
            _emit_media(completion_event.images, "image/*", "image")
        if hasattr(completion_event, "videos") and completion_event.videos:
            _emit_media(completion_event.videos, "video/*", "video")
        if hasattr(completion_event, "audio") and completion_event.audio:
            _emit_media(completion_event.audio, "audio/*", "audio")
        if hasattr(completion_event, "response_audio") and completion_event.response_audio:
            audio = completion_event.response_audio
            ap: List[Part] = []
            if audio.url:
                ap.append(_file_part_from_url(audio.url, "audio/*"))
            artifacts.append(
                Artifact(
                    artifact_id="response-audio",
                    name=getattr(audio, "name", None) or "response-audio",
                    description="Audio response from agent",
                    parts=ap,
                )
            )

        final_metadata = {}
        if hasattr(completion_event, "metrics") and completion_event.metrics:  # type: ignore
            final_metadata["metrics"] = completion_event.metrics.to_dict()  # type: ignore
        if hasattr(completion_event, "metadata") and completion_event.metadata:
            final_metadata.update(completion_event.metadata)

        final_message = _build_agent_message(
            parts=final_parts,
            context_id=context_id,
            task_id=task_id,
            message_id=message_id,
            metadata=final_metadata or None,
        )
    else:
        final_message = _build_agent_message(
            parts=[_text_part(accumulated_content)] if accumulated_content else [],
            context_id=context_id,
            task_id=task_id,
            message_id=message_id,
        )

    task = Task(
        id=task_id,
        context_id=context_id,
        status=TaskStatus(state=TaskState.TASK_STATE_COMPLETED),
        history=[final_message],
    )
    if artifacts:
        task.artifacts.extend(artifacts)
    yield _sse_event("Task", request_id, task)


async def stream_a2a_response_with_error_handling(
    event_stream: AsyncIterator[Union[RunOutputEvent, TeamRunOutputEvent, WorkflowRunOutputEvent, RunOutput]],
    request_id: Union[str, int],
) -> AsyncIterator[str]:
    """Wrapper around stream_a2a_response that surfaces critical errors as failed Task events."""
    task_id: str = str(uuid4())
    context_id: str = str(uuid4())

    try:
        async for chunk in stream_a2a_response(event_stream, request_id):
            yield chunk

    except Exception as e:
        failed_status_event = _status_update(task_id, context_id, TaskState.TASK_STATE_FAILED)
        yield _sse_event("TaskStatusUpdateEvent", request_id, failed_status_event)

        error_message = _build_agent_message(
            parts=[_text_part(f"Error: {str(e)}")],
            context_id=context_id,
        )
        failed_task = Task(
            id=task_id,
            context_id=context_id,
            status=TaskStatus(state=TaskState.TASK_STATE_FAILED),
            history=[error_message],
        )
        yield _sse_event("Task", request_id, failed_task)
