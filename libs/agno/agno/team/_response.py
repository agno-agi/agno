"""Response-related helpers for Team (parsing, output models, reasoning, metrics)."""

from __future__ import annotations

from collections import deque
from typing import (
    TYPE_CHECKING,
    Any,
    AsyncIterator,
    Dict,
    Iterator,
    List,
    Optional,
    Type,
    Union,
    cast,
)

from pydantic import BaseModel

from agno.models.base import Model
from agno.models.message import Message
from agno.models.metrics import Metrics
from agno.models.response import ModelResponse
from agno.reasoning.step import NextAction, ReasoningStep, ReasoningSteps
from agno.run import RunContext
from agno.run.messages import RunMessages
from agno.run.team import (
    TeamRunOutput,
    TeamRunOutputEvent,
)
from agno.session import TeamSession
from agno.utils.events import (
    create_team_parser_model_response_completed_event,
    create_team_parser_model_response_started_event,
    create_team_reasoning_completed_event,
    create_team_reasoning_content_delta_event,
    create_team_reasoning_started_event,
    create_team_reasoning_step_event,
    handle_event,
)
from agno.utils.log import log_debug, log_warning
from agno.utils.reasoning import (
    add_reasoning_step_to_metadata,
    append_to_reasoning_content,
    update_run_output_with_reasoning,
)

if TYPE_CHECKING:
    from agno.reasoning.manager import ReasoningEvent
    from agno.team.team import Team


# ---------------------------------------------------------------------------
# Response format
# ---------------------------------------------------------------------------


def get_response_format(
    team: "Team", model: Optional[Model] = None, run_context: Optional[RunContext] = None
) -> Optional[Union[Dict, Type[BaseModel]]]:
    model = cast(Model, model or team.model)
    # Get output_schema from run_context
    output_schema = run_context.output_schema if run_context else None

    if output_schema is None:
        return None
    else:
        json_response_format = {"type": "json_object"}

        if model.supports_native_structured_outputs:
            if not team.use_json_mode:
                log_debug("Setting Model.response_format to Agent.output_schema")
                return output_schema
            else:
                log_debug("Model supports native structured outputs but it is not enabled. Using JSON mode instead.")
                return json_response_format

        elif model.supports_json_schema_outputs:
            if team.use_json_mode:
                log_debug("Setting Model.response_format to JSON response mode")
                # Handle JSON schema - pass through directly (user provides full provider format)
                if isinstance(output_schema, dict):
                    return output_schema
                # Handle Pydantic schema
                return {
                    "type": "json_schema",
                    "json_schema": {
                        "name": output_schema.__name__,
                        "schema": output_schema.model_json_schema(),
                    },
                }
            else:
                return None

        else:
            log_debug("Model does not support structured or JSON schema outputs.")
            return json_response_format


# ---------------------------------------------------------------------------
# Parser model helpers
# ---------------------------------------------------------------------------


def process_parser_response(
    team: "Team",
    model_response: ModelResponse,
    run_messages: RunMessages,
    parser_model_response: ModelResponse,
    messages_for_parser_model: list,
) -> None:
    """Common logic for processing parser model response."""
    parser_model_response_message: Optional[Message] = None
    for message in reversed(messages_for_parser_model):
        if message.role == "assistant":
            parser_model_response_message = message
            break

    if parser_model_response_message is not None:
        run_messages.messages.append(parser_model_response_message)
        model_response.parsed = parser_model_response.parsed
        model_response.content = parser_model_response.content
    else:
        log_warning("Unable to parse response with parser model")


