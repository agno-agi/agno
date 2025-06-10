from typing import Any, List, Optional

from agno.media import AudioResponse, ImageArtifact
from agno.models.message import Citations
from agno.models.response import ToolExecution
from agno.reasoning.step import ReasoningStep
from agno.run.response import (
    MemoryUpdateCompletedEvent,
    MemoryUpdateStartedEvent,
    ReasoningCompletedEvent,
    ReasoningStartedEvent,
    ReasoningStepEvent,
    RunResponse,
    RunResponseCancelledEvent,
    RunResponseCompletedEvent,
    RunResponseContentEvent,
    RunResponseContinuedEvent,
    RunResponseErrorEvent,
    RunResponsePausedEvent,
    RunResponseStartedEvent,
    ToolCallCompletedEvent,
    ToolCallStartedEvent,
)
from agno.run.team import MemoryUpdateCompletedEvent as TeamMemoryUpdateCompletedEvent
from agno.run.team import MemoryUpdateStartedEvent as TeamMemoryUpdateStartedEvent
from agno.run.team import ReasoningCompletedEvent as TeamReasoningCompletedEvent
from agno.run.team import ReasoningStartedEvent as TeamReasoningStartedEvent
from agno.run.team import ReasoningStepEvent as TeamReasoningStepEvent
from agno.run.team import RunResponseCancelledEvent as TeamRunResponseCancelledEvent
from agno.run.team import RunResponseCompletedEvent as TeamRunResponseCompletedEvent
from agno.run.team import RunResponseContentEvent as TeamRunResponseContentEvent
from agno.run.team import RunResponseErrorEvent as TeamRunResponseErrorEvent
from agno.run.team import RunResponseStartedEvent as TeamRunResponseStartedEvent
from agno.run.team import TeamRunResponse
from agno.run.team import ToolCallCompletedEvent as TeamToolCallCompletedEvent
from agno.run.team import ToolCallStartedEvent as TeamToolCallStartedEvent


def create_team_run_response_started_event(from_run_response: TeamRunResponse) -> TeamRunResponseStartedEvent:
    return TeamRunResponseStartedEvent(
        session_id=from_run_response.session_id,
        team_id=from_run_response.team_id,  # type: ignore
        run_id=from_run_response.run_id,
        model=from_run_response.model,  # type: ignore
        model_provider=from_run_response.model_provider,  # type: ignore
    )


def create_run_response_started_event(from_run_response: RunResponse) -> RunResponseStartedEvent:
    return RunResponseStartedEvent(
        session_id=from_run_response.session_id,
        agent_id=from_run_response.agent_id,  # type: ignore
        run_id=from_run_response.run_id,
        model=from_run_response.model,  # type: ignore
        model_provider=from_run_response.model_provider,  # type: ignore
    )


def create_team_run_response_completed_event(from_run_response: TeamRunResponse) -> TeamRunResponseCompletedEvent:
    return TeamRunResponseCompletedEvent(
        session_id=from_run_response.session_id,
        team_id=from_run_response.team_id,  # type: ignore
        run_id=from_run_response.run_id,
        content=from_run_response.content,  # type: ignore
        reasoning_content=from_run_response.reasoning_content,  # type: ignore
        thinking=from_run_response.thinking,  # type: ignore
        citations=from_run_response.citations,  # type: ignore
        images=from_run_response.images,  # type: ignore
        videos=from_run_response.videos,  # type: ignore
        audio=from_run_response.audio,  # type: ignore
        response_audio=from_run_response.response_audio,  # type: ignore
        extra_data=from_run_response.extra_data,  # type: ignore
        member_responses=from_run_response.member_responses,  # type: ignore
    )


def create_run_response_completed_event(from_run_response: RunResponse) -> RunResponseCompletedEvent:
    return RunResponseCompletedEvent(
        session_id=from_run_response.session_id,
        agent_id=from_run_response.agent_id,  # type: ignore
        run_id=from_run_response.run_id,
        content=from_run_response.content,  # type: ignore
        reasoning_content=from_run_response.reasoning_content,  # type: ignore
        thinking=from_run_response.thinking,  # type: ignore
        citations=from_run_response.citations,  # type: ignore
        images=from_run_response.images,  # type: ignore
        videos=from_run_response.videos,  # type: ignore
        audio=from_run_response.audio,  # type: ignore
        response_audio=from_run_response.response_audio,  # type: ignore
        extra_data=from_run_response.extra_data,  # type: ignore
    )


