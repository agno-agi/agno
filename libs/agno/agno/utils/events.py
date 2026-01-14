from typing import Any, Dict, List, Optional, Union

from agno.media import Audio, Image
from agno.models.message import Citations
from agno.models.response import ToolExecution
from agno.reasoning.step import ReasoningStep
from agno.run.agent import (
    MemoryUpdateCompletedEvent,
    MemoryUpdateStartedEvent,
    OutputModelResponseCompletedEvent,
    OutputModelResponseStartedEvent,
    ParserModelResponseCompletedEvent,
    ParserModelResponseStartedEvent,
    PostHookCompletedEvent,
    PostHookStartedEvent,
    PreHookCompletedEvent,
    PreHookStartedEvent,
    ReasoningCompletedEvent,
    ReasoningContentDeltaEvent,
    ReasoningStartedEvent,
    ReasoningStepEvent,
    RunCancelledEvent,
    RunCompletedEvent,
    RunContentCompletedEvent,
    RunContentEvent,
    RunContinuedEvent,
    RunErrorEvent,
    RunEvent,
    RunInput,
    RunOutput,
    RunOutputEvent,
    RunPausedEvent,
    RunStartedEvent,
    SessionSummaryCompletedEvent,
    SessionSummaryStartedEvent,
    ToolCallCompletedEvent,
    ToolCallErrorEvent,
    ToolCallStartedEvent,
)
from agno.run.requirement import RunRequirement
from agno.run.team import MemoryUpdateCompletedEvent as TeamMemoryUpdateCompletedEvent
from agno.run.team import MemoryUpdateStartedEvent as TeamMemoryUpdateStartedEvent
from agno.run.team import OutputModelResponseCompletedEvent as TeamOutputModelResponseCompletedEvent
from agno.run.team import OutputModelResponseStartedEvent as TeamOutputModelResponseStartedEvent
from agno.run.team import ParserModelResponseCompletedEvent as TeamParserModelResponseCompletedEvent
from agno.run.team import ParserModelResponseStartedEvent as TeamParserModelResponseStartedEvent
from agno.run.team import PostHookCompletedEvent as TeamPostHookCompletedEvent
from agno.run.team import PostHookStartedEvent as TeamPostHookStartedEvent
from agno.run.team import PreHookCompletedEvent as TeamPreHookCompletedEvent
from agno.run.team import PreHookStartedEvent as TeamPreHookStartedEvent
from agno.run.team import ReasoningCompletedEvent as TeamReasoningCompletedEvent
from agno.run.team import ReasoningContentDeltaEvent as TeamReasoningContentDeltaEvent
from agno.run.team import ReasoningStartedEvent as TeamReasoningStartedEvent
from agno.run.team import ReasoningStepEvent as TeamReasoningStepEvent
from agno.run.team import RunCancelledEvent as TeamRunCancelledEvent
from agno.run.team import RunCompletedEvent as TeamRunCompletedEvent
from agno.run.team import RunContentCompletedEvent as TeamRunContentCompletedEvent
from agno.run.team import RunContentEvent as TeamRunContentEvent
from agno.run.team import RunErrorEvent as TeamRunErrorEvent
from agno.run.team import RunStartedEvent as TeamRunStartedEvent
from agno.run.team import SessionSummaryCompletedEvent as TeamSessionSummaryCompletedEvent
from agno.run.team import SessionSummaryStartedEvent as TeamSessionSummaryStartedEvent
from agno.run.team import TeamRunEvent, TeamRunInput, TeamRunOutput, TeamRunOutputEvent
from agno.run.team import ToolCallCompletedEvent as TeamToolCallCompletedEvent
from agno.run.team import ToolCallErrorEvent as TeamToolCallErrorEvent
from agno.run.team import ToolCallStartedEvent as TeamToolCallStartedEvent
from agno.session.summary import SessionSummary