def parse_response_with_parser_model(
    team: "Team", model_response: ModelResponse, run_messages: RunMessages, run_context: Optional[RunContext] = None
) -> None:
    """Parse the model response using the parser model."""
    if team.parser_model is None:
        return

    # Get output_schema from run_context
    output_schema = run_context.output_schema if run_context else None

    if output_schema is not None:
        parser_response_format = get_response_format(team, team.parser_model, run_context=run_context)
        messages_for_parser_model = team._get_messages_for_parser_model(
            model_response, parser_response_format, run_context=run_context
        )
        parser_model_response: ModelResponse = team.parser_model.response(
            messages=messages_for_parser_model,
            response_format=parser_response_format,
        )
        process_parser_response(team, model_response, run_messages, parser_model_response, messages_for_parser_model)
    else:
        log_warning("A response model is required to parse the response with a parser model")


async def aparse_response_with_parser_model(
    team: "Team", model_response: ModelResponse, run_messages: RunMessages, run_context: Optional[RunContext] = None
) -> None:
    """Parse the model response using the parser model."""
    if team.parser_model is None:
        return

    # Get output_schema from run_context
    output_schema = run_context.output_schema if run_context else None

    if output_schema is not None:
        parser_response_format = get_response_format(team, team.parser_model, run_context=run_context)
        messages_for_parser_model = team._get_messages_for_parser_model(
            model_response, parser_response_format, run_context=run_context
        )
        parser_model_response: ModelResponse = await team.parser_model.aresponse(
            messages=messages_for_parser_model,
            response_format=parser_response_format,
        )
        process_parser_response(team, model_response, run_messages, parser_model_response, messages_for_parser_model)
    else:
        log_warning("A response model is required to parse the response with a parser model")


def parse_response_with_parser_model_stream(
    team: "Team",
    session: TeamSession,
    run_response: TeamRunOutput,
    stream_events: bool = False,
    run_context: Optional[RunContext] = None,
):
    """Parse the model response using the parser model"""
    if team.parser_model is not None:
        # run_context override for output_schema
        # Get output_schema from run_context
        output_schema = run_context.output_schema if run_context else None

        if output_schema is not None:
            if stream_events:
                yield handle_event(  # type: ignore
                    create_team_parser_model_response_started_event(run_response),
                    run_response,
                    events_to_skip=team.events_to_skip,
                    store_events=team.store_events,
                )

            parser_model_response = ModelResponse(content="")
            parser_response_format = get_response_format(team, team.parser_model, run_context=run_context)
            messages_for_parser_model = team._get_messages_for_parser_model_stream(
                run_response, parser_response_format, run_context=run_context
            )
            for model_response_event in team.parser_model.response_stream(
                messages=messages_for_parser_model,
                response_format=parser_response_format,
                stream_model_response=False,
            ):
                yield from team._handle_model_response_chunk(
                    session=session,
                    run_response=run_response,
                    full_model_response=parser_model_response,
                    model_response_event=model_response_event,
                    parse_structured_output=True,
                    stream_events=stream_events,
                    run_context=run_context,
                )

            run_response.content = parser_model_response.content

            parser_model_response_message: Optional[Message] = None
            for message in reversed(messages_for_parser_model):
                if message.role == "assistant":
                    parser_model_response_message = message
                    break
            if parser_model_response_message is not None:
                if run_response.messages is not None:
                    run_response.messages.append(parser_model_response_message)
            else:
                log_warning("Unable to parse response with parser model")

            if stream_events:
                yield handle_event(  # type: ignore
                    create_team_parser_model_response_completed_event(run_response),
                    run_response,
                    events_to_skip=team.events_to_skip,
                    store_events=team.store_events,
                )

        else:
            log_warning("A response model is required to parse the response with a parser model")