def create_run_response_paused_event(
    from_run_response: RunResponse, tools: Optional[List[ToolExecution]] = None
) -> RunResponsePausedEvent:
    return RunResponsePausedEvent(
        session_id=from_run_response.session_id,
        agent_id=from_run_response.agent_id,  # type: ignore
        run_id=from_run_response.run_id,
        tools=tools,
    )


def create_run_response_continued_event(from_run_response: RunResponse) -> RunResponseContinuedEvent:
    return RunResponseContinuedEvent(
        session_id=from_run_response.session_id,
        agent_id=from_run_response.agent_id,  # type: ignore
        run_id=from_run_response.run_id,
    )


def create_team_run_response_error_event(from_run_response: TeamRunResponse, error: str) -> TeamRunResponseErrorEvent:
    return TeamRunResponseErrorEvent(
        session_id=from_run_response.session_id,
        team_id=from_run_response.team_id,  # type: ignore
        run_id=from_run_response.run_id,
        content=error,
    )


def create_run_response_error_event(from_run_response: RunResponse, error: str) -> RunResponseErrorEvent:
    return RunResponseErrorEvent(
        session_id=from_run_response.session_id,
        agent_id=from_run_response.agent_id,  # type: ignore
        run_id=from_run_response.run_id,
        content=error,
    )


def create_team_run_response_cancelled_event(
    from_run_response: TeamRunResponse, reason: str
) -> TeamRunResponseCancelledEvent:
    return TeamRunResponseCancelledEvent(
        session_id=from_run_response.session_id,
        team_id=from_run_response.team_id,  # type: ignore
        run_id=from_run_response.run_id,
        reason=reason,
    )


def create_run_response_cancelled_event(from_run_response: RunResponse, reason: str) -> RunResponseCancelledEvent:
    return RunResponseCancelledEvent(
        session_id=from_run_response.session_id,
        agent_id=from_run_response.agent_id,  # type: ignore
        run_id=from_run_response.run_id,
        reason=reason,
    )


def create_memory_update_started_event(from_run_response: RunResponse) -> MemoryUpdateStartedEvent:
    return MemoryUpdateStartedEvent(
        session_id=from_run_response.session_id,
        agent_id=from_run_response.agent_id,  # type: ignore
        run_id=from_run_response.run_id,
    )


def create_team_memory_update_started_event(from_run_response: TeamRunResponse) -> TeamMemoryUpdateStartedEvent:
    return TeamMemoryUpdateStartedEvent(
        session_id=from_run_response.session_id,
        team_id=from_run_response.team_id,  # type: ignore
        run_id=from_run_response.run_id,
    )


def create_memory_update_completed_event(from_run_response: RunResponse) -> MemoryUpdateCompletedEvent:
    return MemoryUpdateCompletedEvent(
        session_id=from_run_response.session_id,
        agent_id=from_run_response.agent_id,  # type: ignore
        run_id=from_run_response.run_id,
    )


def create_team_memory_update_completed_event(from_run_response: TeamRunResponse) -> TeamMemoryUpdateCompletedEvent:
    return TeamMemoryUpdateCompletedEvent(
        session_id=from_run_response.session_id,
        team_id=from_run_response.team_id,  # type: ignore
        run_id=from_run_response.run_id,
    )


def create_reasoning_started_event(from_run_response: RunResponse) -> ReasoningStartedEvent:
    return ReasoningStartedEvent(
        session_id=from_run_response.session_id,
        agent_id=from_run_response.agent_id,  # type: ignore
        run_id=from_run_response.run_id,
    )


def create_team_reasoning_started_event(from_run_response: TeamRunResponse) -> TeamReasoningStartedEvent:
    return TeamReasoningStartedEvent(
        session_id=from_run_response.session_id,
        team_id=from_run_response.team_id,  # type: ignore
        run_id=from_run_response.run_id,
    )


def create_reasoning_step_event(
    from_run_response: RunResponse, reasoning_step: ReasoningStep, reasoning_content: str
) -> ReasoningStepEvent:
    return ReasoningStepEvent(
        session_id=from_run_response.session_id,
        agent_id=from_run_response.agent_id,  # type: ignore
        run_id=from_run_response.run_id,
        content=reasoning_step,
        content_type=reasoning_step.__class__.__name__,
        reasoning_content=reasoning_content,
    )


