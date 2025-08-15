from typing import Any, List, Optional

from agno.media import AudioResponse, ImageArtifact
from agno.models.message import Citations
from agno.models.response import ToolExecution
from agno.reasoning.step import ReasoningStep
from agno.run.response import (
    MemoryUpdateCompletedEvent,
    MemoryUpdateStartedEvent,
    ParserModelResponseCompletedEvent,
    ParserModelResponseStartedEvent,
    ReasoningCompletedEvent,
    ReasoningStartedEvent,
    ReasoningStepEvent,
    RunCancelledEvent,
    RunCompletedEvent,
    RunContentEvent,
    RunContinuedEvent,
    RunErrorEvent,
    RunOutput,
    RunPausedEvent,
    RunStartedEvent,
    ToolCallCompletedEvent,
    ToolCallStartedEvent,
)
from agno.run.team import MemoryUpdateCompletedEvent as TeamMemoryUpdateCompletedEvent
from agno.run.team import MemoryUpdateStartedEvent as TeamMemoryUpdateStartedEvent
from agno.run.team import ParserModelResponseCompletedEvent as TeamParserModelResponseCompletedEvent
from agno.run.team import ParserModelResponseStartedEvent as TeamParserModelResponseStartedEvent
from agno.run.team import ReasoningCompletedEvent as TeamReasoningCompletedEvent
from agno.run.team import ReasoningStartedEvent as TeamReasoningStartedEvent
from agno.run.team import ReasoningStepEvent as TeamReasoningStepEvent
from agno.run.team import RunCancelledEvent as TeamRunCancelledEvent
from agno.run.team import RunCompletedEvent as TeamRunCompletedEvent
from agno.run.team import RunContentEvent as TeamRunContentEvent
from agno.run.team import RunErrorEvent as TeamRunErrorEvent
from agno.run.team import RunStartedEvent as TeamRunStartedEvent
from agno.run.team import TeamRunOutput
from agno.run.team import ToolCallCompletedEvent as TeamToolCallCompletedEvent
from agno.run.team import ToolCallStartedEvent as TeamToolCallStartedEvent


def create_team_run_output_started_event(from_run_output: TeamRunOutput) -> TeamRunStartedEvent:
    return TeamRunStartedEvent(
        session_id=from_run_output.session_id,
        team_id=from_run_output.team_id,  # type: ignore
        team_name=from_run_output.team_name,  # type: ignore
        team_session_id=from_run_output.team_session_id,  # type: ignore
        run_id=from_run_output.run_id,
        model=from_run_output.model,  # type: ignore
        model_provider=from_run_output.model_provider,  # type: ignore
    )


def create_run_output_started_event(from_run_output: RunOutput) -> RunStartedEvent:
    return RunStartedEvent(
        session_id=from_run_output.session_id,
        agent_id=from_run_output.agent_id,  # type: ignore
        agent_name=from_run_output.agent_name,  # type: ignore
        team_session_id=from_run_output.team_session_id,  # type: ignore
        run_id=from_run_output.run_id,
        model=from_run_output.model,  # type: ignore
        model_provider=from_run_output.model_provider,  # type: ignore
    )


def create_team_run_output_completed_event(from_run_output: TeamRunOutput) -> TeamRunCompletedEvent:
    return TeamRunCompletedEvent(
        session_id=from_run_output.session_id,
        team_id=from_run_output.team_id,  # type: ignore
        team_name=from_run_output.team_name,  # type: ignore
        team_session_id=from_run_output.team_session_id,  # type: ignore
        run_id=from_run_output.run_id,
        content=from_run_output.content,  # type: ignore
        content_type=from_run_output.content_type,  # type: ignore
        reasoning_content=from_run_output.reasoning_content,  # type: ignore
        thinking=from_run_output.thinking,  # type: ignore
        citations=from_run_output.citations,  # type: ignore
        images=from_run_output.images,  # type: ignore
        videos=from_run_output.videos,  # type: ignore
        audio=from_run_output.audio,  # type: ignore
        response_audio=from_run_output.response_audio,  # type: ignore
        metadata=from_run_output.metadata,  # type: ignore
        member_responses=from_run_output.member_responses,  # type: ignore
    )


def create_run_output_completed_event(from_run_output: RunOutput) -> RunCompletedEvent:
    return RunCompletedEvent(
        session_id=from_run_output.session_id,
        agent_id=from_run_output.agent_id,  # type: ignore
        agent_name=from_run_output.agent_name,  # type: ignore
        team_session_id=from_run_output.team_session_id,  # type: ignore
        run_id=from_run_output.run_id,
        content=from_run_output.content,  # type: ignore
        content_type=from_run_output.content_type,  # type: ignore
        reasoning_content=from_run_output.reasoning_content,  # type: ignore
        thinking=from_run_output.thinking,  # type: ignore
        citations=from_run_output.citations,  # type: ignore
        images=from_run_output.images,  # type: ignore
        videos=from_run_output.videos,  # type: ignore
        audio=from_run_output.audio,  # type: ignore
        response_audio=from_run_output.response_audio,  # type: ignore
        metadata=from_run_output.metadata,  # type: ignore
    )