async def aparse_response_with_parser_model_stream(
    team: "Team",
    session: TeamSession,
    run_response: TeamRunOutput,
    stream_events: bool = False,
    run_context: Optional[RunContext] = None,
):
    """Parse the model response using the parser model stream."""
    if team.parser_model is not None:
        # run_context override for output_schema
        # Get output_schema from run_context
        output_schema = run_context.output_schema if run_context else None

        if output_schema is not None:
            if stream_events:
                yield handle_event(  # type: ignore
                    create_team_parser_model_response_started_event(run_response),
                    run_response,
                    events_to_skip=team.events_to_skip,
                    store_events=team.store_events,
                )

            parser_model_response = ModelResponse(content="")
            parser_response_format = get_response_format(team, team.parser_model, run_context=run_context)
            messages_for_parser_model = team._get_messages_for_parser_model_stream(
                run_response, parser_response_format, run_context=run_context
            )
            model_response_stream = team.parser_model.aresponse_stream(
                messages=messages_for_parser_model,
                response_format=parser_response_format,
                stream_model_response=False,
            )
            async for model_response_event in model_response_stream:  # type: ignore
                for event in team._handle_model_response_chunk(
                    session=session,
                    run_response=run_response,
                    full_model_response=parser_model_response,
                    model_response_event=model_response_event,
                    parse_structured_output=True,
                    stream_events=stream_events,
                    run_context=run_context,
                ):
                    yield event

            run_response.content = parser_model_response.content

            parser_model_response_message: Optional[Message] = None
            for message in reversed(messages_for_parser_model):
                if message.role == "assistant":
                    parser_model_response_message = message
                    break
            if parser_model_response_message is not None:
                if run_response.messages is not None:
                    run_response.messages.append(parser_model_response_message)
            else:
                log_warning("Unable to parse response with parser model")

            if stream_events:
                yield handle_event(  # type: ignore
                    create_team_parser_model_response_completed_event(run_response),
                    run_response,
                    events_to_skip=team.events_to_skip,
                    store_events=team.store_events,
                )
        else:
            log_warning("A response model is required to parse the response with a parser model")


# ---------------------------------------------------------------------------
# Output model helpers
# ---------------------------------------------------------------------------


def parse_response_with_output_model(team: "Team", model_response: ModelResponse, run_messages: RunMessages) -> None:
    """Parse the model response using the output model."""
    if team.output_model is None:
        return

    messages_for_output_model = team._get_messages_for_output_model(run_messages.messages)
    output_model_response: ModelResponse = team.output_model.response(messages=messages_for_output_model)
    model_response.content = output_model_response.content


def generate_response_with_output_model_stream(
    team: "Team",
    session: TeamSession,
    run_response: TeamRunOutput,
    run_messages: RunMessages,
    stream_events: bool = False,
):
    """Parse the model response using the output model stream."""
    from agno.utils.events import (
        create_team_output_model_response_completed_event,
        create_team_output_model_response_started_event,
    )

    if team.output_model is None:
        return

    if stream_events:
        yield handle_event(  # type: ignore
            create_team_output_model_response_started_event(run_response),
            run_response,
            events_to_skip=team.events_to_skip,
            store_events=team.store_events,
        )

    messages_for_output_model = team._get_messages_for_output_model(run_messages.messages)
    model_response = ModelResponse(content="")

    for model_response_event in team.output_model.response_stream(messages=messages_for_output_model):
        yield from team._handle_model_response_chunk(
            session=session,
            run_response=run_response,
            full_model_response=model_response,
            model_response_event=model_response_event,
        )

    # Update the TeamRunResponse content
    run_response.content = model_response.content

    if stream_events:
        yield handle_event(  # type: ignore
            create_team_output_model_response_completed_event(run_response),
            run_response,
            events_to_skip=team.events_to_skip,
            store_events=team.store_events,
        )

    # Build a list of messages that should be added to the RunResponse
    messages_for_run_response = [m for m in run_messages.messages if m.add_to_agent_memory]
    # Update the RunResponse messages
    run_response.messages = messages_for_run_response
    # Update the RunResponse metrics
    run_response.metrics = calculate_metrics(team, messages_for_run_response, current_run_metrics=run_response.metrics)