def create_team_run_started_event(from_run_response: TeamRunOutput) -> TeamRunStartedEvent:
    return TeamRunStartedEvent(
        session_id=from_run_response.session_id,
        team_id=from_run_response.team_id,  # type: ignore
        team_name=from_run_response.team_name,  # type: ignore
        run_id=from_run_response.run_id,
        model=from_run_response.model,  # type: ignore
        model_provider=from_run_response.model_provider,  # type: ignore
    )


def create_run_started_event(from_run_response: RunOutput) -> RunStartedEvent:
    return RunStartedEvent(
        session_id=from_run_response.session_id,
        agent_id=from_run_response.agent_id,  # type: ignore
        agent_name=from_run_response.agent_name,  # type: ignore
        run_id=from_run_response.run_id,
        model=from_run_response.model,  # type: ignore
        model_provider=from_run_response.model_provider,  # type: ignore
    )


def create_team_run_completed_event(from_run_response: TeamRunOutput) -> TeamRunCompletedEvent:
    return TeamRunCompletedEvent(
        session_id=from_run_response.session_id,
        team_id=from_run_response.team_id,  # type: ignore
        team_name=from_run_response.team_name,  # type: ignore
        run_id=from_run_response.run_id,
        content=from_run_response.content,  # type: ignore
        content_type=from_run_response.content_type,  # type: ignore
        reasoning_content=from_run_response.reasoning_content,  # type: ignore
        citations=from_run_response.citations,  # type: ignore
        model_provider_data=from_run_response.model_provider_data,  # type: ignore
        images=from_run_response.images,  # type: ignore
        videos=from_run_response.videos,  # type: ignore
        audio=from_run_response.audio,  # type: ignore
        response_audio=from_run_response.response_audio,  # type: ignore
        references=from_run_response.references,  # type: ignore
        additional_input=from_run_response.additional_input,  # type: ignore
        reasoning_steps=from_run_response.reasoning_steps,  # type: ignore
        reasoning_messages=from_run_response.reasoning_messages,  # type: ignore
        member_responses=from_run_response.member_responses,  # type: ignore
        metadata=from_run_response.metadata,  # type: ignore
        metrics=from_run_response.metrics,  # type: ignore
        session_state=from_run_response.session_state,  # type: ignore
    )


def create_run_completed_event(from_run_response: RunOutput) -> RunCompletedEvent:
    return RunCompletedEvent(
        session_id=from_run_response.session_id,
        agent_id=from_run_response.agent_id,  # type: ignore
        agent_name=from_run_response.agent_name,  # type: ignore
        run_id=from_run_response.run_id,
        content=from_run_response.content,  # type: ignore
        content_type=from_run_response.content_type,  # type: ignore
        reasoning_content=from_run_response.reasoning_content,  # type: ignore
        citations=from_run_response.citations,  # type: ignore
        model_provider_data=from_run_response.model_provider_data,  # type: ignore
        images=from_run_response.images,  # type: ignore
        videos=from_run_response.videos,  # type: ignore
        audio=from_run_response.audio,  # type: ignore
        response_audio=from_run_response.response_audio,  # type: ignore
        references=from_run_response.references,  # type: ignore
        additional_input=from_run_response.additional_input,  # type: ignore
        reasoning_steps=from_run_response.reasoning_steps,  # type: ignore
        reasoning_messages=from_run_response.reasoning_messages,  # type: ignore
        metadata=from_run_response.metadata,  # type: ignore
        metrics=from_run_response.metrics,  # type: ignore
        session_state=from_run_response.session_state,  # type: ignore
    )


def create_run_paused_event(
    from_run_response: RunOutput,
    tools: Optional[List[ToolExecution]] = None,
    requirements: Optional[List[RunRequirement]] = None,
) -> RunPausedEvent:
    return RunPausedEvent(
        session_id=from_run_response.session_id,
        agent_id=from_run_response.agent_id,  # type: ignore
        agent_name=from_run_response.agent_name,  # type: ignore
        run_id=from_run_response.run_id,
        tools=tools,
        requirements=requirements,
        content=from_run_response.content,
    )


