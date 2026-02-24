"""Response processing, reasoning, output format, and model response handling for Agent."""

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
    get_args,
)
from uuid import uuid4

from pydantic import BaseModel

if TYPE_CHECKING:
    from agno.agent.agent import Agent

from agno.media import Audio
from agno.models.base import Model
from agno.models.message import Message
from agno.models.response import ModelResponse, ModelResponseEvent
from agno.reasoning.step import NextAction, ReasoningStep, ReasoningSteps
from agno.run import RunContext
from agno.run.agent import RunEvent, RunOutput, RunOutputEvent
from agno.run.messages import RunMessages
from agno.run.requirement import RunRequirement
from agno.run.team import TeamRunOutputEvent
from agno.session import AgentSession
from agno.tools.function import Function
from agno.utils.events import (
    create_compression_completed_event,
    create_compression_started_event,
    create_model_request_completed_event,
    create_model_request_started_event,
    create_parser_model_response_completed_event,
    create_parser_model_response_started_event,
    create_reasoning_completed_event,
    create_reasoning_content_delta_event,
    create_reasoning_started_event,
    create_reasoning_step_event,
    create_run_output_content_event,
    create_tool_call_completed_event,
    create_tool_call_error_event,
    create_tool_call_started_event,
    handle_event,
)
from agno.utils.log import log_debug, log_warning
from agno.utils.merge_dict import merge_dictionaries
from agno.utils.reasoning import (
    add_reasoning_metrics_to_metadata,
    add_reasoning_step_to_metadata,
    append_to_reasoning_content,
    update_run_output_with_reasoning,
)
from agno.utils.string import parse_response_dict_str, parse_response_model_str

###########################################################################
# Reasoning
###########################################################################


def handle_reasoning(
    agent: Agent, run_response: RunOutput, run_messages: RunMessages, run_context: Optional[RunContext] = None
) -> None:
    if agent.reasoning or agent.reasoning_model is not None:
        reasoning_generator = reason(
            agent=agent,
            run_response=run_response,
            run_messages=run_messages,
            run_context=run_context,
            stream_events=False,
        )

        # Consume the generator without yielding
        deque(reasoning_generator, maxlen=0)


def handle_reasoning_stream(
    agent: Agent,
    run_response: RunOutput,
    run_messages: RunMessages,
    run_context: Optional[RunContext] = None,
    stream_events: Optional[bool] = None,
) -> Iterator[RunOutputEvent]:
    if agent.reasoning or agent.reasoning_model is not None:
        reasoning_generator = reason(
            agent=agent,
            run_response=run_response,
            run_messages=run_messages,
            run_context=run_context,
            stream_events=stream_events,
        )
        yield from reasoning_generator


async def ahandle_reasoning(
    agent: Agent, run_response: RunOutput, run_messages: RunMessages, run_context: Optional[RunContext] = None
) -> None:
    if agent.reasoning or agent.reasoning_model is not None:
        reason_generator = areason(
            agent=agent,
            run_response=run_response,
            run_messages=run_messages,
            run_context=run_context,
            stream_events=False,
        )
        # Consume the generator without yielding
        async for _ in reason_generator:  # type: ignore
            pass


async def ahandle_reasoning_stream(
    agent: Agent,
    run_response: RunOutput,
    run_messages: RunMessages,
    run_context: Optional[RunContext] = None,
    stream_events: Optional[bool] = None,
) -> AsyncIterator[RunOutputEvent]:
    if agent.reasoning or agent.reasoning_model is not None:
        reason_generator = areason(
            agent=agent,
            run_response=run_response,
            run_messages=run_messages,
            run_context=run_context,
            stream_events=stream_events,
        )
        async for item in reason_generator:  # type: ignore
            yield item


def format_reasoning_step_content(agent: Agent, run_response: RunOutput, reasoning_step: ReasoningStep) -> str:
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
    if hasattr(run_response, "reasoning_content") and run_response.reasoning_content:  # type: ignore
        current_reasoning_content = run_response.reasoning_content  # type: ignore

    # Create updated reasoning_content
    updated_reasoning_content = current_reasoning_content + step_content

    return updated_reasoning_content


def handle_reasoning_event(
    agent: Agent,
    event: "ReasoningEvent",  # type: ignore # noqa: F821
    run_response: RunOutput,
    stream_events: Optional[bool] = None,
) -> Iterator[RunOutputEvent]:
    """
    Convert a ReasoningEvent from the ReasoningManager to Agent-specific RunOutputEvents.

    This method handles the conversion of generic reasoning events to Agent events,
    keeping the Agent._reason() method clean and simple.
    """
    from agno.reasoning.manager import ReasoningEventType

    if event.event_type == ReasoningEventType.started:
        if stream_events:
            yield handle_event(  # type: ignore
                create_reasoning_started_event(from_run_response=run_response),
                run_response,
                events_to_skip=agent.events_to_skip,  # type: ignore
                store_events=agent.store_events,
            )

    elif event.event_type == ReasoningEventType.content_delta:
        if stream_events and event.reasoning_content:
            yield handle_event(  # type: ignore
                create_reasoning_content_delta_event(
                    from_run_response=run_response,
                    reasoning_content=event.reasoning_content,
                ),
                run_response,
                events_to_skip=agent.events_to_skip,  # type: ignore
                store_events=agent.store_events,
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
                    agent=agent,
                    run_response=run_response,
                    reasoning_step=event.reasoning_step,
                )
                yield handle_event(  # type: ignore
                    create_reasoning_step_event(
                        from_run_response=run_response,
                        reasoning_step=event.reasoning_step,
                        reasoning_content=updated_reasoning_content,
                    ),
                    run_response,
                    events_to_skip=agent.events_to_skip,  # type: ignore
                    store_events=agent.store_events,
                )

    elif event.event_type == ReasoningEventType.completed:
        if event.message and event.reasoning_steps:
            # This is from native reasoning - update with the message and steps
            update_run_output_with_reasoning(
                run_response=run_response,
                reasoning_steps=event.reasoning_steps,
                reasoning_agent_messages=event.reasoning_messages,
            )
        if stream_events:
            yield handle_event(  # type: ignore
                create_reasoning_completed_event(
                    from_run_response=run_response,
                    content=ReasoningSteps(reasoning_steps=event.reasoning_steps),
                    content_type=ReasoningSteps.__name__,
                ),
                run_response,
                events_to_skip=agent.events_to_skip,  # type: ignore
                store_events=agent.store_events,
            )

    elif event.event_type == ReasoningEventType.error:
        log_warning(f"Reasoning error. {event.error}, continuing regular session...")