def create_team_reasoning_step_event(
    from_run_response: TeamRunResponse, reasoning_step: ReasoningStep, reasoning_content: str
) -> TeamReasoningStepEvent:
    return TeamReasoningStepEvent(
        session_id=from_run_response.session_id,
        team_id=from_run_response.team_id,  # type: ignore
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
        agent_id=from_run_response.agent_id,  # type: ignore
        run_id=from_run_response.run_id,
        content=content,
        content_type=content_type or "str",
    )


def create_team_reasoning_completed_event(
    from_run_response: TeamRunResponse, content: Optional[Any] = None, content_type: Optional[str] = None
) -> TeamReasoningCompletedEvent:
    return TeamReasoningCompletedEvent(
        session_id=from_run_response.session_id,
        team_id=from_run_response.team_id,  # type: ignore
        run_id=from_run_response.run_id,
        content=content,
        content_type=content_type or "str",
    )


def create_tool_call_started_event(from_run_response: RunResponse, tool: ToolExecution) -> ToolCallStartedEvent:
    return ToolCallStartedEvent(
        session_id=from_run_response.session_id,
        agent_id=from_run_response.agent_id,  # type: ignore
        run_id=from_run_response.run_id,
        tool=tool,
    )


def create_team_tool_call_started_event(
    from_run_response: TeamRunResponse, tool: ToolExecution
) -> TeamToolCallStartedEvent:
    return TeamToolCallStartedEvent(
        session_id=from_run_response.session_id,
        team_id=from_run_response.team_id,  # type: ignore
        run_id=from_run_response.run_id,
        tool=tool,
    )


def create_tool_call_completed_event(
    from_run_response: RunResponse, tool: ToolExecution, content: Optional[Any] = None
) -> ToolCallCompletedEvent:
    return ToolCallCompletedEvent(
        session_id=from_run_response.session_id,
        agent_id=from_run_response.agent_id,  # type: ignore
        run_id=from_run_response.run_id,
        tool=tool,
        content=content,
        images=from_run_response.images,
        videos=from_run_response.videos,
        audio=from_run_response.audio,
    )


def create_team_tool_call_completed_event(
    from_run_response: TeamRunResponse, tool: ToolExecution, content: Optional[Any] = None
) -> TeamToolCallCompletedEvent:
    return TeamToolCallCompletedEvent(
        session_id=from_run_response.session_id,
        team_id=from_run_response.team_id,  # type: ignore
        run_id=from_run_response.run_id,
        tool=tool,
        content=content,
        images=from_run_response.images,
        videos=from_run_response.videos,
        audio=from_run_response.audio,
    )


def create_run_response_content_event(
    from_run_response: RunResponse,
    content: Optional[Any] = None,
    thinking: Optional[str] = None,
    redacted_thinking: Optional[str] = None,
    citations: Optional[Citations] = None,
    response_audio: Optional[AudioResponse] = None,
    image: Optional[ImageArtifact] = None,
) -> RunResponseContentEvent:
    thinking_combined = (thinking or "") + (redacted_thinking or "")
    return RunResponseContentEvent(
        session_id=from_run_response.session_id,
        agent_id=from_run_response.agent_id,  # type: ignore
        run_id=from_run_response.run_id,
        content=content,
        thinking=thinking_combined,
        citations=citations,
        response_audio=response_audio,
        image=image,
        extra_data=from_run_response.extra_data,
    )


def create_team_run_response_content_event(
    from_run_response: TeamRunResponse,
    content: Optional[Any] = None,
    thinking: Optional[str] = None,
    redacted_thinking: Optional[str] = None,
    citations: Optional[Citations] = None,
    response_audio: Optional[AudioResponse] = None,
    image: Optional[ImageArtifact] = None,
) -> TeamRunResponseContentEvent:
    thinking_combined = (thinking or "") + (redacted_thinking or "")
    return TeamRunResponseContentEvent(
        session_id=from_run_response.session_id,
        team_id=from_run_response.team_id,  # type: ignore
        run_id=from_run_response.run_id,
        content=content,
        thinking=thinking_combined,
        citations=citations,
        response_audio=response_audio,
        image=image,
        extra_data=from_run_response.extra_data,
    )