def create_run_continued_event(from_run_response: RunOutput) -> RunContinuedEvent:
    return RunContinuedEvent(
        session_id=from_run_response.session_id,
        agent_id=from_run_response.agent_id,  # type: ignore
        agent_name=from_run_response.agent_name,  # type: ignore
        run_id=from_run_response.run_id,
    )


def create_team_run_error_event(
    from_run_response: TeamRunOutput,
    error: str,
    error_type: Optional[str] = None,
    error_id: Optional[str] = None,
    additional_data: Optional[Dict[str, Any]] = None,
) -> TeamRunErrorEvent:
    return TeamRunErrorEvent(
        session_id=from_run_response.session_id,
        team_id=from_run_response.team_id,  # type: ignore
        team_name=from_run_response.team_name,  # type: ignore
        run_id=from_run_response.run_id,
        content=error,
        error_type=error_type,
        error_id=error_id,
        additional_data=additional_data,
    )


def create_run_error_event(
    from_run_response: RunOutput,
    error: str,
    error_type: Optional[str] = None,
    error_id: Optional[str] = None,
    additional_data: Optional[Dict[str, Any]] = None,
) -> RunErrorEvent:
    return RunErrorEvent(
        session_id=from_run_response.session_id,
        agent_id=from_run_response.agent_id,  # type: ignore
        agent_name=from_run_response.agent_name,  # type: ignore
        run_id=from_run_response.run_id,
        content=error,
        error_type=error_type,
        error_id=error_id,
        additional_data=additional_data,
    )


def create_team_run_cancelled_event(from_run_response: TeamRunOutput, reason: str) -> TeamRunCancelledEvent:
    return TeamRunCancelledEvent(
        session_id=from_run_response.session_id,
        team_id=from_run_response.team_id,  # type: ignore
        team_name=from_run_response.team_name,  # type: ignore
        run_id=from_run_response.run_id,
        reason=reason,
    )


def create_run_cancelled_event(from_run_response: RunOutput, reason: str) -> RunCancelledEvent:
    return RunCancelledEvent(
        session_id=from_run_response.session_id,
        agent_id=from_run_response.agent_id,  # type: ignore
        agent_name=from_run_response.agent_name,  # type: ignore
        run_id=from_run_response.run_id,
        reason=reason,
    )


def create_pre_hook_started_event(
    from_run_response: RunOutput, pre_hook_name: Optional[str] = None, run_input: Optional[RunInput] = None
) -> PreHookStartedEvent:
    from copy import deepcopy

    return PreHookStartedEvent(
        session_id=from_run_response.session_id,
        agent_id=from_run_response.agent_id,  # type: ignore
        agent_name=from_run_response.agent_name,  # type: ignore
        run_id=from_run_response.run_id,
        pre_hook_name=pre_hook_name,
        run_input=deepcopy(run_input),
    )


def create_team_pre_hook_started_event(
    from_run_response: TeamRunOutput, pre_hook_name: Optional[str] = None, run_input: Optional[TeamRunInput] = None
) -> TeamPreHookStartedEvent:
    from copy import deepcopy

    return TeamPreHookStartedEvent(
        session_id=from_run_response.session_id,
        team_id=from_run_response.team_id,  # type: ignore
        team_name=from_run_response.team_name,  # type: ignore
        run_id=from_run_response.run_id,
        pre_hook_name=pre_hook_name,
        run_input=deepcopy(run_input),
    )


def create_pre_hook_completed_event(
    from_run_response: RunOutput, pre_hook_name: Optional[str] = None, run_input: Optional[RunInput] = None
) -> PreHookCompletedEvent:
    from copy import deepcopy

    return PreHookCompletedEvent(
        session_id=from_run_response.session_id,
        agent_id=from_run_response.agent_id,  # type: ignore
        agent_name=from_run_response.agent_name,  # type: ignore
        run_id=from_run_response.run_id,
        pre_hook_name=pre_hook_name,
        run_input=deepcopy(run_input),
    )