def reason(
    agent: Agent,
    run_response: RunOutput,
    run_messages: RunMessages,
    run_context: Optional[RunContext] = None,
    stream_events: Optional[bool] = None,
) -> Iterator[RunOutputEvent]:
    """
    Run reasoning using the ReasoningManager.

    Handles both native reasoning models (DeepSeek, Anthropic, etc.) and
    default Chain-of-Thought reasoning with a clean, unified interface.
    """
    from agno.reasoning.manager import ReasoningConfig, ReasoningManager

    # Get the reasoning model (use copy of main model if not provided)
    reasoning_model: Optional[Model] = agent.reasoning_model
    if reasoning_model is None and agent.model is not None:
        from copy import deepcopy

        reasoning_model = deepcopy(agent.model)

    # Create reasoning manager with config
    manager = ReasoningManager(
        ReasoningConfig(
            reasoning_model=reasoning_model,
            reasoning_agent=agent.reasoning_agent,
            min_steps=agent.reasoning_min_steps,
            max_steps=agent.reasoning_max_steps,
            tools=agent.tools if isinstance(agent.tools, list) else None,
            tool_call_limit=agent.tool_call_limit,
            use_json_mode=agent.use_json_mode,
            telemetry=agent.telemetry,
            debug_mode=agent.debug_mode,
            debug_level=agent.debug_level,
            run_context=run_context,
            run_response=run_response,
        )
    )

    # Use the unified reason() method and convert events
    for event in manager.reason(run_messages, stream=bool(stream_events)):
        yield from handle_reasoning_event(
            agent=agent, event=event, run_response=run_response, stream_events=stream_events
        )


async def areason(
    agent: Agent,
    run_response: RunOutput,
    run_messages: RunMessages,
    run_context: Optional[RunContext] = None,
    stream_events: Optional[bool] = None,
) -> AsyncIterator[RunOutputEvent]:
    """
    Run reasoning asynchronously using the ReasoningManager.

    Handles both native reasoning models (DeepSeek, Anthropic, etc.) and
    default Chain-of-Thought reasoning with a clean, unified interface.
    """
    from agno.reasoning.manager import ReasoningConfig, ReasoningManager

    # Get the reasoning model (use copy of main model if not provided)
    reasoning_model: Optional[Model] = agent.reasoning_model
    if reasoning_model is None and agent.model is not None:
        from copy import deepcopy

        reasoning_model = deepcopy(agent.model)

    # Create reasoning manager with config
    manager = ReasoningManager(
        ReasoningConfig(
            reasoning_model=reasoning_model,
            reasoning_agent=agent.reasoning_agent,
            min_steps=agent.reasoning_min_steps,
            max_steps=agent.reasoning_max_steps,
            tools=agent.tools if isinstance(agent.tools, list) else None,
            tool_call_limit=agent.tool_call_limit,
            use_json_mode=agent.use_json_mode,
            telemetry=agent.telemetry,
            debug_mode=agent.debug_mode,
            debug_level=agent.debug_level,
            run_context=run_context,
            run_response=run_response,
        )
    )

    # Use the unified areason() method and convert events
    async for event in manager.areason(run_messages, stream=bool(stream_events)):
        for output_event in handle_reasoning_event(
            agent=agent, event=event, run_response=run_response, stream_events=stream_events
        ):
            yield output_event


def process_parser_response(
    agent: Agent,
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
    agent: Agent,
    model_response: ModelResponse,
    run_messages: RunMessages,
    run_context: Optional[RunContext] = None,
    run_response: Optional[RunOutput] = None,
) -> None:
    """Parse the model response using the parser model."""
    from agno.agent._messages import get_messages_for_parser_model

    if agent.parser_model is None:
        return

    # Get output_schema from run_context
    output_schema = run_context.output_schema if run_context else None

    if output_schema is not None:
        parser_response_format = get_response_format(agent, agent.parser_model, run_context=run_context)
        messages_for_parser_model = get_messages_for_parser_model(
            agent, model_response, parser_response_format, run_context=run_context
        )
        parser_model_response: ModelResponse = agent.parser_model.response(
            messages=messages_for_parser_model,
            response_format=parser_response_format,
        )

        # Accumulate parser model metrics
        if run_response is not None:
            from agno.metrics import ModelType, accumulate_model_metrics

            accumulate_model_metrics(parser_model_response, agent.parser_model, ModelType.PARSER_MODEL, run_response)

        process_parser_response(
            agent=agent,
            model_response=model_response,
            run_messages=run_messages,
            parser_model_response=parser_model_response,
            messages_for_parser_model=messages_for_parser_model,
        )
    else:
        log_warning("A response model is required to parse the response with a parser model")


async def aparse_response_with_parser_model(
    agent: Agent,
    model_response: ModelResponse,
    run_messages: RunMessages,
    run_context: Optional[RunContext] = None,
    run_response: Optional[RunOutput] = None,
) -> None:
    """Parse the model response using the parser model."""
    from agno.agent._messages import get_messages_for_parser_model

    if agent.parser_model is None:
        return

    # Get output_schema from run_context
    output_schema = run_context.output_schema if run_context else None

    if output_schema is not None:
        parser_response_format = get_response_format(agent, agent.parser_model, run_context=run_context)
        messages_for_parser_model = get_messages_for_parser_model(
            agent, model_response, parser_response_format, run_context=run_context
        )
        parser_model_response: ModelResponse = await agent.parser_model.aresponse(
            messages=messages_for_parser_model,
            response_format=parser_response_format,
        )

        # Accumulate parser model metrics
        if run_response is not None:
            from agno.metrics import ModelType, accumulate_model_metrics

            accumulate_model_metrics(parser_model_response, agent.parser_model, ModelType.PARSER_MODEL, run_response)

        process_parser_response(
            agent=agent,
            model_response=model_response,
            run_messages=run_messages,
            parser_model_response=parser_model_response,
            messages_for_parser_model=messages_for_parser_model,
        )
    else:
        log_warning("A response model is required to parse the response with a parser model")