async def agenerate_response_with_output_model(
    team: "Team", model_response: ModelResponse, run_messages: RunMessages
) -> None:
    """Parse the model response using the output model stream."""
    if team.output_model is None:
        return

    messages_for_output_model = team._get_messages_for_output_model(run_messages.messages)
    output_model_response: ModelResponse = await team.output_model.aresponse(messages=messages_for_output_model)
    model_response.content = output_model_response.content


async def agenerate_response_with_output_model_stream(
    team: "Team",
    session: TeamSession,
    run_response: TeamRunOutput,
    run_messages: RunMessages,
    stream_events: bool = False,
):
    """Parse the model response using the output model stream."""
    from agno.utils.events import (
        create_team_output_model_response_completed_event,
        create_team_output_model_response_started_event,
    )

    if team.output_model is None:
        return

    if stream_events:
        yield handle_event(  # type: ignore
            create_team_output_model_response_started_event(run_response),
            run_response,
            events_to_skip=team.events_to_skip,
            store_events=team.store_events,
        )

    messages_for_output_model = team._get_messages_for_output_model(run_messages.messages)
    model_response = ModelResponse(content="")

    async for model_response_event in team.output_model.aresponse_stream(messages=messages_for_output_model):
        for event in team._handle_model_response_chunk(
            session=session,
            run_response=run_response,
            full_model_response=model_response,
            model_response_event=model_response_event,
        ):
            yield event

    # Update the TeamRunResponse content
    run_response.content = model_response.content

    if stream_events:
        yield handle_event(  # type: ignore
            create_team_output_model_response_completed_event(run_response),
            run_response,
            events_to_skip=team.events_to_skip,
            store_events=team.store_events,
        )

    # Build a list of messages that should be added to the RunResponse
    messages_for_run_response = [m for m in run_messages.messages if m.add_to_agent_memory]
    # Update the RunResponse messages
    run_response.messages = messages_for_run_response
    # Update the RunResponse metrics
    run_response.metrics = calculate_metrics(team, messages_for_run_response, current_run_metrics=run_response.metrics)


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------


def calculate_metrics(team: "Team", messages: List[Message], current_run_metrics: Optional[Metrics] = None) -> Metrics:
    metrics = current_run_metrics or Metrics()
    assistant_message_role = team.model.assistant_message_role if team.model is not None else "assistant"

    for m in messages:
        if m.role == assistant_message_role and m.metrics is not None and m.from_history is False:
            metrics += m.metrics

    # If the run metrics were already initialized, keep the time related metrics
    if current_run_metrics is not None:
        metrics.timer = current_run_metrics.timer
        metrics.duration = current_run_metrics.duration
        metrics.time_to_first_token = current_run_metrics.time_to_first_token

    return metrics


def get_session_metrics(team: "Team", session: TeamSession) -> Metrics:
    # Get the session_metrics from the database
    if session.session_data is not None and "session_metrics" in session.session_data:
        session_metrics_from_db = session.session_data.get("session_metrics")
        if session_metrics_from_db is not None:
            if isinstance(session_metrics_from_db, dict):
                return Metrics(**session_metrics_from_db)
            elif isinstance(session_metrics_from_db, Metrics):
                return session_metrics_from_db

    return Metrics()


def update_session_metrics(team: "Team", session: TeamSession, run_response: TeamRunOutput) -> None:
    """Calculate session metrics"""
    session_metrics = get_session_metrics(team, session=session)
    # Add the metrics for the current run to the session metrics
    if run_response.metrics is not None:
        session_metrics += run_response.metrics
    session_metrics.time_to_first_token = None
    if session.session_data is not None:
        session.session_data["session_metrics"] = session_metrics


# ---------------------------------------------------------------------------
# Reasoning
# ---------------------------------------------------------------------------