def create_team_pre_hook_completed_event(
    from_run_response: TeamRunOutput, pre_hook_name: Optional[str] = None, run_input: Optional[TeamRunInput] = None
) -> TeamPreHookCompletedEvent:
    from copy import deepcopy

    return TeamPreHookCompletedEvent(
        session_id=from_run_response.session_id,
        team_id=from_run_response.team_id,  # type: ignore
        team_name=from_run_response.team_name,  # type: ignore
        run_id=from_run_response.run_id,
        pre_hook_name=pre_hook_name,
        run_input=deepcopy(run_input),
    )


def create_post_hook_started_event(
    from_run_response: RunOutput, post_hook_name: Optional[str] = None
) -> PostHookStartedEvent:
    return PostHookStartedEvent(
        session_id=from_run_response.session_id,
        agent_id=from_run_response.agent_id,  # type: ignore
        agent_name=from_run_response.agent_name,  # type: ignore
        run_id=from_run_response.run_id,
        post_hook_name=post_hook_name,
    )


def create_team_post_hook_started_event(
    from_run_response: TeamRunOutput, post_hook_name: Optional[str] = None
) -> TeamPostHookStartedEvent:
    return TeamPostHookStartedEvent(
        session_id=from_run_response.session_id,
        team_id=from_run_response.team_id,  # type: ignore
        team_name=from_run_response.team_name,  # type: ignore
        run_id=from_run_response.run_id,
        post_hook_name=post_hook_name,
    )


def create_post_hook_completed_event(
    from_run_response: RunOutput, post_hook_name: Optional[str] = None
) -> PostHookCompletedEvent:
    return PostHookCompletedEvent(
        session_id=from_run_response.session_id,
        agent_id=from_run_response.agent_id,  # type: ignore
        agent_name=from_run_response.agent_name,  # type: ignore
        run_id=from_run_response.run_id,
        post_hook_name=post_hook_name,
    )


def create_team_post_hook_completed_event(
    from_run_response: TeamRunOutput, post_hook_name: Optional[str] = None
) -> TeamPostHookCompletedEvent:
    return TeamPostHookCompletedEvent(
        session_id=from_run_response.session_id,
        team_id=from_run_response.team_id,  # type: ignore
        team_name=from_run_response.team_name,  # type: ignore
        run_id=from_run_response.run_id,
        post_hook_name=post_hook_name,
    )


def create_memory_update_started_event(from_run_response: RunOutput) -> MemoryUpdateStartedEvent:
    return MemoryUpdateStartedEvent(
        session_id=from_run_response.session_id,
        agent_id=from_run_response.agent_id,  # type: ignore
        agent_name=from_run_response.agent_name,  # type: ignore
        run_id=from_run_response.run_id,
    )


def create_team_memory_update_started_event(from_run_response: TeamRunOutput) -> TeamMemoryUpdateStartedEvent:
    return TeamMemoryUpdateStartedEvent(
        session_id=from_run_response.session_id,
        team_id=from_run_response.team_id,  # type: ignore
        team_name=from_run_response.team_name,  # type: ignore
        run_id=from_run_response.run_id,
    )


def create_memory_update_completed_event(from_run_response: RunOutput) -> MemoryUpdateCompletedEvent:
    return MemoryUpdateCompletedEvent(
        session_id=from_run_response.session_id,
        agent_id=from_run_response.agent_id,  # type: ignore
        agent_name=from_run_response.agent_name,  # type: ignore
        run_id=from_run_response.run_id,
    )


def create_team_memory_update_completed_event(from_run_response: TeamRunOutput) -> TeamMemoryUpdateCompletedEvent:
    return TeamMemoryUpdateCompletedEvent(
        session_id=from_run_response.session_id,
        team_id=from_run_response.team_id,  # type: ignore
        team_name=from_run_response.team_name,  # type: ignore
        run_id=from_run_response.run_id,
    )