def parse_response_with_parser_model_stream(
    agent: Agent,
    session: AgentSession,
    run_response: RunOutput,
    stream_events: bool = True,
    run_context: Optional[RunContext] = None,
) -> Iterator[RunOutputEvent]:
    """Parse the model response using the parser model"""
    from agno.agent._messages import get_messages_for_parser_model_stream

    if agent.parser_model is not None:
        # Get output_schema from run_context
        output_schema = run_context.output_schema if run_context else None

        if output_schema is not None:
            if stream_events:
                yield handle_event(
                    create_parser_model_response_started_event(run_response),
                    run_response,
                    events_to_skip=agent.events_to_skip,  # type: ignore
                    store_events=agent.store_events,
                )

            parser_model_response = ModelResponse(content="")
            parser_response_format = get_response_format(agent, agent.parser_model, run_context=run_context)
            messages_for_parser_model = get_messages_for_parser_model_stream(
                agent, run_response, parser_response_format, run_context=run_context
            )
            for model_response_event in agent.parser_model.response_stream(
                messages=messages_for_parser_model,
                response_format=parser_response_format,
                stream_model_response=False,
                run_response=run_response,
            ):
                yield from handle_model_response_chunk(
                    agent,
                    session=session,
                    run_response=run_response,
                    model_response=parser_model_response,
                    model_response_event=model_response_event,
                    parse_structured_output=True,
                    stream_events=stream_events,
                    run_context=run_context,
                )

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
                yield handle_event(
                    create_parser_model_response_completed_event(run_response),
                    run_response,
                    events_to_skip=agent.events_to_skip,  # type: ignore
                    store_events=agent.store_events,
                )

        else:
            log_warning("A response model is required to parse the response with a parser model")


async def aparse_response_with_parser_model_stream(
    agent: Agent,
    session: AgentSession,
    run_response: RunOutput,
    stream_events: bool = True,
    run_context: Optional[RunContext] = None,
) -> AsyncIterator[RunOutputEvent]:
    """Parse the model response using the parser model stream."""
    from agno.agent._messages import get_messages_for_parser_model_stream

    if agent.parser_model is not None:
        # Get output_schema from run_context
        output_schema = run_context.output_schema if run_context else None

        if output_schema is not None:
            if stream_events:
                yield handle_event(
                    create_parser_model_response_started_event(run_response),
                    run_response,
                    events_to_skip=agent.events_to_skip,  # type: ignore
                    store_events=agent.store_events,
                )

            parser_model_response = ModelResponse(content="")
            parser_response_format = get_response_format(agent, agent.parser_model, run_context=run_context)
            messages_for_parser_model = get_messages_for_parser_model_stream(
                agent, run_response, parser_response_format, run_context=run_context
            )
            model_response_stream = agent.parser_model.aresponse_stream(
                messages=messages_for_parser_model,
                response_format=parser_response_format,
                stream_model_response=False,
                run_response=run_response,
            )
            async for model_response_event in model_response_stream:  # type: ignore
                for event in handle_model_response_chunk(
                    agent,
                    session=session,
                    run_response=run_response,
                    model_response=parser_model_response,
                    model_response_event=model_response_event,
                    parse_structured_output=True,
                    stream_events=stream_events,
                    run_context=run_context,
                ):
                    yield event

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
                yield handle_event(
                    create_parser_model_response_completed_event(run_response),
                    run_response,
                    events_to_skip=agent.events_to_skip,  # type: ignore
                    store_events=agent.store_events,
                )
        else:
            log_warning("A response model is required to parse the response with a parser model")


def generate_response_with_output_model(
    agent: Agent, model_response: ModelResponse, run_messages: RunMessages, run_response: Optional[RunOutput] = None
) -> None:
    """Parse the model response using the output model."""
    from agno.agent._messages import get_messages_for_output_model

    if agent.output_model is None:
        return

    messages_for_output_model = get_messages_for_output_model(agent, run_messages.messages)
    output_model_response: ModelResponse = agent.output_model.response(messages=messages_for_output_model)

    # Accumulate output model metrics
    if run_response is not None:
        from agno.metrics import ModelType, accumulate_model_metrics

        accumulate_model_metrics(output_model_response, agent.output_model, ModelType.OUTPUT_MODEL, run_response)

    model_response.content = output_model_response.content


def generate_response_with_output_model_stream(
    agent: Agent,
    session: AgentSession,
    run_response: RunOutput,
    run_messages: RunMessages,
    stream_events: bool = False,
) -> Iterator[RunOutputEvent]:
    """Parse the model response using the output model."""
    from agno.agent._messages import get_messages_for_output_model
    from agno.utils.events import (
        create_output_model_response_completed_event,
        create_output_model_response_started_event,
    )

    if agent.output_model is None:
        return

    if stream_events:
        yield handle_event(
            create_output_model_response_started_event(run_response),
            run_response,
            events_to_skip=agent.events_to_skip,  # type: ignore
            store_events=agent.store_events,
        )

    messages_for_output_model = get_messages_for_output_model(agent, run_messages.messages)

    model_response = ModelResponse(content="")

    for model_response_event in agent.output_model.response_stream(
        messages=messages_for_output_model, run_response=run_response
    ):
        yield from handle_model_response_chunk(
            agent,
            session=session,
            run_response=run_response,
            model_response=model_response,
            model_response_event=model_response_event,
            stream_events=stream_events,
        )

    if stream_events:
        yield handle_event(
            create_output_model_response_completed_event(run_response),
            run_response,
            events_to_skip=agent.events_to_skip,  # type: ignore
            store_events=agent.store_events,
        )

    # Build a list of messages that should be added to the RunResponse
    messages_for_run_response = [m for m in run_messages.messages if m.add_to_agent_memory]
    # Update the RunResponse messages
    run_response.messages = messages_for_run_response


async def agenerate_response_with_output_model(
    agent: Agent, model_response: ModelResponse, run_messages: RunMessages, run_response: Optional[RunOutput] = None
) -> None:
    """Parse the model response using the output model."""
    from agno.agent._messages import get_messages_for_output_model

    if agent.output_model is None:
        return

    messages_for_output_model = get_messages_for_output_model(agent, run_messages.messages)
    output_model_response: ModelResponse = await agent.output_model.aresponse(messages=messages_for_output_model)

    # Accumulate output model metrics
    if run_response is not None:
        from agno.metrics import ModelType, accumulate_model_metrics

        accumulate_model_metrics(output_model_response, agent.output_model, ModelType.OUTPUT_MODEL, run_response)

    model_response.content = output_model_response.content


