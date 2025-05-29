from typing import List, Optional, Any

from agno.media import AudioResponse, ImageArtifact
from agno.models.message import Citations
from agno.models.response import ToolExecution
from agno.reasoning.step import ReasoningStep
from agno.run.response import (
    RunResponseStartedEvent,
    RunResponse,
    RunResponseCompletedEvent,
    RunResponsePausedEvent,
    RunResponseDeltaEvent,
    RunResponseErrorEvent,
    RunResponseCancelledEvent,
    RunResponseContinuedEvent,
    MemoryUpdateStartedEvent,
    ReasoningStartedEvent,
    ReasoningStepEvent,
    ReasoningCompletedEvent,
    ToolCallStartedEvent,
    ToolCallCompletedEvent,
    MemoryUpdateCompletedEvent,
)


def create_run_response_started_event(from_run_response: RunResponse) -> RunResponseStartedEvent:
    return RunResponseStartedEvent(
        session_id=from_run_response.session_id,
        agent_id=from_run_response.agent_id,
        run_id=from_run_response.run_id,
        model=from_run_response.model,  # type: ignore
        model_provider=from_run_response.model_provider,  # type: ignore
    )


def create_run_response_completed_event(from_run_response: RunResponse) -> RunResponseCompletedEvent:
    return RunResponseCompletedEvent(
        session_id=from_run_response.session_id,
        agent_id=from_run_response.agent_id,
        run_id=from_run_response.run_id,
        content=from_run_response.content,  # type: ignore
        reasoning_content=from_run_response.reasoning_content,  # type: ignore
        images=from_run_response.images,  # type: ignore
        videos=from_run_response.videos,  # type: ignore
        audio=from_run_response.audio,  # type: ignore
        response_audio=from_run_response.response_audio,  # type: ignore
    )


def create_run_response_paused_event(
    from_run_response: RunResponse, tools: List[ToolExecution]
) -> RunResponsePausedEvent:
    return RunResponsePausedEvent(
        session_id=from_run_response.session_id,
        agent_id=from_run_response.agent_id,
        run_id=from_run_response.run_id,
        tools=tools,
    )


def create_run_response_continued_event(from_run_response: RunResponse) -> RunResponseContinuedEvent:
    return RunResponseContinuedEvent(
        session_id=from_run_response.session_id,
        agent_id=from_run_response.agent_id,
        run_id=from_run_response.run_id,
    )


def create_run_response_error_event(from_run_response: RunResponse, error: str) -> RunResponseErrorEvent:
    return RunResponseErrorEvent(
        session_id=from_run_response.session_id,
        agent_id=from_run_response.agent_id,
        run_id=from_run_response.run_id,
        error=error,
    )


def create_run_response_cancelled_event(
    from_run_response: RunResponse, reason: str
) -> RunResponseCancelledEvent:
    return RunResponseCancelledEvent(
        session_id=from_run_response.session_id,
        agent_id=from_run_response.agent_id,
        run_id=from_run_response.run_id,
        reason=reason,
    )


def create_memory_update_started_event(from_run_response: RunResponse) -> MemoryUpdateStartedEvent:
    return MemoryUpdateStartedEvent(
        session_id=from_run_response.session_id,
        agent_id=from_run_response.agent_id,
        run_id=from_run_response.run_id,
    )

def create_memory_update_completed_event(from_run_response: RunResponse) -> MemoryUpdateCompletedEvent:
    return MemoryUpdateCompletedEvent(
        session_id=from_run_response.session_id,
        agent_id=from_run_response.agent_id,
        run_id=from_run_response.run_id,
    )



def create_reasoning_started_event(from_run_response: RunResponse) -> ReasoningStartedEvent:
    return ReasoningStartedEvent(
        session_id=from_run_response.session_id,
        agent_id=from_run_response.agent_id,
        run_id=from_run_response.run_id,
    )


def create_reasoning_step_event(
    from_run_response: RunResponse, reasoning_step: ReasoningStep, reasoning_content: str
) -> ReasoningStepEvent:
    return ReasoningStepEvent(
        session_id=from_run_response.session_id,
        agent_id=from_run_response.agent_id,
        run_id=from_run_response.run_id,
        content=reasoning_step,
        content_type=reasoning_step.__class__.__name__,
        reasoning_content=reasoning_content,
    )


def create_reasoning_completed_event(
    from_run_response: RunResponse, content: Optional[Any] = None, content_type: Optional[str] = None
) -> ReasoningCompletedEvent:
    return ReasoningCompletedEvent(
        session_id=from_run_response.session_id,
        agent_id=from_run_response.agent_id,
        run_id=from_run_response.run_id,
        content=content,
        content_type=content_type,
    )


def create_tool_call_started_event(from_run_response: RunResponse, tool: ToolExecution) -> ToolCallStartedEvent:
    return ToolCallStartedEvent(
        session_id=from_run_response.session_id,
        agent_id=from_run_response.agent_id,
        run_id=from_run_response.run_id,
        tool=tool,
    )


def create_tool_call_completed_event(
    from_run_response: RunResponse, tool: ToolExecution, content: str
) -> ToolCallCompletedEvent:
    return ToolCallCompletedEvent(
        session_id=from_run_response.session_id,
        agent_id=from_run_response.agent_id,
        run_id=from_run_response.run_id,
        tool=tool,
        content=content,
    )


def create_run_response_delta_event(
    from_run_response: RunResponse,
    content: Optional[Any] = None,
    thinking: Optional[str] = None,
    redacted_thinking: Optional[str] = None,
    citations: Optional[Citations] = None,
    response_audio: Optional[AudioResponse] = None,
    image: Optional[ImageArtifact] = None,
) -> RunResponseDeltaEvent:
    thinking_combined = (thinking or "") + (redacted_thinking or "")
    return RunResponseDeltaEvent(
        session_id=from_run_response.session_id,
        agent_id=from_run_response.agent_id,
        run_id=from_run_response.run_id,
        content=content,
        thinking=thinking_combined,
        citations=citations,
        response_audio=response_audio,
        image=image,
        extra_data=from_run_response.extra_data,
    )