def create_team_session_summary_started_event(
    from_run_response: TeamRunOutput,
) -> TeamSessionSummaryStartedEvent:
    return TeamSessionSummaryStartedEvent(
        session_id=from_run_response.session_id,
        team_id=from_run_response.team_id,  # type: ignore
        team_name=from_run_response.team_name,  # type: ignore
        run_id=from_run_response.run_id,
    )


def create_team_session_summary_completed_event(
    from_run_response: TeamRunOutput, session_summary: Optional[SessionSummary] = None
) -> TeamSessionSummaryCompletedEvent:
    return TeamSessionSummaryCompletedEvent(
        session_id=from_run_response.session_id,
        team_id=from_run_response.team_id,  # type: ignore
        team_name=from_run_response.team_name,  # type: ignore
        run_id=from_run_response.run_id,
        session_summary=session_summary,
    )


def create_session_summary_started_event(from_run_response: RunOutput) -> SessionSummaryStartedEvent:
    return SessionSummaryStartedEvent(
        session_id=from_run_response.session_id,
        agent_id=from_run_response.agent_id,  # type: ignore
        agent_name=from_run_response.agent_name,  # type: ignore
        run_id=from_run_response.run_id,
    )


def create_session_summary_completed_event(
    from_run_response: RunOutput, session_summary: Optional[SessionSummary] = None
) -> SessionSummaryCompletedEvent:
    return SessionSummaryCompletedEvent(
        session_id=from_run_response.session_id,
        agent_id=from_run_response.agent_id,  # type: ignore
        agent_name=from_run_response.agent_name,  # type: ignore
        run_id=from_run_response.run_id,
        session_summary=session_summary,
    )


def create_reasoning_started_event(from_run_response: RunOutput) -> ReasoningStartedEvent:
    return ReasoningStartedEvent(
        session_id=from_run_response.session_id,
        agent_id=from_run_response.agent_id,  # type: ignore
        agent_name=from_run_response.agent_name,  # type: ignore
        run_id=from_run_response.run_id,
    )


def create_team_reasoning_started_event(from_run_response: TeamRunOutput) -> TeamReasoningStartedEvent:
    return TeamReasoningStartedEvent(
        session_id=from_run_response.session_id,
        team_id=from_run_response.team_id,  # type: ignore
        team_name=from_run_response.team_name,  # type: ignore
        run_id=from_run_response.run_id,
    )


def create_reasoning_step_event(
    from_run_response: RunOutput, reasoning_step: ReasoningStep, reasoning_content: str
) -> ReasoningStepEvent:
    return ReasoningStepEvent(
        session_id=from_run_response.session_id,
        agent_id=from_run_response.agent_id,  # type: ignore
        agent_name=from_run_response.agent_name,  # type: ignore
        run_id=from_run_response.run_id,
        content=reasoning_step,
        content_type=reasoning_step.__class__.__name__,
        reasoning_content=reasoning_content,
    )


def create_reasoning_content_delta_event(
    from_run_response: RunOutput, reasoning_content: str
) -> ReasoningContentDeltaEvent:
    """Create an event for streaming reasoning content chunks."""
    return ReasoningContentDeltaEvent(
        session_id=from_run_response.session_id,
        agent_id=from_run_response.agent_id,  # type: ignore
        agent_name=from_run_response.agent_name,  # type: ignore
        run_id=from_run_response.run_id,
        reasoning_content=reasoning_content,
    )


def create_team_reasoning_step_event(
    from_run_response: TeamRunOutput, reasoning_step: ReasoningStep, reasoning_content: str
) -> TeamReasoningStepEvent:
    return TeamReasoningStepEvent(
        session_id=from_run_response.session_id,
        team_id=from_run_response.team_id,  # type: ignore
        team_name=from_run_response.team_name,  # type: ignore
        run_id=from_run_response.run_id,
        content=reasoning_step,
        content_type=reasoning_step.__class__.__name__,
        reasoning_content=reasoning_content,
    )