def create_run_output_paused_event(
    from_run_output: RunOutput, tools: Optional[List[ToolExecution]] = None
) -> RunPausedEvent:
    return RunPausedEvent(
        session_id=from_run_output.session_id,
        agent_id=from_run_output.agent_id,  # type: ignore
        agent_name=from_run_output.agent_name,  # type: ignore
        team_session_id=from_run_output.team_session_id,  # type: ignore
        run_id=from_run_output.run_id,
        tools=tools,
        content=from_run_output.content,
    )


def create_run_output_continued_event(from_run_output: RunOutput) -> RunContinuedEvent:
    return RunContinuedEvent(
        session_id=from_run_output.session_id,
        agent_id=from_run_output.agent_id,  # type: ignore
        agent_name=from_run_output.agent_name,  # type: ignore
        team_session_id=from_run_output.team_session_id,  # type: ignore
        run_id=from_run_output.run_id,
    )


def create_team_run_output_error_event(from_run_output: TeamRunOutput, error: str) -> TeamRunErrorEvent:
    return TeamRunErrorEvent(
        session_id=from_run_output.session_id,
        team_id=from_run_output.team_id,  # type: ignore
        team_name=from_run_output.team_name,  # type: ignore
        team_session_id=from_run_output.team_session_id,  # type: ignore
        run_id=from_run_output.run_id,
        content=error,
    )


def create_run_output_error_event(from_run_output: RunOutput, error: str) -> RunErrorEvent:
    return RunErrorEvent(
        session_id=from_run_output.session_id,
        agent_id=from_run_output.agent_id,  # type: ignore
        agent_name=from_run_output.agent_name,  # type: ignore
        team_session_id=from_run_output.team_session_id,  # type: ignore
        run_id=from_run_output.run_id,
        content=error,
    )


def create_team_run_output_cancelled_event(from_run_output: TeamRunOutput, reason: str) -> TeamRunCancelledEvent:
    return TeamRunCancelledEvent(
        session_id=from_run_output.session_id,
        team_id=from_run_output.team_id,  # type: ignore
        team_name=from_run_output.team_name,  # type: ignore
        team_session_id=from_run_output.team_session_id,  # type: ignore
        run_id=from_run_output.run_id,
        reason=reason,
    )


def create_run_output_cancelled_event(from_run_output: RunOutput, reason: str) -> RunCancelledEvent:
    return RunCancelledEvent(
        session_id=from_run_output.session_id,
        agent_id=from_run_output.agent_id,  # type: ignore
        agent_name=from_run_output.agent_name,  # type: ignore
        team_session_id=from_run_output.team_session_id,  # type: ignore
        run_id=from_run_output.run_id,
        reason=reason,
    )


def create_memory_update_started_event(from_run_output: RunOutput) -> MemoryUpdateStartedEvent:
    return MemoryUpdateStartedEvent(
        session_id=from_run_output.session_id,
        agent_id=from_run_output.agent_id,  # type: ignore
        agent_name=from_run_output.agent_name,  # type: ignore
        team_session_id=from_run_output.team_session_id,  # type: ignore
        run_id=from_run_output.run_id,
    )


def create_team_memory_update_started_event(from_run_output: TeamRunOutput) -> TeamMemoryUpdateStartedEvent:
    return TeamMemoryUpdateStartedEvent(
        session_id=from_run_output.session_id,
        team_id=from_run_output.team_id,  # type: ignore
        team_name=from_run_output.team_name,  # type: ignore
        team_session_id=from_run_output.team_session_id,  # type: ignore
        run_id=from_run_output.run_id,
    )


def create_memory_update_completed_event(from_run_output: RunOutput) -> MemoryUpdateCompletedEvent:
    return MemoryUpdateCompletedEvent(
        session_id=from_run_output.session_id,
        agent_id=from_run_output.agent_id,  # type: ignore
        agent_name=from_run_output.agent_name,  # type: ignore
        team_session_id=from_run_output.team_session_id,  # type: ignore
        run_id=from_run_output.run_id,
    )