def format_reasoning_step_content(team: "Team", run_response: TeamRunOutput, reasoning_step: ReasoningStep) -> str:
    """Format content for a reasoning step without changing any existing logic."""
    step_content = ""
    if reasoning_step.title:
        step_content += f"## {reasoning_step.title}\n"
    if reasoning_step.reasoning:
        step_content += f"{reasoning_step.reasoning}\n"
    if reasoning_step.action:
        step_content += f"Action: {reasoning_step.action}\n"
    if reasoning_step.result:
        step_content += f"Result: {reasoning_step.result}\n"
    step_content += "\n"

    # Get the current reasoning_content and append this step
    current_reasoning_content = ""
    if hasattr(run_response, "reasoning_content") and run_response.reasoning_content:
        current_reasoning_content = run_response.reasoning_content

    # Create updated reasoning_content
    updated_reasoning_content = current_reasoning_content + step_content

    return updated_reasoning_content


def handle_reasoning_event(
    team: "Team",
    event: "ReasoningEvent",
    run_response: TeamRunOutput,
    stream_events: bool,
) -> Iterator[TeamRunOutputEvent]:
    """
    Convert a ReasoningEvent from the ReasoningManager to Team-specific TeamRunOutputEvents.

    This method handles the conversion of generic reasoning events to Team events,
    keeping the Team._reason() method clean and simple.
    """
    from agno.reasoning.manager import ReasoningEventType

    if event.event_type == ReasoningEventType.started:
        if stream_events:
            yield handle_event(  # type: ignore
                create_team_reasoning_started_event(from_run_response=run_response),
                run_response,
                events_to_skip=team.events_to_skip,
                store_events=team.store_events,
            )

    elif event.event_type == ReasoningEventType.content_delta:
        if stream_events and event.reasoning_content:
            yield handle_event(  # type: ignore
                create_team_reasoning_content_delta_event(
                    from_run_response=run_response,
                    reasoning_content=event.reasoning_content,
                ),
                run_response,
                events_to_skip=team.events_to_skip,
                store_events=team.store_events,
            )

    elif event.event_type == ReasoningEventType.step:
        if event.reasoning_step:
            # Update run_response with this step
            update_run_output_with_reasoning(
                run_response=run_response,
                reasoning_steps=[event.reasoning_step],
                reasoning_agent_messages=[],
            )
            if stream_events:
                updated_reasoning_content = format_reasoning_step_content(
                    team,
                    run_response=run_response,
                    reasoning_step=event.reasoning_step,
                )
                yield handle_event(  # type: ignore
                    create_team_reasoning_step_event(
                        from_run_response=run_response,
                        reasoning_step=event.reasoning_step,
                        reasoning_content=updated_reasoning_content,
                    ),
                    run_response,
                    events_to_skip=team.events_to_skip,
                    store_events=team.store_events,
                )

    elif event.event_type == ReasoningEventType.completed:
        if event.message and event.reasoning_steps:
            update_run_output_with_reasoning(
                run_response=run_response,
                reasoning_steps=event.reasoning_steps,
                reasoning_agent_messages=event.reasoning_messages,
            )
        if stream_events:
            yield handle_event(  # type: ignore
                create_team_reasoning_completed_event(
                    from_run_response=run_response,
                    content=ReasoningSteps(reasoning_steps=event.reasoning_steps),
                    content_type=ReasoningSteps.__name__,
                ),
                run_response,
                events_to_skip=team.events_to_skip,
                store_events=team.store_events,
            )

    elif event.event_type == ReasoningEventType.error:
        log_warning(f"Reasoning error. {event.error}, continuing regular session...")


def handle_reasoning(
    team: "Team", run_response: TeamRunOutput, run_messages: RunMessages, run_context: Optional[RunContext] = None
) -> None:
    if team.reasoning or team.reasoning_model is not None:
        reasoning_generator = reason(
            team, run_response=run_response, run_messages=run_messages, run_context=run_context, stream_events=False
        )

        # Consume the generator without yielding
        deque(reasoning_generator, maxlen=0)