async def agenerate_response_with_output_model_stream(
    agent: Agent,
    session: AgentSession,
    run_response: RunOutput,
    run_messages: RunMessages,
    stream_events: bool = False,
) -> AsyncIterator[RunOutputEvent]:
    """Parse the model response using the output model."""
    from agno.agent._messages import get_messages_for_output_model
    from agno.utils.events import (
        create_output_model_response_completed_event,
        create_output_model_response_started_event,
    )

    if agent.output_model is None:
        return

    if stream_events:
        yield handle_event(
            create_output_model_response_started_event(run_response),
            run_response,
            events_to_skip=agent.events_to_skip,  # type: ignore
            store_events=agent.store_events,
        )

    messages_for_output_model = get_messages_for_output_model(agent, run_messages.messages)

    model_response = ModelResponse(content="")

    model_response_stream = agent.output_model.aresponse_stream(
        messages=messages_for_output_model, run_response=run_response
    )

    async for model_response_event in model_response_stream:
        for event in handle_model_response_chunk(
            agent,
            session=session,
            run_response=run_response,
            model_response=model_response,
            model_response_event=model_response_event,
            stream_events=stream_events,
        ):
            yield event

    if stream_events:
        yield handle_event(
            create_output_model_response_completed_event(run_response),
            run_response,
            events_to_skip=agent.events_to_skip,  # type: ignore
            store_events=agent.store_events,
        )

    # Build a list of messages that should be added to the RunResponse
    messages_for_run_response = [m for m in run_messages.messages if m.add_to_agent_memory]
    # Update the RunResponse messages
    run_response.messages = messages_for_run_response


# ---------------------------------------------------------------------------
# Reasoning tool-call helpers
# ---------------------------------------------------------------------------


def update_reasoning_content_from_tool_call(
    agent: Agent, run_response: RunOutput, tool_name: str, tool_args: Dict[str, Any]
) -> Optional[ReasoningStep]:
    """Update reasoning_content based on tool calls that look like thinking or reasoning tools."""

    # Case 1: ReasoningTools.think (has title, thought, optional action and confidence)
    if tool_name.lower() == "think" and "title" in tool_args and "thought" in tool_args:
        title = tool_args["title"]
        thought = tool_args["thought"]
        action = tool_args.get("action", "")
        confidence = tool_args.get("confidence", None)

        reasoning_step = ReasoningStep(
            title=title,
            reasoning=thought,
            action=action,
            next_action=NextAction.CONTINUE,
            confidence=confidence,
            result=None,
        )

        add_reasoning_step_to_metadata(run_response=run_response, reasoning_step=reasoning_step)

        formatted_content = f"## {title}\n{thought}\n"
        if action:
            formatted_content += f"Action: {action}\n"
        if confidence is not None:
            formatted_content += f"Confidence: {confidence}\n"
        formatted_content += "\n"

        append_to_reasoning_content(run_response=run_response, content=formatted_content)
        return reasoning_step

    # Case 2: ReasoningTools.analyze (has title, result, analysis, optional next_action and confidence)
    elif tool_name.lower() == "analyze" and "title" in tool_args:
        title = tool_args["title"]
        result = tool_args.get("result", "")
        analysis = tool_args.get("analysis", "")
        next_action = tool_args.get("next_action", "")
        confidence = tool_args.get("confidence", None)

        next_action_enum = NextAction.CONTINUE
        if next_action.lower() == "validate":
            next_action_enum = NextAction.VALIDATE
        elif next_action.lower() in ["final", "final_answer", "finalize"]:
            next_action_enum = NextAction.FINAL_ANSWER

        reasoning_step = ReasoningStep(
            title=title,
            result=result,
            reasoning=analysis,
            next_action=next_action_enum,
            confidence=confidence,
            action=None,
        )

        add_reasoning_step_to_metadata(run_response=run_response, reasoning_step=reasoning_step)

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

        append_to_reasoning_content(run_response=run_response, content=formatted_content)
        return reasoning_step

    # Case 3: ReasoningTool.think (simple format, just has 'thought')
    elif tool_name.lower() == "think" and "thought" in tool_args:
        thought = tool_args["thought"]
        reasoning_step = ReasoningStep(  # type: ignore
            title="Thinking",
            reasoning=thought,
            confidence=None,
        )
        formatted_content = f"## Thinking\n{thought}\n\n"
        add_reasoning_step_to_metadata(run_response=run_response, reasoning_step=reasoning_step)
        append_to_reasoning_content(run_response=run_response, content=formatted_content)
        return reasoning_step

    return None


# ---------------------------------------------------------------------------
# Output format resolution
# ---------------------------------------------------------------------------


def model_should_return_structured_output(agent: Agent, run_context: Optional[RunContext] = None) -> bool:
    # Get output_schema from run_context
    output_schema = run_context.output_schema if run_context else None

    agent.model = cast(Model, agent.model)
    return bool(
        agent.model.supports_native_structured_outputs
        and output_schema is not None
        and (not agent.use_json_mode or agent.structured_outputs)
    )


def get_response_format(
    agent: Agent, model: Optional[Model] = None, run_context: Optional[RunContext] = None
) -> Optional[Union[Dict, Type[BaseModel]]]:
    # Get output_schema from run_context
    output_schema = run_context.output_schema if run_context else None

    model = cast(Model, model or agent.model)
    if output_schema is None:
        return None
    else:
        json_response_format: Dict[str, Any] = {"type": "json_object"}

        if model.supports_native_structured_outputs:
            if not agent.use_json_mode or agent.structured_outputs:
                log_debug("Setting Model.response_format to Agent.output_schema")
                return output_schema
            else:
                log_debug("Model supports native structured outputs but it is not enabled. Using JSON mode instead.")
                return json_response_format

        elif model.supports_json_schema_outputs:
            if agent.use_json_mode or (not agent.structured_outputs):
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
# Response conversion
# ---------------------------------------------------------------------------


def convert_response_to_structured_format(
    agent: Agent, run_response: Union[RunOutput, ModelResponse], run_context: Optional[RunContext] = None
):
    # Get output_schema from run_context
    output_schema = run_context.output_schema if run_context else None

    # Convert the response to the structured format if needed
    if output_schema is not None:
        # If the output schema is a dict, do not convert it into a BaseModel
        if isinstance(output_schema, dict):
            if isinstance(run_response.content, str):
                parsed_dict = parse_response_dict_str(run_response.content)
                if parsed_dict is not None:
                    run_response.content = parsed_dict
                    if isinstance(run_response, RunOutput):
                        run_response.content_type = "dict"
                else:
                    log_warning("Failed to parse JSON response against the provided output schema.")
        # If the output schema is a Pydantic model and parse_response is True, parse it into a BaseModel
        elif not isinstance(run_response.content, output_schema):
            if isinstance(run_response.content, str) and agent.parse_response:
                try:
                    structured_output = parse_response_model_str(run_response.content, output_schema)

                    # Update RunOutput
                    if structured_output is not None:
                        run_response.content = structured_output
                        if isinstance(run_response, RunOutput):
                            run_response.content_type = output_schema.__name__
                    else:
                        log_warning("Failed to convert response to output_schema")
                except Exception as e:
                    log_warning(f"Failed to convert response to output model: {e}")
            else:
                log_warning("Something went wrong. Run response content is not a string")