def create_team_reasoning_content_delta_event(
    from_run_response: TeamRunOutput, reasoning_content: str
) -> TeamReasoningContentDeltaEvent:
    """Create an event for streaming reasoning content chunks for Team."""
    return TeamReasoningContentDeltaEvent(
        session_id=from_run_response.session_id,
        team_id=from_run_response.team_id,  # type: ignore
        team_name=from_run_response.team_name,  # type: ignore
        run_id=from_run_response.run_id,
        reasoning_content=reasoning_content,
    )


def create_reasoning_completed_event(
    from_run_response: RunOutput, content: Optional[Any] = None, content_type: Optional[str] = None
) -> ReasoningCompletedEvent:
    return ReasoningCompletedEvent(
        session_id=from_run_response.session_id,
        agent_id=from_run_response.agent_id,  # type: ignore
        agent_name=from_run_response.agent_name,  # type: ignore
        run_id=from_run_response.run_id,
        content=content,
        content_type=content_type or "str",
    )


def create_team_reasoning_completed_event(
    from_run_response: TeamRunOutput, content: Optional[Any] = None, content_type: Optional[str] = None
) -> TeamReasoningCompletedEvent:
    return TeamReasoningCompletedEvent(
        session_id=from_run_response.session_id,
        team_id=from_run_response.team_id,  # type: ignore
        team_name=from_run_response.team_name,  # type: ignore
        run_id=from_run_response.run_id,
        content=content,
        content_type=content_type or "str",
    )


def create_tool_call_started_event(from_run_response: RunOutput, tool: ToolExecution) -> ToolCallStartedEvent:
    return ToolCallStartedEvent(
        session_id=from_run_response.session_id,
        agent_id=from_run_response.agent_id,  # type: ignore
        agent_name=from_run_response.agent_name,  # type: ignore
        run_id=from_run_response.run_id,
        tool=tool,
    )


def create_team_tool_call_started_event(
    from_run_response: TeamRunOutput, tool: ToolExecution
) -> TeamToolCallStartedEvent:
    return TeamToolCallStartedEvent(
        session_id=from_run_response.session_id,
        team_id=from_run_response.team_id,  # type: ignore
        team_name=from_run_response.team_name,  # type: ignore
        run_id=from_run_response.run_id,
        tool=tool,
    )


def create_tool_call_completed_event(
    from_run_response: RunOutput, tool: ToolExecution, content: Optional[Any] = None
) -> ToolCallCompletedEvent:
    return ToolCallCompletedEvent(
        session_id=from_run_response.session_id,
        agent_id=from_run_response.agent_id,  # type: ignore
        agent_name=from_run_response.agent_name,  # type: ignore
        run_id=from_run_response.run_id,
        tool=tool,
        content=content,
        images=from_run_response.images,
        videos=from_run_response.videos,
        audio=from_run_response.audio,
    )


def create_team_tool_call_completed_event(
    from_run_response: TeamRunOutput, tool: ToolExecution, content: Optional[Any] = None
) -> TeamToolCallCompletedEvent:
    return TeamToolCallCompletedEvent(
        session_id=from_run_response.session_id,
        team_id=from_run_response.team_id,  # type: ignore
        team_name=from_run_response.team_name,  # type: ignore
        run_id=from_run_response.run_id,
        tool=tool,
        content=content,
        images=from_run_response.images,
        videos=from_run_response.videos,
        audio=from_run_response.audio,
    )


def create_tool_call_error_event(
    from_run_response: RunOutput, tool: ToolExecution, error: Optional[str] = None
) -> ToolCallErrorEvent:
    return ToolCallErrorEvent(
        session_id=from_run_response.session_id,
        agent_id=from_run_response.agent_id,  # type: ignore
        agent_name=from_run_response.agent_name,  # type: ignore
        run_id=from_run_response.run_id,
        tool=tool,
        error=error,
    )