def handle_reasoning_stream(
    team: "Team",
    run_response: TeamRunOutput,
    run_messages: RunMessages,
    run_context: Optional[RunContext] = None,
    stream_events: bool = False,
) -> Iterator[TeamRunOutputEvent]:
    if team.reasoning or team.reasoning_model is not None:
        reasoning_generator = reason(
            team,
            run_response=run_response,
            run_messages=run_messages,
            run_context=run_context,
            stream_events=stream_events,
        )
        yield from reasoning_generator


async def ahandle_reasoning(
    team: "Team", run_response: TeamRunOutput, run_messages: RunMessages, run_context: Optional[RunContext] = None
) -> None:
    if team.reasoning or team.reasoning_model is not None:
        reason_generator = areason(
            team, run_response=run_response, run_messages=run_messages, run_context=run_context, stream_events=False
        )
        # Consume the generator without yielding
        async for _ in reason_generator:
            pass


async def ahandle_reasoning_stream(
    team: "Team",
    run_response: TeamRunOutput,
    run_messages: RunMessages,
    run_context: Optional[RunContext] = None,
    stream_events: bool = False,
) -> AsyncIterator[TeamRunOutputEvent]:
    if team.reasoning or team.reasoning_model is not None:
        reason_generator = areason(
            team,
            run_response=run_response,
            run_messages=run_messages,
            run_context=run_context,
            stream_events=stream_events,
        )
        async for item in reason_generator:
            yield item


def reason(
    team: "Team",
    run_response: TeamRunOutput,
    run_messages: RunMessages,
    run_context: Optional[RunContext] = None,
    stream_events: bool = False,
) -> Iterator[TeamRunOutputEvent]:
    """
    Run reasoning using the ReasoningManager.

    Handles both native reasoning models (DeepSeek, Anthropic, etc.) and
    default Chain-of-Thought reasoning with a clean, unified interface.
    """
    from agno.reasoning.manager import ReasoningConfig, ReasoningManager

    # Get the reasoning model (use copy of main model if not provided)
    reasoning_model: Optional[Model] = team.reasoning_model
    if reasoning_model is None and team.model is not None:
        from copy import deepcopy

        reasoning_model = deepcopy(team.model)

    # Create reasoning manager with config
    manager = ReasoningManager(
        ReasoningConfig(
            reasoning_model=reasoning_model,
            reasoning_agent=team.reasoning_agent,
            min_steps=team.reasoning_min_steps,
            max_steps=team.reasoning_max_steps,
            tools=team.tools if isinstance(team.tools, list) else None,
            tool_call_limit=team.tool_call_limit,
            use_json_mode=team.use_json_mode,
            telemetry=team.telemetry,
            debug_mode=team.debug_mode,
            debug_level=team.debug_level,
            run_context=run_context,
        )
    )

    # Use the unified reason() method and convert events
    for event in manager.reason(run_messages, stream=stream_events):
        yield from handle_reasoning_event(team, event, run_response, stream_events)


async def areason(
    team: "Team",
    run_response: TeamRunOutput,
    run_messages: RunMessages,
    run_context: Optional[RunContext] = None,
    stream_events: bool = False,
) -> AsyncIterator[TeamRunOutputEvent]:
    """
    Run reasoning asynchronously using the ReasoningManager.

    Handles both native reasoning models (DeepSeek, Anthropic, etc.) and
    default Chain-of-Thought reasoning with a clean, unified interface.
    """
    from agno.reasoning.manager import ReasoningConfig, ReasoningManager

    # Get the reasoning model (use copy of main model if not provided)
    reasoning_model: Optional[Model] = team.reasoning_model
    if reasoning_model is None and team.model is not None:
        from copy import deepcopy

        reasoning_model = deepcopy(team.model)

    # Create reasoning manager with config
    manager = ReasoningManager(
        ReasoningConfig(
            reasoning_model=reasoning_model,
            reasoning_agent=team.reasoning_agent,
            min_steps=team.reasoning_min_steps,
            max_steps=team.reasoning_max_steps,
            tools=team.tools if isinstance(team.tools, list) else None,
            tool_call_limit=team.tool_call_limit,
            use_json_mode=team.use_json_mode,
            telemetry=team.telemetry,
            debug_mode=team.debug_mode,
            debug_level=team.debug_level,
            run_context=run_context,
        )
    )

    # Use the unified areason() method and convert events
    async for event in manager.areason(run_messages, stream=stream_events):
        for output_event in handle_reasoning_event(team, event, run_response, stream_events):
            yield output_event