# ---------------------------------------------------------------------------
# Run response update
# ---------------------------------------------------------------------------


def update_run_response(
    agent: Agent,
    model_response: ModelResponse,
    run_response: RunOutput,
    run_messages: RunMessages,
    run_context: Optional[RunContext] = None,
):
    # Get output_schema from run_context
    output_schema = run_context.output_schema if run_context else None

    # Handle structured outputs
    if output_schema is not None and model_response.parsed is not None:
        # We get native structured outputs from the model
        if model_should_return_structured_output(agent, run_context=run_context):
            # Update the run_response content with the structured output
            run_response.content = model_response.parsed
            # Update the run_response content_type with the structured output class name
            run_response.content_type = "dict" if isinstance(output_schema, dict) else output_schema.__name__
    else:
        # Update the run_response content with the model response content
        run_response.content = model_response.content

    # Update the run_response reasoning content with the model response reasoning content
    if model_response.reasoning_content is not None:
        run_response.reasoning_content = model_response.reasoning_content
    if model_response.redacted_reasoning_content is not None:
        if run_response.reasoning_content is None:
            run_response.reasoning_content = model_response.redacted_reasoning_content
        else:
            run_response.reasoning_content += model_response.redacted_reasoning_content

    # Update the run_response citations with the model response citations
    if model_response.citations is not None:
        run_response.citations = model_response.citations
    if model_response.provider_data is not None:
        run_response.model_provider_data = model_response.provider_data

    # Update the run_response tools with the model response tool_executions
    if model_response.tool_executions is not None:
        if run_response.tools is None:
            run_response.tools = model_response.tool_executions
        else:
            run_response.tools.extend(model_response.tool_executions)

        # For Reasoning/Thinking/Knowledge Tools update reasoning_content in RunOutput
        for tool_call in model_response.tool_executions:
            tool_name = tool_call.tool_name or ""
            if tool_name.lower() in ["think", "analyze"]:
                tool_args = tool_call.tool_args or {}
                update_reasoning_content_from_tool_call(
                    agent,
                    run_response=run_response,
                    tool_name=tool_name,
                    tool_args=tool_args,
                )

    # Update the run_response audio with the model response audio
    if model_response.audio is not None:
        run_response.response_audio = model_response.audio

    # Update the run_response created_at with the model response created_at
    run_response.created_at = model_response.created_at

    # Build a list of messages that should be added to the RunOutput
    messages_for_run_response = [m for m in run_messages.messages if m.add_to_agent_memory]
    # Update the RunOutput messages
    run_response.messages = messages_for_run_response


# ---------------------------------------------------------------------------
# Model response streaming
# ---------------------------------------------------------------------------


def handle_model_response_stream(
    agent: Agent,
    session: AgentSession,
    run_response: RunOutput,
    run_messages: RunMessages,
    tools: Optional[List[Union[Function, dict]]] = None,
    response_format: Optional[Union[Dict, Type[BaseModel]]] = None,
    stream_events: bool = False,
    session_state: Optional[Dict[str, Any]] = None,
    run_context: Optional[RunContext] = None,
) -> Iterator[RunOutputEvent]:
    agent.model = cast(Model, agent.model)

    reasoning_state = {
        "reasoning_started": False,
        "reasoning_time_taken": 0.0,
    }
    model_response = ModelResponse(content="")

    # Get output_schema from run_context
    output_schema = run_context.output_schema if run_context else None
    should_parse_structured_output = output_schema is not None and agent.parse_response and agent.parser_model is None

    stream_model_response = True
    if should_parse_structured_output:
        log_debug("Response model set, model response is not streamed.")
        stream_model_response = False

    for model_response_event in agent.model.response_stream(
        messages=run_messages.messages,
        response_format=response_format,
        tools=tools,
        tool_choice=agent.tool_choice,
        tool_call_limit=agent.tool_call_limit,
        stream_model_response=stream_model_response,
        run_response=run_response,
        send_media_to_model=agent.send_media_to_model,
        compression_manager=agent.compression_manager if agent.compress_tool_results else None,
    ):
        # Handle LLM request events and compression events from ModelResponse
        if isinstance(model_response_event, ModelResponse):
            if model_response_event.event == ModelResponseEvent.model_request_started.value:
                if stream_events:
                    yield handle_event(  # type: ignore
                        create_model_request_started_event(
                            from_run_response=run_response,
                            model=agent.model.id,
                            model_provider=agent.model.provider,
                        ),
                        run_response,
                        events_to_skip=agent.events_to_skip,  # type: ignore
                        store_events=agent.store_events,
                    )
                continue

            if model_response_event.event == ModelResponseEvent.model_request_completed.value:
                if stream_events:
                    yield handle_event(  # type: ignore
                        create_model_request_completed_event(
                            from_run_response=run_response,
                            model=agent.model.id,
                            model_provider=agent.model.provider,
                            input_tokens=model_response_event.input_tokens,
                            output_tokens=model_response_event.output_tokens,
                            total_tokens=model_response_event.total_tokens,
                            time_to_first_token=model_response_event.time_to_first_token,
                            reasoning_tokens=model_response_event.reasoning_tokens,
                            cache_read_tokens=model_response_event.cache_read_tokens,
                            cache_write_tokens=model_response_event.cache_write_tokens,
                        ),
                        run_response,
                        events_to_skip=agent.events_to_skip,  # type: ignore
                        store_events=agent.store_events,
                    )
                continue

            # Handle compression events
            if model_response_event.event == ModelResponseEvent.compression_started.value:
                if stream_events:
                    yield handle_event(  # type: ignore
                        create_compression_started_event(from_run_response=run_response),
                        run_response,
                        events_to_skip=agent.events_to_skip,  # type: ignore
                        store_events=agent.store_events,
                    )
                continue

            if model_response_event.event == ModelResponseEvent.compression_completed.value:
                if stream_events:
                    stats = model_response_event.compression_stats or {}
                    yield handle_event(  # type: ignore
                        create_compression_completed_event(
                            from_run_response=run_response,
                            tool_results_compressed=stats.get("tool_results_compressed"),
                            original_size=stats.get("original_size"),
                            compressed_size=stats.get("compressed_size"),
                        ),
                        run_response,
                        events_to_skip=agent.events_to_skip,  # type: ignore
                        store_events=agent.store_events,
                    )
                continue

        yield from handle_model_response_chunk(
            agent,
            session=session,
            run_response=run_response,
            model_response=model_response,
            model_response_event=model_response_event,
            reasoning_state=reasoning_state,
            parse_structured_output=should_parse_structured_output,
            stream_events=stream_events,
            session_state=session_state,
            run_context=run_context,
        )

    # Update RunOutput
    # Build a list of messages that should be added to the RunOutput
    messages_for_run_response = [m for m in run_messages.messages if m.add_to_agent_memory]
    # Update the RunOutput messages
    run_response.messages = messages_for_run_response

    # Determine reasoning completed
    if stream_events and reasoning_state["reasoning_started"]:
        all_reasoning_steps: List[ReasoningStep] = []
        if run_response and run_response.reasoning_steps:
            all_reasoning_steps = cast(List[ReasoningStep], run_response.reasoning_steps)

        if all_reasoning_steps:
            add_reasoning_metrics_to_metadata(
                run_response=run_response,
                reasoning_time_taken=reasoning_state["reasoning_time_taken"],
            )
            yield handle_event(  # type: ignore
                create_reasoning_completed_event(
                    from_run_response=run_response,
                    content=ReasoningSteps(reasoning_steps=all_reasoning_steps),
                    content_type=ReasoningSteps.__name__,
                ),
                run_response,
                events_to_skip=agent.events_to_skip,  # type: ignore
                store_events=agent.store_events,
            )

    # Update the run_response audio if streaming
    if model_response.audio is not None:
        run_response.response_audio = model_response.audio