def create_team_memory_update_completed_event(from_run_output: TeamRunOutput) -> TeamMemoryUpdateCompletedEvent:
    return TeamMemoryUpdateCompletedEvent(
        session_id=from_run_output.session_id,
        team_id=from_run_output.team_id,  # type: ignore
        team_name=from_run_output.team_name,  # type: ignore
        team_session_id=from_run_output.team_session_id,  # type: ignore
        run_id=from_run_output.run_id,
    )


def create_reasoning_started_event(from_run_output: RunOutput) -> ReasoningStartedEvent:
    return ReasoningStartedEvent(
        session_id=from_run_output.session_id,
        agent_id=from_run_output.agent_id,  # type: ignore
        agent_name=from_run_output.agent_name,  # type: ignore
        team_session_id=from_run_output.team_session_id,  # type: ignore
        run_id=from_run_output.run_id,
    )


def create_team_reasoning_started_event(from_run_output: TeamRunOutput) -> TeamReasoningStartedEvent:
    return TeamReasoningStartedEvent(
        session_id=from_run_output.session_id,
        team_id=from_run_output.team_id,  # type: ignore
        team_name=from_run_output.team_name,  # type: ignore
        team_session_id=from_run_output.team_session_id,  # type: ignore
        run_id=from_run_output.run_id,
    )


def create_reasoning_step_event(
    from_run_output: RunOutput, reasoning_step: ReasoningStep, reasoning_content: str
) -> ReasoningStepEvent:
    return ReasoningStepEvent(
        session_id=from_run_output.session_id,
        agent_id=from_run_output.agent_id,  # type: ignore
        agent_name=from_run_output.agent_name,  # type: ignore
        team_session_id=from_run_output.team_session_id,  # type: ignore
        run_id=from_run_output.run_id,
        content=reasoning_step,
        content_type=reasoning_step.__class__.__name__,
        reasoning_content=reasoning_content,
    )


def create_team_reasoning_step_event(
    from_run_output: TeamRunOutput, reasoning_step: ReasoningStep, reasoning_content: str
) -> TeamReasoningStepEvent:
    return TeamReasoningStepEvent(
        session_id=from_run_output.session_id,
        team_id=from_run_output.team_id,  # type: ignore
        team_name=from_run_output.team_name,  # type: ignore
        team_session_id=from_run_output.team_session_id,  # type: ignore
        run_id=from_run_output.run_id,
        content=reasoning_step,
        content_type=reasoning_step.__class__.__name__,
        reasoning_content=reasoning_content,
    )


def create_reasoning_completed_event(
    from_run_output: RunOutput, content: Optional[Any] = None, content_type: Optional[str] = None
) -> ReasoningCompletedEvent:
    return ReasoningCompletedEvent(
        session_id=from_run_output.session_id,
        agent_id=from_run_output.agent_id,  # type: ignore
        agent_name=from_run_output.agent_name,  # type: ignore
        team_session_id=from_run_output.team_session_id,  # type: ignore
        run_id=from_run_output.run_id,
        content=content,
        content_type=content_type or "str",
    )


def create_team_reasoning_completed_event(
    from_run_output: TeamRunOutput, content: Optional[Any] = None, content_type: Optional[str] = None
) -> TeamReasoningCompletedEvent:
    return TeamReasoningCompletedEvent(
        session_id=from_run_output.session_id,
        team_id=from_run_output.team_id,  # type: ignore
        team_name=from_run_output.team_name,  # type: ignore
        team_session_id=from_run_output.team_session_id,  # type: ignore
        run_id=from_run_output.run_id,
        content=content,
        content_type=content_type or "str",
    )


def create_tool_call_started_event(from_run_output: RunOutput, tool: ToolExecution) -> ToolCallStartedEvent:
    return ToolCallStartedEvent(
        session_id=from_run_output.session_id,
        agent_id=from_run_output.agent_id,  # type: ignore
        agent_name=from_run_output.agent_name,  # type: ignore
        team_session_id=from_run_output.team_session_id,  # type: ignore
        run_id=from_run_output.run_id,
        tool=tool,
    )


def create_team_tool_call_started_event(
    from_run_output: TeamRunOutput, tool: ToolExecution
) -> TeamToolCallStartedEvent:
    return TeamToolCallStartedEvent(
        session_id=from_run_output.session_id,
        team_id=from_run_output.team_id,  # type: ignore
        team_name=from_run_output.team_name,  # type: ignore
        team_session_id=from_run_output.team_session_id,  # type: ignore
        run_id=from_run_output.run_id,
        tool=tool,
    )


def create_tool_call_completed_event(
    from_run_output: RunOutput, tool: ToolExecution, content: Optional[Any] = None
) -> ToolCallCompletedEvent:
    return ToolCallCompletedEvent(
        session_id=from_run_output.session_id,
        agent_id=from_run_output.agent_id,  # type: ignore
        agent_name=from_run_output.agent_name,  # type: ignore
        team_session_id=from_run_output.team_session_id,  # type: ignore
        run_id=from_run_output.run_id,
        tool=tool,
        content=content,
        images=from_run_output.images,
        videos=from_run_output.videos,
        audio=from_run_output.audio,
    )