# ---------------------------------------------------------------------------
# Tool-call reasoning update
# ---------------------------------------------------------------------------


def update_reasoning_content_from_tool_call(
    team: "Team", run_response: TeamRunOutput, tool_name: str, tool_args: Dict[str, Any]
) -> Optional[ReasoningStep]:
    """Update reasoning_content based on tool calls that look like thinking or reasoning tools."""

    # Case 1: ReasoningTools.think (has title, thought, optional action and confidence)
    if tool_name.lower() == "think" and "title" in tool_args and "thought" in tool_args:
        title = tool_args["title"]
        thought = tool_args["thought"]
        action = tool_args.get("action", "")
        confidence = tool_args.get("confidence", None)

        # Create a reasoning step
        reasoning_step = ReasoningStep(
            title=title,
            reasoning=thought,
            action=action,
            result=None,
            next_action=NextAction.CONTINUE,
            confidence=confidence,
        )

        # Add the step to the run response
        add_reasoning_step_to_metadata(run_response, reasoning_step)

        formatted_content = f"## {title}\n{thought}\n"
        if action:
            formatted_content += f"Action: {action}\n"
        if confidence is not None:
            formatted_content += f"Confidence: {confidence}\n"
        formatted_content += "\n"

        append_to_reasoning_content(run_response, formatted_content)
        return reasoning_step

    # Case 2: ReasoningTools.analyze (has title, result, analysis, optional next_action and confidence)
    elif tool_name.lower() == "analyze" and "title" in tool_args:
        title = tool_args["title"]
        result = tool_args.get("result", "")
        analysis = tool_args.get("analysis", "")
        next_action = tool_args.get("next_action", "")
        confidence = tool_args.get("confidence", None)

        # Map string next_action to enum
        next_action_enum = NextAction.CONTINUE
        if next_action.lower() == "validate":
            next_action_enum = NextAction.VALIDATE
        elif next_action.lower() in ["final", "final_answer", "finalize"]:
            next_action_enum = NextAction.FINAL_ANSWER

        # Create a reasoning step
        reasoning_step = ReasoningStep(
            title=title,
            action=None,
            result=result,
            reasoning=analysis,
            next_action=next_action_enum,
            confidence=confidence,
        )

        # Add the step to the run response
        add_reasoning_step_to_metadata(run_response, reasoning_step)

        formatted_content = f"## {title}\n"
        if result:
            formatted_content += f"Result: {result}\n"
        if analysis:
            formatted_content += f"{analysis}\n"
        if next_action and next_action.lower() != "continue":
            formatted_content += f"Next Action: {next_action}\n"
        if confidence is not None:
            formatted_content += f"Confidence: {confidence}\n"
        formatted_content += "\n"

        append_to_reasoning_content(run_response, formatted_content)
        return reasoning_step

    # Case 3: ReasoningTool.think (simple format, just has 'thought')
    elif tool_name.lower() == "think" and "thought" in tool_args:
        thought = tool_args["thought"]
        reasoning_step = ReasoningStep(
            title="Thinking",
            action=None,
            result=None,
            reasoning=thought,
            next_action=None,
            confidence=None,
        )
        formatted_content = f"## Thinking\n{thought}\n\n"
        add_reasoning_step_to_metadata(run_response, reasoning_step)
        append_to_reasoning_content(run_response, formatted_content)
        return reasoning_step

    return None