async def ahandle_model_response_stream(
    agent: Agent,
    session: AgentSession,
    run_response: RunOutput,
    run_messages: RunMessages,
    tools: Optional[List[Union[Function, dict]]] = None,
    response_format: Optional[Union[Dict, Type[BaseModel]]] = None,
    stream_events: bool = False,
    session_state: Optional[Dict[str, Any]] = None,
    run_context: Optional[RunContext] = None,
) -> AsyncIterator[RunOutputEvent]:
    agent.model = cast(Model, agent.model)

    reasoning_state = {
        "reasoning_started": False,
        "reasoning_time_taken": 0.0,
    }
    model_response = ModelResponse(content="")

    # Get output_schema from run_context
    output_schema = run_context.output_schema if run_context else None
    should_parse_structured_output = output_schema is not None and agent.parse_response and agent.parser_model is None

    stream_model_response = True
    if should_parse_structured_output:
        log_debug("Response model set, model response is not streamed.")
        stream_model_response = False

    model_response_stream = agent.model.aresponse_stream(
        messages=run_messages.messages,
        response_format=response_format,
        tools=tools,
        tool_choice=agent.tool_choice,
        tool_call_limit=agent.tool_call_limit,
        stream_model_response=stream_model_response,
        run_response=run_response,
        send_media_to_model=agent.send_media_to_model,
        compression_manager=agent.compression_manager if agent.compress_tool_results else None,
    )  # type: ignore

    async for model_response_event in model_response_stream:  # type: ignore
        # Handle LLM request events and compression events from ModelResponse
        if isinstance(model_response_event, ModelResponse):
            if model_response_event.event == ModelResponseEvent.model_request_started.value:
                if stream_events:
                    yield handle_event(  # type: ignore
                        create_model_request_started_event(
                            from_run_response=run_response,
                            model=agent.model.id,
                            model_provider=agent.model.provider,
                        ),
                        run_response,
                        events_to_skip=agent.events_to_skip,  # type: ignore
                        store_events=agent.store_events,
                    )
                continue

            if model_response_event.event == ModelResponseEvent.model_request_completed.value:
                if stream_events:
                    yield handle_event(  # type: ignore
                        create_model_request_completed_event(
                            from_run_response=run_response,
                            model=agent.model.id,
                            model_provider=agent.model.provider,
                            input_tokens=model_response_event.input_tokens,
                            output_tokens=model_response_event.output_tokens,
                            total_tokens=model_response_event.total_tokens,
                            time_to_first_token=model_response_event.time_to_first_token,
                            reasoning_tokens=model_response_event.reasoning_tokens,
                            cache_read_tokens=model_response_event.cache_read_tokens,
                            cache_write_tokens=model_response_event.cache_write_tokens,
                        ),
                        run_response,
                        events_to_skip=agent.events_to_skip,  # type: ignore
                        store_events=agent.store_events,
                    )
                continue

            # Handle compression events
            if model_response_event.event == ModelResponseEvent.compression_started.value:
                if stream_events:
                    yield handle_event(  # type: ignore
                        create_compression_started_event(from_run_response=run_response),
                        run_response,
                        events_to_skip=agent.events_to_skip,  # type: ignore
                        store_events=agent.store_events,
                    )
                continue

            if model_response_event.event == ModelResponseEvent.compression_completed.value:
                if stream_events:
                    stats = model_response_event.compression_stats or {}
                    yield handle_event(  # type: ignore
                        create_compression_completed_event(
                            from_run_response=run_response,
                            tool_results_compressed=stats.get("tool_results_compressed"),
                            original_size=stats.get("original_size"),
                            compressed_size=stats.get("compressed_size"),
                        ),
                        run_response,
                        events_to_skip=agent.events_to_skip,  # type: ignore
                        store_events=agent.store_events,
                    )
                continue

        for event in handle_model_response_chunk(
            agent,
            session=session,
            run_response=run_response,
            model_response=model_response,
            model_response_event=model_response_event,
            reasoning_state=reasoning_state,
            parse_structured_output=should_parse_structured_output,
            stream_events=stream_events,
            session_state=session_state,
            run_context=run_context,
        ):
            yield event

    # Update RunOutput
    # Build a list of messages that should be added to the RunOutput
    messages_for_run_response = [m for m in run_messages.messages if m.add_to_agent_memory]
    # Update the RunOutput messages
    run_response.messages = messages_for_run_response

    if stream_events and reasoning_state["reasoning_started"]:
        all_reasoning_steps: List[ReasoningStep] = []
        if run_response and run_response.reasoning_steps:
            all_reasoning_steps = cast(List[ReasoningStep], run_response.reasoning_steps)

        if all_reasoning_steps:
            add_reasoning_metrics_to_metadata(
                run_response=run_response,
                reasoning_time_taken=reasoning_state["reasoning_time_taken"],
            )
            yield handle_event(  # type: ignore
                create_reasoning_completed_event(
                    from_run_response=run_response,
                    content=ReasoningSteps(reasoning_steps=all_reasoning_steps),
                    content_type=ReasoningSteps.__name__,
                ),
                run_response,
                events_to_skip=agent.events_to_skip,  # type: ignore
                store_events=agent.store_events,
            )

    # Update the run_response audio if streaming
    if model_response.audio is not None:
        run_response.response_audio = model_response.audio