def create_team_tool_call_completed_event(
    from_run_output: TeamRunOutput, tool: ToolExecution, content: Optional[Any] = None
) -> TeamToolCallCompletedEvent:
    return TeamToolCallCompletedEvent(
        session_id=from_run_output.session_id,
        team_id=from_run_output.team_id,  # type: ignore
        team_name=from_run_output.team_name,  # type: ignore
        team_session_id=from_run_output.team_session_id,  # type: ignore
        run_id=from_run_output.run_id,
        tool=tool,
        content=content,
        images=from_run_output.images,
        videos=from_run_output.videos,
        audio=from_run_output.audio,
    )


def create_run_output_content_event(
    from_run_output: RunOutput,
    content: Optional[Any] = None,
    content_type: Optional[str] = None,
    thinking: Optional[str] = None,
    redacted_thinking: Optional[str] = None,
    citations: Optional[Citations] = None,
    response_audio: Optional[AudioResponse] = None,
    image: Optional[ImageArtifact] = None,
) -> RunContentEvent:
    thinking_combined = (thinking or "") + (redacted_thinking or "")

    return RunContentEvent(
        session_id=from_run_output.session_id,
        agent_id=from_run_output.agent_id,  # type: ignore
        agent_name=from_run_output.agent_name,  # type: ignore
        team_session_id=from_run_output.team_session_id,  # type: ignore
        run_id=from_run_output.run_id,
        content=content,
        content_type=content_type or "str",
        thinking=thinking_combined,
        citations=citations,
        response_audio=response_audio,
        image=image,
        metadata=from_run_output.metadata,
    )


def create_team_run_output_content_event(
    from_run_output: TeamRunOutput,
    content: Optional[Any] = None,
    content_type: Optional[str] = None,
    thinking: Optional[str] = None,
    redacted_thinking: Optional[str] = None,
    citations: Optional[Citations] = None,
    response_audio: Optional[AudioResponse] = None,
    image: Optional[ImageArtifact] = None,
) -> TeamRunContentEvent:
    thinking_combined = (thinking or "") + (redacted_thinking or "")
    return TeamRunContentEvent(
        session_id=from_run_output.session_id,
        team_id=from_run_output.team_id,  # type: ignore
        team_name=from_run_output.team_name,  # type: ignore
        team_session_id=from_run_output.team_session_id,  # type: ignore
        run_id=from_run_output.run_id,
        content=content,
        content_type=content_type or "str",
        thinking=thinking_combined,
        citations=citations,
        response_audio=response_audio,
        image=image,
        metadata=from_run_output.metadata,
    )


def create_parser_model_response_started_event(
    from_run_output: RunOutput,
) -> ParserModelResponseStartedEvent:
    return ParserModelResponseStartedEvent(
        session_id=from_run_output.session_id,
        agent_id=from_run_output.agent_id,  # type: ignore
        agent_name=from_run_output.agent_name,  # type: ignore
        team_session_id=from_run_output.team_session_id,  # type: ignore
        run_id=from_run_output.run_id,
    )


def create_parser_model_response_completed_event(
    from_run_output: RunOutput,
) -> ParserModelResponseCompletedEvent:
    return ParserModelResponseCompletedEvent(
        session_id=from_run_output.session_id,
        agent_id=from_run_output.agent_id,  # type: ignore
        agent_name=from_run_output.agent_name,  # type: ignore
        team_session_id=from_run_output.team_session_id,  # type: ignore
        run_id=from_run_output.run_id,
    )


def create_team_parser_model_response_started_event(
    from_run_output: TeamRunOutput,
) -> TeamParserModelResponseStartedEvent:
    return TeamParserModelResponseStartedEvent(
        session_id=from_run_output.session_id,
        team_id=from_run_output.team_id,  # type: ignore
        team_name=from_run_output.team_name,  # type: ignore
        team_session_id=from_run_output.team_session_id,  # type: ignore
        run_id=from_run_output.run_id,
    )


def create_team_parser_model_response_completed_event(
    from_run_output: TeamRunOutput,
) -> TeamParserModelResponseCompletedEvent:
    return TeamParserModelResponseCompletedEvent(
        session_id=from_run_output.session_id,
        team_id=from_run_output.team_id,  # type: ignore
        team_name=from_run_output.team_name,  # type: ignore
        team_session_id=from_run_output.team_session_id,  # type: ignore
        run_id=from_run_output.run_id,
    )