def create_team_tool_call_error_event(
    from_run_response: TeamRunOutput, tool: ToolExecution, error: Optional[str] = None
) -> TeamToolCallErrorEvent:
    return TeamToolCallErrorEvent(
        session_id=from_run_response.session_id,
        team_id=from_run_response.team_id,  # type: ignore
        team_name=from_run_response.team_name,  # type: ignore
        run_id=from_run_response.run_id,
        tool=tool,
        error=error,
    )


def create_run_output_content_event(
    from_run_response: RunOutput,
    content: Optional[Any] = None,
    content_type: Optional[str] = None,
    reasoning_content: Optional[str] = None,
    redacted_reasoning_content: Optional[str] = None,
    model_provider_data: Optional[Dict[str, Any]] = None,
    citations: Optional[Citations] = None,
    response_audio: Optional[Audio] = None,
    image: Optional[Image] = None,
) -> RunContentEvent:
    thinking_combined = (reasoning_content or "") + (redacted_reasoning_content or "")

    return RunContentEvent(
        session_id=from_run_response.session_id,
        agent_id=from_run_response.agent_id,  # type: ignore
        agent_name=from_run_response.agent_name,  # type: ignore
        run_id=from_run_response.run_id,
        content=content,
        content_type=content_type or "str",
        reasoning_content=thinking_combined,
        citations=citations,
        response_audio=response_audio,
        image=image,
        references=from_run_response.references,
        additional_input=from_run_response.additional_input,
        reasoning_steps=from_run_response.reasoning_steps,
        reasoning_messages=from_run_response.reasoning_messages,
        model_provider_data=model_provider_data,
    )


def create_team_run_output_content_event(
    from_run_response: TeamRunOutput,
    content: Optional[Any] = None,
    content_type: Optional[str] = None,
    reasoning_content: Optional[str] = None,
    redacted_reasoning_content: Optional[str] = None,
    citations: Optional[Citations] = None,
    model_provider_data: Optional[Dict[str, Any]] = None,
    response_audio: Optional[Audio] = None,
    image: Optional[Image] = None,
) -> TeamRunContentEvent:
    thinking_combined = (reasoning_content or "") + (redacted_reasoning_content or "")

    return TeamRunContentEvent(
        session_id=from_run_response.session_id,
        team_id=from_run_response.team_id,  # type: ignore
        team_name=from_run_response.team_name,  # type: ignore
        run_id=from_run_response.run_id,
        content=content,
        content_type=content_type or "str",
        reasoning_content=thinking_combined,
        citations=citations,
        model_provider_data=model_provider_data,
        response_audio=response_audio,
        image=image,
        references=from_run_response.references,  # type: ignore
        additional_input=from_run_response.additional_input,  # type: ignore
        reasoning_steps=from_run_response.reasoning_steps,  # type: ignore
        reasoning_messages=from_run_response.reasoning_messages,  # type: ignore
    )


def create_run_content_completed_event(
    from_run_response: RunOutput,
) -> RunContentCompletedEvent:
    return RunContentCompletedEvent(
        session_id=from_run_response.session_id,
        agent_id=from_run_response.agent_id,  # type: ignore
        agent_name=from_run_response.agent_name,  # type: ignore
        run_id=from_run_response.run_id,
    )


def create_team_run_content_completed_event(
    from_run_response: TeamRunOutput,
) -> TeamRunContentCompletedEvent:
    return TeamRunContentCompletedEvent(
        session_id=from_run_response.session_id,
        team_id=from_run_response.team_id,  # type: ignore
        team_name=from_run_response.team_name,  # type: ignore
        run_id=from_run_response.run_id,
    )


def create_parser_model_response_started_event(
    from_run_response: RunOutput,
) -> ParserModelResponseStartedEvent:
    return ParserModelResponseStartedEvent(
        session_id=from_run_response.session_id,
        agent_id=from_run_response.agent_id,  # type: ignore
        agent_name=from_run_response.agent_name,  # type: ignore
        run_id=from_run_response.run_id,
    )