def handle_model_response_chunk(
    agent: Agent,
    session: AgentSession,
    run_response: RunOutput,
    model_response: ModelResponse,
    model_response_event: Union[ModelResponse, RunOutputEvent, TeamRunOutputEvent],
    reasoning_state: Optional[Dict[str, Any]] = None,
    parse_structured_output: bool = False,
    stream_events: bool = False,
    session_state: Optional[Dict[str, Any]] = None,
    run_context: Optional[RunContext] = None,
) -> Iterator[RunOutputEvent]:
    from agno.run.workflow import WorkflowRunOutputEvent

    if (
        isinstance(model_response_event, tuple(get_args(RunOutputEvent)))
        or isinstance(model_response_event, tuple(get_args(TeamRunOutputEvent)))
        or isinstance(model_response_event, tuple(get_args(WorkflowRunOutputEvent)))
    ):
        if model_response_event.event == RunEvent.custom_event:  # type: ignore
            model_response_event.agent_id = agent.id  # type: ignore
            model_response_event.agent_name = agent.name  # type: ignore
            model_response_event.session_id = session.session_id  # type: ignore
            model_response_event.run_id = run_response.run_id  # type: ignore

        # We just bubble the event up
        yield handle_event(  # type: ignore
            model_response_event,  # type: ignore
            run_response,
            events_to_skip=agent.events_to_skip,  # type: ignore
            store_events=agent.store_events,
        )
    else:
        model_response_event = cast(ModelResponse, model_response_event)
        # If the model response is an assistant_response, yield a RunOutput
        if model_response_event.event == ModelResponseEvent.assistant_response.value:
            content_type = "str"

            # Process content and thinking
            if model_response_event.content is not None:
                if parse_structured_output:
                    model_response.content = model_response_event.content
                    convert_response_to_structured_format(agent, model_response, run_context=run_context)

                    # Get output_schema from run_context
                    output_schema = run_context.output_schema if run_context else None
                    content_type = "dict" if isinstance(output_schema, dict) else output_schema.__name__  # type: ignore
                    run_response.content = model_response.content
                    run_response.content_type = content_type
                else:
                    model_response.content = (model_response.content or "") + model_response_event.content
                    run_response.content = model_response.content
                    run_response.content_type = "str"

            # Process reasoning content
            if model_response_event.reasoning_content is not None:
                model_response.reasoning_content = (
                    model_response.reasoning_content or ""
                ) + model_response_event.reasoning_content
                run_response.reasoning_content = model_response.reasoning_content

            if model_response_event.redacted_reasoning_content is not None:
                if not model_response.reasoning_content:
                    model_response.reasoning_content = model_response_event.redacted_reasoning_content
                else:
                    model_response.reasoning_content += model_response_event.redacted_reasoning_content
                run_response.reasoning_content = model_response.reasoning_content

            # Handle provider data (one chunk)
            if model_response_event.provider_data is not None:
                run_response.model_provider_data = model_response_event.provider_data

            # Handle citations (one chunk)
            if model_response_event.citations is not None:
                run_response.citations = model_response_event.citations

            # Only yield if we have content to show
            if content_type != "str":
                yield handle_event(  # type: ignore
                    create_run_output_content_event(
                        from_run_response=run_response,
                        content=model_response.content,
                        content_type=content_type,
                    ),
                    run_response,
                    events_to_skip=agent.events_to_skip,  # type: ignore
                    store_events=agent.store_events,
                )
            elif (
                model_response_event.content is not None
                or model_response_event.reasoning_content is not None
                or model_response_event.redacted_reasoning_content is not None
                or model_response_event.citations is not None
                or model_response_event.provider_data is not None
            ):
                yield handle_event(  # type: ignore
                    create_run_output_content_event(
                        from_run_response=run_response,
                        content=model_response_event.content,
                        reasoning_content=model_response_event.reasoning_content,
                        redacted_reasoning_content=model_response_event.redacted_reasoning_content,
                        citations=model_response_event.citations,
                        model_provider_data=model_response_event.provider_data,
                    ),
                    run_response,
                    events_to_skip=agent.events_to_skip,  # type: ignore
                    store_events=agent.store_events,
                )

            # Process audio
            if model_response_event.audio is not None:
                if model_response.audio is None:
                    model_response.audio = Audio(id=str(uuid4()), content=b"", transcript="")

                if model_response_event.audio.id is not None:
                    model_response.audio.id = model_response_event.audio.id  # type: ignore

                if model_response_event.audio.content is not None:
                    # Handle both base64 string and bytes content
                    if isinstance(model_response_event.audio.content, str):
                        # Decode base64 string to bytes
                        try:
                            import base64

                            decoded_content = base64.b64decode(model_response_event.audio.content)
                            if model_response.audio.content is None:
                                model_response.audio.content = b""
                            model_response.audio.content += decoded_content
                        except Exception:
                            # If decode fails, encode string as bytes
                            if model_response.audio.content is None:
                                model_response.audio.content = b""
                            model_response.audio.content += model_response_event.audio.content.encode("utf-8")
                    elif isinstance(model_response_event.audio.content, bytes):
                        # Content is already bytes
                        if model_response.audio.content is None:
                            model_response.audio.content = b""
                        model_response.audio.content += model_response_event.audio.content

                if model_response_event.audio.transcript is not None:
                    model_response.audio.transcript += model_response_event.audio.transcript  # type: ignore

                if model_response_event.audio.expires_at is not None:
                    model_response.audio.expires_at = model_response_event.audio.expires_at  # type: ignore
                if model_response_event.audio.mime_type is not None:
                    model_response.audio.mime_type = model_response_event.audio.mime_type  # type: ignore
                if model_response_event.audio.sample_rate is not None:
                    model_response.audio.sample_rate = model_response_event.audio.sample_rate
                if model_response_event.audio.channels is not None:
                    model_response.audio.channels = model_response_event.audio.channels

                # Yield the audio and transcript bit by bit
                run_response.response_audio = Audio(
                    id=model_response_event.audio.id,
                    content=model_response_event.audio.content,
                    transcript=model_response_event.audio.transcript,
                    sample_rate=model_response_event.audio.sample_rate,
                    channels=model_response_event.audio.channels,
                )
                run_response.created_at = model_response_event.created_at

                yield handle_event(  # type: ignore
                    create_run_output_content_event(
                        from_run_response=run_response,
                        response_audio=run_response.response_audio,
                    ),
                    run_response,
                    events_to_skip=agent.events_to_skip,  # type: ignore
                    store_events=agent.store_events,
                )

            if model_response_event.images is not None:
                yield handle_event(  # type: ignore
                    create_run_output_content_event(
                        from_run_response=run_response,
                        image=model_response_event.images[-1],
                    ),
                    run_response,
                    events_to_skip=agent.events_to_skip,  # type: ignore
                    store_events=agent.store_events,
                )

                if model_response.images is None:
                    model_response.images = []
                model_response.images.extend(model_response_event.images)
                # Store media in run_response if store_media is enabled
                if agent.store_media:
                    for image in model_response_event.images:
                        if run_response.images is None:
                            run_response.images = []
                        run_response.images.append(image)

        # Handle tool interruption events (HITL flow)
        elif model_response_event.event == ModelResponseEvent.tool_call_paused.value:
            # Add tool calls to the run_response
            tool_executions_list = model_response_event.tool_executions
            if tool_executions_list is not None:
                # Add tool calls to the agent.run_response
                if run_response.tools is None:
                    run_response.tools = tool_executions_list
                else:
                    run_response.tools.extend(tool_executions_list)
                # Add requirement to the run_response
                if run_response.requirements is None:
                    run_response.requirements = []
                run_response.requirements.append(RunRequirement(tool_execution=tool_executions_list[-1]))

        # If the model response is a tool_call_started, add the tool call to the run_response
        elif (
            model_response_event.event == ModelResponseEvent.tool_call_started.value
        ):  # Add tool calls to the run_response
            tool_executions_list = model_response_event.tool_executions
            if tool_executions_list is not None:
                # Add tool calls to the agent.run_response
                if run_response.tools is None:
                    run_response.tools = tool_executions_list
                else:
                    run_response.tools.extend(tool_executions_list)

                # Yield each tool call started event
                if stream_events:
                    for tool in tool_executions_list:
                        yield handle_event(  # type: ignore
                            create_tool_call_started_event(from_run_response=run_response, tool=tool),
                            run_response,
                            events_to_skip=agent.events_to_skip,  # type: ignore
                            store_events=agent.store_events,
                        )

        # If the model response is a tool_call_completed, update the existing tool call in the run_response
        elif model_response_event.event == ModelResponseEvent.tool_call_completed.value:
            if model_response_event.updated_session_state is not None:
                # update the session_state for RunOutput
                if session_state is not None:
                    merge_dictionaries(session_state, model_response_event.updated_session_state)
                # update the DB session
                if session.session_data is not None and session.session_data.get("session_state") is not None:
                    merge_dictionaries(
                        session.session_data["session_state"], model_response_event.updated_session_state
                    )

            if model_response_event.images is not None:
                for image in model_response_event.images:
                    if run_response.images is None:
                        run_response.images = []
                    run_response.images.append(image)

            if model_response_event.videos is not None:
                for video in model_response_event.videos:
                    if run_response.videos is None:
                        run_response.videos = []
                    run_response.videos.append(video)

            if model_response_event.audios is not None:
                for audio in model_response_event.audios:
                    if run_response.audio is None:
                        run_response.audio = []
                    run_response.audio.append(audio)

            if model_response_event.files is not None:
                for file_obj in model_response_event.files:
                    if run_response.files is None:
                        run_response.files = []
                    run_response.files.append(file_obj)

            reasoning_step: Optional[ReasoningStep] = None

            tool_executions_list = model_response_event.tool_executions
            if tool_executions_list is not None:
                # Update the existing tool call in the run_response
                if run_response.tools:
                    # Create a mapping of tool_call_id to index
                    tool_call_index_map = {
                        tc.tool_call_id: i for i, tc in enumerate(run_response.tools) if tc.tool_call_id is not None
                    }
                    # Process tool calls
                    for tool_call_dict in tool_executions_list:
                        tool_call_id = tool_call_dict.tool_call_id or ""
                        index = tool_call_index_map.get(tool_call_id)
                        if index is not None:
                            run_response.tools[index] = tool_call_dict
                else:
                    run_response.tools = tool_executions_list

                # Only iterate through new tool calls
                for tool_call in tool_executions_list:
                    tool_name = tool_call.tool_name or ""
                    if tool_name.lower() in ["think", "analyze"]:
                        tool_args = tool_call.tool_args or {}

                        reasoning_step = update_reasoning_content_from_tool_call(
                            agent,
                            run_response=run_response,
                            tool_name=tool_name,
                            tool_args=tool_args,
                        )

                        tool_call_metrics = tool_call.metrics

                        if (
                            tool_call_metrics is not None
                            and tool_call_metrics.duration is not None
                            and reasoning_state is not None
                        ):
                            reasoning_state["reasoning_time_taken"] = reasoning_state["reasoning_time_taken"] + float(
                                tool_call_metrics.duration
                            )

                    if stream_events:
                        yield handle_event(  # type: ignore
                            create_tool_call_completed_event(
                                from_run_response=run_response, tool=tool_call, content=model_response_event.content
                            ),
                            run_response,
                            events_to_skip=agent.events_to_skip,  # type: ignore
                            store_events=agent.store_events,
                        )
                        if tool_call.tool_call_error:
                            yield handle_event(  # type: ignore
                                create_tool_call_error_event(
                                    from_run_response=run_response, tool=tool_call, error=str(tool_call.result)
                                ),
                                run_response,
                                events_to_skip=agent.events_to_skip,  # type: ignore
                                store_events=agent.store_events,
                            )

            if stream_events:
                if reasoning_step is not None:
                    if reasoning_state and not reasoning_state["reasoning_started"]:
                        yield handle_event(  # type: ignore
                            create_reasoning_started_event(from_run_response=run_response),
                            run_response,
                            events_to_skip=agent.events_to_skip,  # type: ignore
                            store_events=agent.store_events,
                        )
                        reasoning_state["reasoning_started"] = True

                    yield handle_event(  # type: ignore
                        create_reasoning_step_event(
                            from_run_response=run_response,
                            reasoning_step=reasoning_step,
                            reasoning_content=run_response.reasoning_content or "",
                        ),
                        run_response,
                        events_to_skip=agent.events_to_skip,  # type: ignore
                        store_events=agent.store_events,
                    )