def create_parser_model_response_completed_event(
    from_run_response: RunOutput,
) -> ParserModelResponseCompletedEvent:
    return ParserModelResponseCompletedEvent(
        session_id=from_run_response.session_id,
        agent_id=from_run_response.agent_id,  # type: ignore
        agent_name=from_run_response.agent_name,  # type: ignore
        run_id=from_run_response.run_id,
    )


def create_team_parser_model_response_started_event(
    from_run_response: TeamRunOutput,
) -> TeamParserModelResponseStartedEvent:
    return TeamParserModelResponseStartedEvent(
        session_id=from_run_response.session_id,
        team_id=from_run_response.team_id,  # type: ignore
        team_name=from_run_response.team_name,  # type: ignore
        run_id=from_run_response.run_id,
    )


def create_team_parser_model_response_completed_event(
    from_run_response: TeamRunOutput,
) -> TeamParserModelResponseCompletedEvent:
    return TeamParserModelResponseCompletedEvent(
        session_id=from_run_response.session_id,
        team_id=from_run_response.team_id,  # type: ignore
        team_name=from_run_response.team_name,  # type: ignore
        run_id=from_run_response.run_id,
    )


def create_output_model_response_started_event(from_run_response: RunOutput) -> OutputModelResponseStartedEvent:
    return OutputModelResponseStartedEvent(
        session_id=from_run_response.session_id,
        agent_id=from_run_response.agent_id,  # type: ignore
        agent_name=from_run_response.agent_name,  # type: ignore
        run_id=from_run_response.run_id,
    )


def create_output_model_response_completed_event(from_run_response: RunOutput) -> OutputModelResponseCompletedEvent:
    return OutputModelResponseCompletedEvent(
        session_id=from_run_response.session_id,
        agent_id=from_run_response.agent_id,  # type: ignore
        agent_name=from_run_response.agent_name,  # type: ignore
        run_id=from_run_response.run_id,
    )


def create_team_output_model_response_started_event(
    from_run_response: TeamRunOutput,
) -> TeamOutputModelResponseStartedEvent:
    return TeamOutputModelResponseStartedEvent(
        session_id=from_run_response.session_id,
        team_id=from_run_response.team_id,  # type: ignore
        team_name=from_run_response.team_name,  # type: ignore
        run_id=from_run_response.run_id,
    )


def create_team_output_model_response_completed_event(
    from_run_response: TeamRunOutput,
) -> TeamOutputModelResponseCompletedEvent:
    return TeamOutputModelResponseCompletedEvent(
        session_id=from_run_response.session_id,
        team_id=from_run_response.team_id,  # type: ignore
        team_name=from_run_response.team_name,  # type: ignore
        run_id=from_run_response.run_id,
    )


def handle_event(
    event: Union[RunOutputEvent, TeamRunOutputEvent],
    run_response: Union[RunOutput, TeamRunOutput],
    events_to_skip: Optional[List[Union[RunEvent, TeamRunEvent]]] = None,
    store_events: bool = False,
) -> Union[RunOutputEvent, TeamRunOutputEvent]:
    # We only store events that are not run_response_content events
    _events_to_skip: List[str] = [event.value for event in events_to_skip] if events_to_skip else []
    if store_events and event.event not in _events_to_skip:
        if run_response.events is None:
            run_response.events = []
        run_response.events.append(event)  # type: ignore
    return event


def add_error_event(
    error: RunErrorEvent,
    events: Optional[List[RunOutputEvent]],
):
    if events is None:
        events = []
    events.append(error)

    return events


def add_team_error_event(
    error: TeamRunErrorEvent,
    events: Optional[List[Union[RunOutputEvent, TeamRunOutputEvent]]],
):
    if events is None:
        events = []
    events.append(error)
    return events
