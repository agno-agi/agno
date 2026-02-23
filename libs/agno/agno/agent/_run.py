"""Core run loop and execution helpers for Agent."""

from __future__ import annotations

import asyncio
import time
import warnings
from collections import deque
from typing import (
    TYPE_CHECKING,
    Any,
    AsyncIterator,
    Dict,
    Iterator,
    List,
    Optional,
    Sequence,
    Type,
    Union,
    cast,
)
from uuid import uuid4

from pydantic import BaseModel

if TYPE_CHECKING:
    from agno.agent.agent import Agent

from agno.agent._init import _initialize_session_state
from agno.agent._run_options import resolve_run_options
from agno.agent._session import initialize_session, update_session_metrics
from agno.exceptions import (
    InputCheckError,
    OutputCheckError,
    RunCancelledException,
)
from agno.filters import FilterExpr
from agno.media import Audio, File, Image, Video
from agno.models.base import Model
from agno.models.message import Message
from agno.models.metrics import RunMetrics
from agno.models.response import ModelResponse, ToolExecution
from agno.run import RunContext, RunStatus
from agno.run.agent import (
    RunInput,
    RunOutput,
    RunOutputEvent,
)
from agno.run.approval import (
    acreate_approval_from_pause,
    create_approval_from_pause,
)
from agno.run.cancel import (
    acancel_run as acancel_run_global,
)
from agno.run.cancel import (
    acleanup_run,
    araise_if_cancelled,
    aregister_run,
    cleanup_run,
    raise_if_cancelled,
    register_run,
)
from agno.run.cancel import (
    cancel_run as cancel_run_global,
)
from agno.run.messages import RunMessages
from agno.run.requirement import RunRequirement
from agno.session import AgentSession
from agno.tools.function import Function
from agno.utils.agent import (
    await_for_open_threads,
    await_for_thread_tasks_stream,
    scrub_history_messages_from_run_output,
    scrub_media_from_run_output,
    scrub_tool_results_from_run_output,
    store_media_util,
    validate_input,
    validate_media_object_id,
    wait_for_open_threads,
    wait_for_thread_tasks_stream,
)
from agno.utils.events import (
    add_error_event,
    create_run_cancelled_event,
    create_run_completed_event,
    create_run_content_completed_event,
    create_run_continued_event,
    create_run_error_event,
    create_run_paused_event,
    create_run_started_event,
    create_session_summary_completed_event,
    create_session_summary_started_event,
    handle_event,
)
from agno.utils.hooks import (
    normalize_post_hooks,
    normalize_pre_hooks,
)
from agno.utils.log import (
    log_debug,
    log_error,
    log_info,
    log_warning,
)
from agno.utils.response import get_paused_content

# Strong references to background tasks so they aren't garbage-collected mid-execution.
# See: https://docs.python.org/3/library/asyncio-task.html#asyncio.create_task
_background_tasks: set[asyncio.Task[None]] = set()

# ---------------------------------------------------------------------------
# Run dependency resolution
# ---------------------------------------------------------------------------


def resolve_run_dependencies(agent: Agent, run_context: RunContext) -> None:
    from inspect import iscoroutine, iscoroutinefunction, signature

    # Dependencies should already be resolved in run() method
    log_debug("Resolving dependencies")
    if not isinstance(run_context.dependencies, dict):
        log_warning("Run dependencies are not a dict")
        return

    for key, value in run_context.dependencies.items():
        if iscoroutine(value) or iscoroutinefunction(value):
            log_warning(f"Dependency {key} is a coroutine. Use agent.arun() or agent.aprint_response() instead.")
            continue
        elif callable(value):
            try:
                sig = signature(value)

                # Build kwargs for the function
                kwargs: Dict[str, Any] = {}
                if "agent" in sig.parameters:
                    kwargs["agent"] = agent
                if "run_context" in sig.parameters:
                    kwargs["run_context"] = run_context

                # Run the function
                result = value(**kwargs)

                # Carry the result in the run context
                if result is not None:
                    run_context.dependencies[key] = result

            except Exception as e:
                log_warning(f"Failed to resolve dependencies for '{key}': {e}")
        else:
            run_context.dependencies[key] = value


async def aresolve_run_dependencies(agent: Agent, run_context: RunContext) -> None:
    from inspect import iscoroutine, signature

    log_debug("Resolving context (async)")
    if not isinstance(run_context.dependencies, dict):
        log_warning("Run dependencies are not a dict")
        return

    for key, value in run_context.dependencies.items():
        if not callable(value):
            run_context.dependencies[key] = value
            continue
        try:
            sig = signature(value)

            # Build kwargs for the function
            kwargs: Dict[str, Any] = {}
            if "agent" in sig.parameters:
                kwargs["agent"] = agent
            if "run_context" in sig.parameters:
                kwargs["run_context"] = run_context

            # Run the function
            result = value(**kwargs)
            if iscoroutine(result):
                result = await result  # type: ignore

            run_context.dependencies[key] = result
        except Exception as e:
            log_warning(f"Failed to resolve context for '{key}': {e}")


# ---------------------------------------------------------------------------
# Pause handling
# ---------------------------------------------------------------------------


def handle_agent_run_paused(
    agent: Agent,
    run_response: RunOutput,
    session: AgentSession,
    user_id: Optional[str] = None,
    run_context: Optional[RunContext] = None,
) -> RunOutput:
    run_response.status = RunStatus.paused
    if not run_response.content:
        run_response.content = get_paused_content(run_response)

    cleanup_and_store(agent, run_response=run_response, session=session, run_context=run_context, user_id=user_id)
    create_approval_from_pause(
        db=agent.db, run_response=run_response, agent_id=agent.id, agent_name=agent.name, user_id=user_id
    )

    log_debug(f"Agent Run Paused: {run_response.run_id}", center=True, symbol="*")

    # We return and await confirmation/completion for the tools that require it
    return run_response


def handle_agent_run_paused_stream(
    agent: Agent,
    run_response: RunOutput,
    session: AgentSession,
    user_id: Optional[str] = None,
    run_context: Optional[RunContext] = None,
    yield_run_output: bool = False,
) -> Iterator[Union[RunOutputEvent, RunOutput]]:
    run_response.status = RunStatus.paused
    if not run_response.content:
        run_response.content = get_paused_content(run_response)

    # We return and await confirmation/completion for the tools that require it
    pause_event = handle_event(
        create_run_paused_event(
            from_run_response=run_response,
            tools=run_response.tools,
            requirements=run_response.requirements,
        ),
        run_response,
        events_to_skip=agent.events_to_skip,  # type: ignore
        store_events=agent.store_events,
    )

    cleanup_and_store(agent, run_response=run_response, session=session, run_context=run_context, user_id=user_id)
    create_approval_from_pause(
        db=agent.db, run_response=run_response, agent_id=agent.id, agent_name=agent.name, user_id=user_id
    )

    yield pause_event  # type: ignore

    # Also yield the run_response if requested, so callers can capture it
    if yield_run_output:
        yield run_response

    log_debug(f"Agent Run Paused: {run_response.run_id}", center=True, symbol="*")


async def ahandle_agent_run_paused(
    agent: Agent,
    run_response: RunOutput,
    session: AgentSession,
    user_id: Optional[str] = None,
    run_context: Optional[RunContext] = None,
) -> RunOutput:
    run_response.status = RunStatus.paused
    if not run_response.content:
        run_response.content = get_paused_content(run_response)

    await acleanup_and_store(
        agent, run_response=run_response, session=session, run_context=run_context, user_id=user_id
    )
    await acreate_approval_from_pause(
        db=agent.db, run_response=run_response, agent_id=agent.id, agent_name=agent.name, user_id=user_id
    )

    log_debug(f"Agent Run Paused: {run_response.run_id}", center=True, symbol="*")

    # We return and await confirmation/completion for the tools that require it
    return run_response


async def ahandle_agent_run_paused_stream(
    agent: Agent,
    run_response: RunOutput,
    session: AgentSession,
    user_id: Optional[str] = None,
    run_context: Optional[RunContext] = None,
    yield_run_output: bool = False,
) -> AsyncIterator[Union[RunOutputEvent, RunOutput]]:
    run_response.status = RunStatus.paused
    if not run_response.content:
        run_response.content = get_paused_content(run_response)

    # We return and await confirmation/completion for the tools that require it
    pause_event = handle_event(
        create_run_paused_event(
            from_run_response=run_response,
            tools=run_response.tools,
            requirements=run_response.requirements,
        ),
        run_response,
        events_to_skip=agent.events_to_skip,  # type: ignore
        store_events=agent.store_events,
    )

    await acleanup_and_store(
        agent, run_response=run_response, session=session, run_context=run_context, user_id=user_id
    )
    await acreate_approval_from_pause(
        db=agent.db, run_response=run_response, agent_id=agent.id, agent_name=agent.name, user_id=user_id
    )

    yield pause_event  # type: ignore

    # Also yield the run_response if requested, so callers can capture it
    if yield_run_output:
        yield run_response

    log_debug(f"Agent Run Paused: {run_response.run_id}", center=True, symbol="*")


def _run(
    agent: Agent,
    run_response: RunOutput,
    run_context: RunContext,
    session_id: str,
    user_id: Optional[str] = None,
    add_history_to_context: Optional[bool] = None,
    add_dependencies_to_context: Optional[bool] = None,
    add_session_state_to_context: Optional[bool] = None,
    response_format: Optional[Union[Dict, Type[BaseModel]]] = None,
    debug_mode: Optional[bool] = None,
    background_tasks: Optional[Any] = None,
    pre_session: Optional[AgentSession] = None,
    **kwargs: Any,
) -> RunOutput:
    """Run the Agent and return the RunOutput.

    Steps:
    1. Read or create session
    2. Update metadata and session state
    3. Resolve dependencies
    4. Execute pre-hooks
    5. Determine tools for model
    6. Prepare run messages
    7. Start memory creation in background thread
    8. Reason about the task if reasoning is enabled
    9. Generate a response from the Model (includes running function calls)
    10. Update the RunOutput with the model response
    11. Store media if enabled
    12. Convert the response to the structured format if needed
    13. Execute post-hooks
    14. Wait for background memory creation and cultural knowledge creation
    15. Create session summary
    16. Cleanup and store the run response and session
    """
    from agno.agent._hooks import execute_post_hooks, execute_pre_hooks
    from agno.agent._init import disconnect_connectable_tools
    from agno.agent._messages import get_run_messages
    from agno.agent._response import (
        convert_response_to_structured_format,
        generate_response_with_output_model,
        handle_reasoning,
        parse_response_with_parser_model,
        update_run_response,
    )
    from agno.agent._storage import load_session_state, read_or_create_session, update_metadata
    from agno.agent._telemetry import log_agent_telemetry
    from agno.agent._tools import determine_tools_for_model

    register_run(run_context.run_id)
    log_debug(f"Agent Run Start: {run_response.run_id}", center=True)

    memory_future = None
    learning_future = None
    cultural_knowledge_future = None
    agent_session: Optional[AgentSession] = None

    try:
        # Set up retry logic
        num_attempts = agent.retries + 1
        for attempt in range(num_attempts):
            if attempt > 0:
                log_debug(f"Retrying Agent run {run_response.run_id}. Attempt {attempt + 1} of {num_attempts}...")
            try:
                # 1. Read or create session. Reuse pre-read session on first attempt.
                if attempt == 0 and pre_session is not None:
                    agent_session = pre_session
                else:
                    agent_session = read_or_create_session(agent, session_id=session_id, user_id=user_id)

                # 2. Update metadata and session state
                if not (attempt == 0 and pre_session is not None):
                    update_metadata(agent, session=agent_session)

                # Initialize session state. Get it from DB if relevant.
                run_context.session_state = load_session_state(
                    agent,
                    session=agent_session,
                    session_state=run_context.session_state if run_context.session_state is not None else {},
                )
                _initialize_session_state(
                    run_context.session_state,
                    user_id=user_id,
                    session_id=session_id,
                    run_id=run_context.run_id,
                )

                # 3. Resolve dependencies
                if run_context.dependencies is not None:
                    resolve_run_dependencies(agent, run_context=run_context)

                # 4. Execute pre-hooks
                run_input = cast(RunInput, run_response.input)
                agent.model = cast(Model, agent.model)
                if agent.pre_hooks is not None:
                    # Can modify the run input
                    pre_hook_iterator = execute_pre_hooks(
                        agent,
                        hooks=agent.pre_hooks,  # type: ignore
                        run_response=run_response,
                        run_input=run_input,
                        run_context=run_context,
                        session=agent_session,
                        user_id=user_id,
                        debug_mode=debug_mode,
                        background_tasks=background_tasks,
                        **kwargs,
                    )
                    # Consume the generator without yielding
                    deque(pre_hook_iterator, maxlen=0)

                # 5. Determine tools for model
                processed_tools = agent.get_tools(
                    run_response=run_response,
                    run_context=run_context,
                    session=agent_session,
                    user_id=user_id,
                )
                _tools = determine_tools_for_model(
                    agent,
                    model=agent.model,
                    processed_tools=processed_tools,
                    run_response=run_response,
                    session=agent_session,
                    run_context=run_context,
                )

                # 6. Prepare run messages
                run_messages: RunMessages = get_run_messages(
                    agent,
                    run_response=run_response,
                    run_context=run_context,
                    input=run_input.input_content,
                    session=agent_session,
                    user_id=user_id,
                    audio=run_input.audios,
                    images=run_input.images,
                    videos=run_input.videos,
                    files=run_input.files,
                    add_history_to_context=add_history_to_context,
                    add_dependencies_to_context=add_dependencies_to_context,
                    add_session_state_to_context=add_session_state_to_context,
                    tools=_tools,
                    **kwargs,
                )
                if len(run_messages.messages) == 0:
                    log_error("No messages to be sent to the model.")

                # Start memory creation in background thread
                from agno.agent import _managers

                memory_future = _managers.start_memory_future(
                    agent,
                    run_messages=run_messages,
                    user_id=user_id,
                    existing_future=memory_future,
                    run_response=run_response,
                )

                # Start learning extraction as a background task (runs concurrently with the main execution)
                learning_future = _managers.start_learning_future(
                    agent,
                    run_messages=run_messages,
                    session=agent_session,
                    user_id=user_id,
                    existing_future=learning_future,
                    run_response=run_response,
                )

                # Start cultural knowledge creation in background thread
                cultural_knowledge_future = _managers.start_cultural_knowledge_future(
                    agent,
                    run_messages=run_messages,
                    existing_future=cultural_knowledge_future,
                    run_response=run_response,
                )

                raise_if_cancelled(run_response.run_id)  # type: ignore

                # 5. Reason about the task
                handle_reasoning(agent, run_response=run_response, run_messages=run_messages, run_context=run_context)

                # Check for cancellation before model call
                raise_if_cancelled(run_response.run_id)  # type: ignore

                # 6. Generate a response from the Model (includes running function calls)
                agent.model = cast(Model, agent.model)

                model_response: ModelResponse = agent.model.response(
                    messages=run_messages.messages,
                    tools=_tools,
                    tool_choice=agent.tool_choice,
                    tool_call_limit=agent.tool_call_limit,
                    response_format=response_format,
                    run_response=run_response,
                    send_media_to_model=agent.send_media_to_model,
                    compression_manager=agent.compression_manager if agent.compress_tool_results else None,
                )

                # Check for cancellation after model call
                raise_if_cancelled(run_response.run_id)  # type: ignore

                # If an output model is provided, generate output using the output model
                generate_response_with_output_model(agent, model_response, run_messages, run_response=run_response)

                # If a parser model is provided, structure the response separately
                parse_response_with_parser_model(
                    agent, model_response, run_messages, run_context=run_context, run_response=run_response
                )

                # 7. Update the RunOutput with the model response
                update_run_response(
                    agent,
                    model_response=model_response,
                    run_response=run_response,
                    run_messages=run_messages,
                    run_context=run_context,
                )

                # We should break out of the run function
                if any(tool_call.is_paused for tool_call in run_response.tools or []):
                    wait_for_open_threads(
                        memory_future=memory_future,  # type: ignore
                        cultural_knowledge_future=cultural_knowledge_future,  # type: ignore
                        learning_future=learning_future,  # type: ignore
                    )

                    return handle_agent_run_paused(
                        agent,
                        run_response=run_response,
                        session=agent_session,
                        run_context=run_context,
                        user_id=user_id,
                    )

                # 8. Store media if enabled
                if agent.store_media:
                    store_media_util(run_response, model_response)

                # 9. Convert the response to the structured format if needed
                convert_response_to_structured_format(agent, run_response, run_context=run_context)

                # 10. Execute post-hooks after output is generated but before response is returned
                if agent.post_hooks is not None:
                    post_hook_iterator = execute_post_hooks(
                        agent,
                        hooks=agent.post_hooks,  # type: ignore
                        run_output=run_response,
                        run_context=run_context,
                        session=agent_session,
                        user_id=user_id,
                        debug_mode=debug_mode,
                        background_tasks=background_tasks,
                        **kwargs,
                    )
                    deque(post_hook_iterator, maxlen=0)

                # Check for cancellation
                raise_if_cancelled(run_response.run_id)  # type: ignore

                # 11. Wait for background memory creation and cultural knowledge creation
                wait_for_open_threads(
                    memory_future=memory_future,  # type: ignore
                    cultural_knowledge_future=cultural_knowledge_future,  # type: ignore
                    learning_future=learning_future,  # type: ignore
                )

                # 12. Create session summary
                if agent.session_summary_manager is not None and agent.enable_session_summaries:
                    # Upsert the RunOutput to Agent Session before creating the session summary
                    agent_session.upsert_run(run=run_response)
                    try:
                        agent.session_summary_manager.create_session_summary(
                            session=agent_session, run_response=run_response
                        )
                    except Exception as e:
                        log_warning(f"Error in session summary creation: {str(e)}")

                run_response.status = RunStatus.completed

                # 13. Cleanup and store the run response and session
                cleanup_and_store(
                    agent, run_response=run_response, session=agent_session, run_context=run_context, user_id=user_id
                )

                # Log Agent Telemetry
                log_agent_telemetry(agent, session_id=agent_session.session_id, run_id=run_response.run_id)

                log_debug(f"Agent Run End: {run_response.run_id}", center=True, symbol="*")

                return run_response
            except RunCancelledException as e:
                log_info(f"Run {run_response.run_id} was cancelled")
                run_response.content = str(e)
                run_response.status = RunStatus.cancelled

                # Cleanup and store the run response and session
                if agent_session is not None:
                    cleanup_and_store(
                        agent,
                        run_response=run_response,
                        session=agent_session,
                        run_context=run_context,
                        user_id=user_id,
                    )

                return run_response
            except (InputCheckError, OutputCheckError) as e:
                # Handle exceptions during streaming
                run_response.status = RunStatus.error
                # If the content is None, set it to the error message
                if run_response.content is None:
                    run_response.content = str(e)

                log_error(f"Validation failed: {str(e)} | Check trigger: {e.check_trigger}")

                if agent_session is not None:
                    cleanup_and_store(
                        agent,
                        run_response=run_response,
                        session=agent_session,
                        run_context=run_context,
                        user_id=user_id,
                    )

                return run_response
            except KeyboardInterrupt:
                run_response = cast(RunOutput, run_response)
                run_response.status = RunStatus.cancelled
                run_response.content = "Operation cancelled by user"
                return run_response

            except Exception as e:
                if attempt < num_attempts - 1:
                    # Calculate delay with exponential backoff if enabled
                    if agent.exponential_backoff:
                        delay = agent.delay_between_retries * (2**attempt)
                    else:
                        delay = agent.delay_between_retries

                    log_warning(f"Attempt {attempt + 1}/{num_attempts} failed: {str(e)}. Retrying in {delay}s...")
                    time.sleep(delay)
                    continue

                run_response.status = RunStatus.error

                # If the content is None, set it to the error message
                if run_response.content is None:
                    run_response.content = str(e)

                log_error(f"Error in Agent run: {str(e)}")

                # Cleanup and store the run response and session
                if agent_session is not None:
                    cleanup_and_store(
                        agent,
                        run_response=run_response,
                        session=agent_session,
                        run_context=run_context,
                        user_id=user_id,
                    )

                return run_response
    finally:
        # Cancel background futures on error (wait_for_open_threads handles waiting on success)
        for future in (memory_future, cultural_knowledge_future, learning_future):
            if future is not None and not future.done():
                future.cancel()
                try:
                    future.result(timeout=0)
                except Exception:
                    pass

        # Always disconnect connectable tools
        disconnect_connectable_tools(agent)
        # Always clean up the run tracking
        cleanup_run(run_response.run_id)  # type: ignore

    return run_response


def _run_stream(
    agent: Agent,
    run_response: RunOutput,
    run_context: RunContext,
    session_id: str,
    user_id: Optional[str] = None,
    add_history_to_context: Optional[bool] = None,
    add_dependencies_to_context: Optional[bool] = None,
    add_session_state_to_context: Optional[bool] = None,
    response_format: Optional[Union[Dict, Type[BaseModel]]] = None,
    stream_events: bool = False,
    yield_run_output: Optional[bool] = None,
    debug_mode: Optional[bool] = None,
    background_tasks: Optional[Any] = None,
    pre_session: Optional[AgentSession] = None,
    **kwargs: Any,
) -> Iterator[Union[RunOutputEvent, RunOutput]]:
    """Run the Agent and yield the RunOutput.

    Steps:
    1. Read or create session
    2. Update metadata and session state
    3. Resolve dependencies
    4. Execute pre-hooks
    5. Determine tools for model
    6. Prepare run messages
    7. Start memory creation in background thread
    8. Reason about the task if reasoning is enabled
    9. Process model response
    10. Parse response with parser model if provided
    11. Wait for background memory creation and cultural knowledge creation
    12. Create session summary
    13. Cleanup and store the run response and session
    """
    from agno.agent._hooks import execute_post_hooks, execute_pre_hooks
    from agno.agent._init import disconnect_connectable_tools
    from agno.agent._messages import get_run_messages
    from agno.agent._response import (
        generate_response_with_output_model_stream,
        handle_model_response_stream,
        handle_reasoning_stream,
        parse_response_with_parser_model_stream,
    )
    from agno.agent._storage import load_session_state, read_or_create_session, update_metadata
    from agno.agent._telemetry import log_agent_telemetry
    from agno.agent._tools import determine_tools_for_model

    register_run(run_context.run_id)
    log_debug(f"Agent Run Start: {run_response.run_id}", center=True)

    memory_future = None
    learning_future = None
    cultural_knowledge_future = None
    agent_session: Optional[AgentSession] = None

    try:
        # Set up retry logic
        num_attempts = agent.retries + 1
        for attempt in range(num_attempts):
            if attempt > 0:
                log_debug(f"Retrying Agent run {run_response.run_id}. Attempt {attempt + 1} of {num_attempts}...")
            try:
                # 1. Read or create session. Reuse pre-read session on first attempt.
                if attempt == 0 and pre_session is not None:
                    agent_session = pre_session
                else:
                    agent_session = read_or_create_session(agent, session_id=session_id, user_id=user_id)

                # 2. Update metadata and session state
                if not (attempt == 0 and pre_session is not None):
                    update_metadata(agent, session=agent_session)

                # Initialize session state. Get it from DB if relevant.
                run_context.session_state = load_session_state(
                    agent,
                    session=agent_session,
                    session_state=run_context.session_state if run_context.session_state is not None else {},
                )
                _initialize_session_state(
                    run_context.session_state,
                    user_id=user_id,
                    session_id=session_id,
                    run_id=run_context.run_id,
                )

                # 3. Resolve dependencies
                if run_context.dependencies is not None:
                    resolve_run_dependencies(agent, run_context=run_context)

                # 4. Execute pre-hooks
                run_input = cast(RunInput, run_response.input)
                agent.model = cast(Model, agent.model)
                if agent.pre_hooks is not None:
                    # Can modify the run input
                    pre_hook_iterator = execute_pre_hooks(
                        agent,
                        hooks=agent.pre_hooks,  # type: ignore
                        run_response=run_response,
                        run_input=run_input,
                        run_context=run_context,
                        session=agent_session,
                        user_id=user_id,
                        debug_mode=debug_mode,
                        stream_events=stream_events,
                        background_tasks=background_tasks,
                        **kwargs,
                    )
                    for event in pre_hook_iterator:
                        yield event

                # 5. Determine tools for model
                processed_tools = agent.get_tools(
                    run_response=run_response,
                    run_context=run_context,
                    session=agent_session,
                    user_id=user_id,
                )
                _tools = determine_tools_for_model(
                    agent,
                    model=agent.model,
                    processed_tools=processed_tools,
                    run_response=run_response,
                    session=agent_session,
                    run_context=run_context,
                )

                # 6. Prepare run messages
                run_messages: RunMessages = get_run_messages(
                    agent,
                    run_response=run_response,
                    input=run_input.input_content,
                    session=agent_session,
                    run_context=run_context,
                    user_id=user_id,
                    audio=run_input.audios,
                    images=run_input.images,
                    videos=run_input.videos,
                    files=run_input.files,
                    add_history_to_context=add_history_to_context,
                    add_dependencies_to_context=add_dependencies_to_context,
                    add_session_state_to_context=add_session_state_to_context,
                    tools=_tools,
                    **kwargs,
                )
                if len(run_messages.messages) == 0:
                    log_error("No messages to be sent to the model.")

                # 7. Start memory creation in background thread
                from agno.agent import _managers

                memory_future = _managers.start_memory_future(
                    agent,
                    run_messages=run_messages,
                    user_id=user_id,
                    existing_future=memory_future,
                    run_response=run_response,
                )

                # Start learning extraction as a background task (runs concurrently with the main execution)
                learning_future = _managers.start_learning_future(
                    agent,
                    run_messages=run_messages,
                    session=agent_session,
                    user_id=user_id,
                    existing_future=learning_future,
                    run_response=run_response,
                )

                # Start cultural knowledge creation in background thread
                cultural_knowledge_future = _managers.start_cultural_knowledge_future(
                    agent,
                    run_messages=run_messages,
                    existing_future=cultural_knowledge_future,
                    run_response=run_response,
                )

                # Start the Run by yielding a RunStarted event
                if stream_events:
                    yield handle_event(  # type: ignore
                        create_run_started_event(run_response),
                        run_response,
                        events_to_skip=agent.events_to_skip,  # type: ignore
                        store_events=agent.store_events,
                    )

                # 5. Reason about the task if reasoning is enabled
                yield from handle_reasoning_stream(
                    agent,
                    run_response=run_response,
                    run_messages=run_messages,
                    run_context=run_context,
                    stream_events=stream_events,
                )

                # Check for cancellation before model processing
                raise_if_cancelled(run_response.run_id)  # type: ignore

                # 6. Process model response
                if agent.output_model is None:
                    for event in handle_model_response_stream(
                        agent,
                        session=agent_session,
                        run_response=run_response,
                        run_messages=run_messages,
                        tools=_tools,
                        response_format=response_format,
                        stream_events=stream_events,
                        session_state=run_context.session_state,
                        run_context=run_context,
                    ):
                        raise_if_cancelled(run_response.run_id)  # type: ignore
                        yield event
                else:
                    from agno.run.agent import (
                        IntermediateRunContentEvent,
                        RunContentEvent,
                    )  # type: ignore

                    for event in handle_model_response_stream(
                        agent,
                        session=agent_session,
                        run_response=run_response,
                        run_messages=run_messages,
                        tools=_tools,
                        response_format=response_format,
                        stream_events=stream_events,
                        session_state=run_context.session_state,
                        run_context=run_context,
                    ):
                        raise_if_cancelled(run_response.run_id)  # type: ignore
                        if isinstance(event, RunContentEvent):
                            if stream_events:
                                yield IntermediateRunContentEvent(
                                    content=event.content,
                                    content_type=event.content_type,
                                )
                        else:
                            yield event

                    # If an output model is provided, generate output using the output model
                    for event in generate_response_with_output_model_stream(
                        agent,
                        session=agent_session,
                        run_response=run_response,
                        run_messages=run_messages,
                        stream_events=stream_events,
                    ):
                        raise_if_cancelled(run_response.run_id)  # type: ignore
                        yield event  # type: ignore

                # Check for cancellation after model processing
                raise_if_cancelled(run_response.run_id)  # type: ignore

                # 7. Parse response with parser model if provided
                yield from parse_response_with_parser_model_stream(
                    agent,  # type: ignore
                    session=agent_session,
                    run_response=run_response,
                    stream_events=stream_events,
                    run_context=run_context,
                )

                # We should break out of the run function
                if any(tool_call.is_paused for tool_call in run_response.tools or []):
                    yield from wait_for_thread_tasks_stream(
                        memory_future=memory_future,  # type: ignore
                        cultural_knowledge_future=cultural_knowledge_future,  # type: ignore
                        learning_future=learning_future,  # type: ignore
                        stream_events=stream_events,
                        run_response=run_response,
                        events_to_skip=agent.events_to_skip,
                        store_events=agent.store_events,
                        get_memories_callback=lambda: agent.get_user_memories(user_id=user_id),
                    )

                    # Handle the paused run
                    yield from handle_agent_run_paused_stream(
                        agent,
                        run_response=run_response,
                        session=agent_session,
                        run_context=run_context,
                        user_id=user_id,
                        yield_run_output=yield_run_output or False,
                    )
                    return

                # Yield RunContentCompletedEvent
                if stream_events:
                    yield handle_event(  # type: ignore
                        create_run_content_completed_event(from_run_response=run_response),
                        run_response,
                        events_to_skip=agent.events_to_skip,  # type: ignore
                        store_events=agent.store_events,
                    )

                # Execute post-hooks after output is generated but before response is returned
                if agent.post_hooks is not None:
                    yield from execute_post_hooks(
                        agent,
                        hooks=agent.post_hooks,  # type: ignore
                        run_output=run_response,
                        run_context=run_context,
                        session=agent_session,
                        user_id=user_id,
                        debug_mode=debug_mode,
                        stream_events=stream_events,
                        background_tasks=background_tasks,
                        **kwargs,
                    )

                # 8. Wait for background memory creation and cultural knowledge creation
                yield from wait_for_thread_tasks_stream(
                    memory_future=memory_future,  # type: ignore
                    cultural_knowledge_future=cultural_knowledge_future,  # type: ignore
                    learning_future=learning_future,  # type: ignore
                    stream_events=stream_events,
                    run_response=run_response,
                    events_to_skip=agent.events_to_skip,
                    store_events=agent.store_events,
                    get_memories_callback=lambda: agent.get_user_memories(user_id=user_id),
                )

                # 9. Create session summary
                if agent.session_summary_manager is not None and agent.enable_session_summaries:
                    # Upsert the RunOutput to Agent Session before creating the session summary
                    agent_session.upsert_run(run=run_response)

                    if stream_events:
                        yield handle_event(  # type: ignore
                            create_session_summary_started_event(from_run_response=run_response),
                            run_response,
                            events_to_skip=agent.events_to_skip,  # type: ignore
                            store_events=agent.store_events,
                        )
                    try:
                        agent.session_summary_manager.create_session_summary(
                            session=agent_session, run_response=run_response
                        )
                    except Exception as e:
                        log_warning(f"Error in session summary creation: {str(e)}")
                    if stream_events:
                        yield handle_event(  # type: ignore
                            create_session_summary_completed_event(
                                from_run_response=run_response, session_summary=agent_session.summary
                            ),
                            run_response,
                            events_to_skip=agent.events_to_skip,  # type: ignore
                            store_events=agent.store_events,
                        )

                # Update run_response.session_state before creating RunCompletedEvent
                # This ensures the event has the final state after all tool modifications
                if agent_session.session_data is not None and "session_state" in agent_session.session_data:
                    run_response.session_state = agent_session.session_data["session_state"]

                # Create the run completed event
                completed_event = handle_event(  # type: ignore
                    create_run_completed_event(from_run_response=run_response),
                    run_response,
                    events_to_skip=agent.events_to_skip,  # type: ignore
                    store_events=agent.store_events,
                )

                # Set the run status to completed
                run_response.status = RunStatus.completed

                # 10. Cleanup and store the run response and session
                cleanup_and_store(
                    agent, run_response=run_response, session=agent_session, run_context=run_context, user_id=user_id
                )

                if stream_events:
                    yield completed_event  # type: ignore

                if yield_run_output:
                    yield run_response

                # Log Agent Telemetry
                log_agent_telemetry(agent, session_id=agent_session.session_id, run_id=run_response.run_id)

                log_debug(f"Agent Run End: {run_response.run_id}", center=True, symbol="*")

                break
            except RunCancelledException as e:
                # Handle run cancellation during streaming
                log_info(f"Run {run_response.run_id} was cancelled during streaming")
                run_response.content = str(e)
                run_response.status = RunStatus.cancelled
                yield handle_event(
                    create_run_cancelled_event(from_run_response=run_response, reason=str(e)),
                    run_response,
                    events_to_skip=agent.events_to_skip,  # type: ignore
                    store_events=agent.store_events,
                )

                # Cleanup and store the run response and session
                if agent_session is not None:
                    cleanup_and_store(
                        agent,
                        run_response=run_response,
                        session=agent_session,
                        run_context=run_context,
                        user_id=user_id,
                    )
                break
            except (InputCheckError, OutputCheckError) as e:
                # Handle exceptions during streaming
                run_response.status = RunStatus.error
                # Add error event to list of events
                run_error = create_run_error_event(
                    run_response,
                    error=str(e),
                    error_id=e.error_id,
                    error_type=e.type,
                    additional_data=e.additional_data,
                )
                run_response.events = add_error_event(error=run_error, events=run_response.events)

                # If the content is None, set it to the error message
                if run_response.content is None:
                    run_response.content = str(e)

                log_error(f"Validation failed: {str(e)} | Check trigger: {e.check_trigger}")

                if agent_session is not None:
                    cleanup_and_store(
                        agent,
                        run_response=run_response,
                        session=agent_session,
                        run_context=run_context,
                        user_id=user_id,
                    )
                yield run_error
                break
            except KeyboardInterrupt:
                run_response = cast(RunOutput, run_response)
                yield handle_event(  # type: ignore
                    create_run_cancelled_event(from_run_response=run_response, reason="Operation cancelled by user"),
                    run_response,
                    events_to_skip=agent.events_to_skip,  # type: ignore
                    store_events=agent.store_events,
                )
                break
            except Exception as e:
                if attempt < num_attempts - 1:
                    # Calculate delay with exponential backoff if enabled
                    if agent.exponential_backoff:
                        delay = agent.delay_between_retries * (2**attempt)
                    else:
                        delay = agent.delay_between_retries

                    log_warning(f"Attempt {attempt + 1}/{num_attempts} failed: {str(e)}. Retrying in {delay}s...")
                    time.sleep(delay)
                    continue

                run_response.status = RunStatus.error
                # Add error event to list of events
                run_error = create_run_error_event(run_response, error=str(e))
                run_response.events = add_error_event(error=run_error, events=run_response.events)

                # If the content is None, set it to the error message
                if run_response.content is None:
                    run_response.content = str(e)

                log_error(f"Error in Agent run: {str(e)}")

                # Cleanup and store the run response and session
                if agent_session is not None:
                    cleanup_and_store(
                        agent,
                        run_response=run_response,
                        session=agent_session,
                        run_context=run_context,
                        user_id=user_id,
                    )

                yield run_error
    finally:
        # Cancel background futures on error (wait_for_thread_tasks_stream handles waiting on success)
        for future in (memory_future, cultural_knowledge_future, learning_future):
            if future is not None and not future.done():
                future.cancel()
                try:
                    future.result(timeout=0)
                except Exception:
                    pass

        # Always disconnect connectable tools
        disconnect_connectable_tools(agent)
        # Always clean up the run tracking
        cleanup_run(run_response.run_id)  # type: ignore


def run_dispatch(
    agent: Agent,
    input: Union[str, List, Dict, Message, BaseModel, List[Message]],
    *,
    stream: Optional[bool] = None,
    stream_events: Optional[bool] = None,
    user_id: Optional[str] = None,
    session_id: Optional[str] = None,
    session_state: Optional[Dict[str, Any]] = None,
    run_context: Optional[RunContext] = None,
    run_id: Optional[str] = None,
    audio: Optional[Sequence[Audio]] = None,
    images: Optional[Sequence[Image]] = None,
    videos: Optional[Sequence[Video]] = None,
    files: Optional[Sequence[File]] = None,
    knowledge_filters: Optional[Union[Dict[str, Any], List[FilterExpr]]] = None,
    add_history_to_context: Optional[bool] = None,
    add_dependencies_to_context: Optional[bool] = None,
    add_session_state_to_context: Optional[bool] = None,
    dependencies: Optional[Dict[str, Any]] = None,
    metadata: Optional[Dict[str, Any]] = None,
    output_schema: Optional[Union[Type[BaseModel], Dict[str, Any]]] = None,
    yield_run_output: Optional[bool] = None,
    debug_mode: Optional[bool] = None,
    **kwargs: Any,
) -> Union[RunOutput, Iterator[Union[RunOutputEvent, RunOutput]]]:
    """Run the Agent and return the response."""
    from agno.agent._init import has_async_db
    from agno.agent._response import get_response_format

    if has_async_db(agent):
        raise RuntimeError("`run` method is not supported with an async database. Please use `arun` method instead.")

    # Set the id for the run and register it immediately for cancellation tracking
    run_id = run_id or str(uuid4())

    if (add_history_to_context or agent.add_history_to_context) and not agent.db and not agent.team_id:
        log_warning(
            "add_history_to_context is True, but no database has been assigned to the agent. History will not be added to the context."
        )

    background_tasks = kwargs.pop("background_tasks", None)
    if background_tasks is not None:
        from fastapi import BackgroundTasks

        background_tasks: BackgroundTasks = background_tasks  # type: ignore

    # Validate input against input_schema if provided
    validated_input = validate_input(input, agent.input_schema)

    # Normalise hook & guardails
    if not agent._hooks_normalised:
        if agent.pre_hooks:
            agent.pre_hooks = normalize_pre_hooks(agent.pre_hooks)  # type: ignore
        if agent.post_hooks:
            agent.post_hooks = normalize_post_hooks(agent.post_hooks)  # type: ignore
        agent._hooks_normalised = True

    # Initialize session
    session_id, user_id = initialize_session(agent, session_id=session_id, user_id=user_id)

    # Initialize the Agent
    agent.initialize_agent(debug_mode=debug_mode)

    image_artifacts, video_artifacts, audio_artifacts, file_artifacts = validate_media_object_id(
        images=images, videos=videos, audios=audio, files=files
    )

    # Create RunInput to capture the original user input
    run_input = RunInput(
        input_content=validated_input,
        images=image_artifacts,
        videos=video_artifacts,
        audios=audio_artifacts,
        files=file_artifacts,
    )

    # Read existing session and update metadata BEFORE resolving run options,
    # so that session-stored metadata is visible to resolve_run_options.
    from agno.agent._storage import read_or_create_session, update_metadata

    agent_session = read_or_create_session(agent, session_id=session_id, user_id=user_id)
    update_metadata(agent, session=agent_session)

    # Resolve all run options centrally
    opts = resolve_run_options(
        agent,
        stream=stream,
        stream_events=stream_events,
        yield_run_output=yield_run_output,
        add_history_to_context=add_history_to_context,
        add_dependencies_to_context=add_dependencies_to_context,
        add_session_state_to_context=add_session_state_to_context,
        dependencies=dependencies,
        knowledge_filters=knowledge_filters,
        metadata=metadata,
        output_schema=output_schema,
    )

    agent.model = cast(Model, agent.model)

    # Initialize run context
    run_context = run_context or RunContext(
        run_id=run_id,
        session_id=session_id,
        user_id=user_id,
        session_state=session_state,
        dependencies=opts.dependencies,
        knowledge_filters=opts.knowledge_filters,
        metadata=opts.metadata,
        output_schema=opts.output_schema,
    )
    # Apply options with precedence: explicit args > existing run_context > resolved defaults.
    opts.apply_to_context(
        run_context,
        dependencies_provided=dependencies is not None,
        knowledge_filters_provided=knowledge_filters is not None,
        metadata_provided=metadata is not None,
    )

    # Prepare arguments for the model (must be after run_context is fully initialized)
    response_format = get_response_format(agent, run_context=run_context) if agent.parser_model is None else None

    # Create a new run_response for this attempt
    run_response = RunOutput(
        run_id=run_id,
        session_id=session_id,
        agent_id=agent.id,
        user_id=user_id,
        agent_name=agent.name,
        metadata=run_context.metadata,
        session_state=run_context.session_state,
        input=run_input,
    )

    run_response.model = agent.model.id if agent.model is not None else None
    run_response.model_provider = agent.model.provider if agent.model is not None else None

    # Start the run metrics timer, to calculate the run duration
    run_response.metrics = RunMetrics()
    run_response.metrics.start_timer()

    if opts.stream:
        response_iterator = _run_stream(
            agent,
            run_response=run_response,
            run_context=run_context,
            session_id=session_id,
            user_id=user_id,
            add_history_to_context=opts.add_history_to_context,
            add_dependencies_to_context=opts.add_dependencies_to_context,
            add_session_state_to_context=opts.add_session_state_to_context,
            response_format=response_format,
            stream_events=opts.stream_events,
            yield_run_output=opts.yield_run_output,
            debug_mode=debug_mode,
            background_tasks=background_tasks,
            pre_session=agent_session,
            **kwargs,
        )
        return response_iterator
    else:
        response = _run(
            agent,
            run_response=run_response,
            run_context=run_context,
            session_id=session_id,
            user_id=user_id,
            add_history_to_context=opts.add_history_to_context,
            add_dependencies_to_context=opts.add_dependencies_to_context,
            add_session_state_to_context=opts.add_session_state_to_context,
            response_format=response_format,
            debug_mode=debug_mode,
            background_tasks=background_tasks,
            pre_session=agent_session,
            **kwargs,
        )
        return response


async def _arun(
    agent: Agent,
    run_response: RunOutput,
    run_context: RunContext,
    session_id: str,
    user_id: Optional[str] = None,
    add_history_to_context: Optional[bool] = None,
    add_dependencies_to_context: Optional[bool] = None,
    add_session_state_to_context: Optional[bool] = None,
    response_format: Optional[Union[Dict, Type[BaseModel]]] = None,
    debug_mode: Optional[bool] = None,
    background_tasks: Optional[Any] = None,
    pre_session: Optional[AgentSession] = None,
    **kwargs: Any,
) -> RunOutput:
    """Run the Agent and return the RunOutput.

    Steps:
    1. Read or create session
    2. Update metadata and session state
    3. Resolve dependencies
    4. Execute pre-hooks
    5. Determine tools for model
    6. Prepare run messages
    7. Start memory creation in background task
    8. Reason about the task if reasoning is enabled
    9. Generate a response from the Model (includes running function calls)
    10. Update the RunOutput with the model response
    11. Convert response to structured format
    12. Store media if enabled
    13. Execute post-hooks
    14. Wait for background memory creation
    15. Create session summary
    16. Cleanup and store (scrub, stop timer, save to file, add to session, calculate metrics, save session)
    """
    from agno.agent._hooks import aexecute_post_hooks, aexecute_pre_hooks
    from agno.agent._init import disconnect_connectable_tools, disconnect_mcp_tools
    from agno.agent._messages import aget_run_messages
    from agno.agent._response import (
        agenerate_response_with_output_model,
        ahandle_reasoning,
        aparse_response_with_parser_model,
        convert_response_to_structured_format,
        update_run_response,
    )
    from agno.agent._storage import aread_or_create_session, load_session_state, update_metadata
    from agno.agent._telemetry import alog_agent_telemetry
    from agno.agent._tools import determine_tools_for_model

    await aregister_run(run_context.run_id)
    log_debug(f"Agent Run Start: {run_response.run_id}", center=True)

    memory_task = None
    learning_task = None
    cultural_knowledge_task = None
    agent_session: Optional[AgentSession] = None

    # Set up retry logic
    num_attempts = agent.retries + 1

    try:
        for attempt in range(num_attempts):
            if attempt > 0:
                log_debug(f"Retrying Agent run {run_response.run_id}. Attempt {attempt + 1} of {num_attempts}...")

            try:
                # 1. Read or create session. Reuse pre-read session on first attempt.
                if attempt == 0 and pre_session is not None:
                    agent_session = pre_session
                else:
                    agent_session = await aread_or_create_session(agent, session_id=session_id, user_id=user_id)

                # 2. Update metadata and session state
                if not (attempt == 0 and pre_session is not None):
                    update_metadata(agent, session=agent_session)

                # Initialize session state. Get it from DB if relevant.
                run_context.session_state = load_session_state(
                    agent,
                    session=agent_session,
                    session_state=run_context.session_state if run_context.session_state is not None else {},
                )
                _initialize_session_state(
                    run_context.session_state,
                    user_id=user_id,
                    session_id=session_id,
                    run_id=run_context.run_id,
                )

                # 3. Resolve dependencies
                if run_context.dependencies is not None:
                    await aresolve_run_dependencies(agent, run_context=run_context)

                # 4. Execute pre-hooks
                run_input = cast(RunInput, run_response.input)
                agent.model = cast(Model, agent.model)
                if agent.pre_hooks is not None:
                    # Can modify the run input
                    pre_hook_iterator = aexecute_pre_hooks(
                        agent,
                        hooks=agent.pre_hooks,  # type: ignore
                        run_response=run_response,
                        run_context=run_context,
                        run_input=run_input,
                        session=agent_session,
                        user_id=user_id,
                        debug_mode=debug_mode,
                        background_tasks=background_tasks,
                        **kwargs,
                    )
                    # Consume the async iterator without yielding
                    async for _ in pre_hook_iterator:
                        pass

                # 5. Determine tools for model
                agent.model = cast(Model, agent.model)
                processed_tools = await agent.aget_tools(
                    run_response=run_response,
                    run_context=run_context,
                    session=agent_session,
                    user_id=user_id,
                )

                _tools = determine_tools_for_model(
                    agent,
                    model=agent.model,
                    processed_tools=processed_tools,
                    run_response=run_response,
                    run_context=run_context,
                    session=agent_session,
                    async_mode=True,
                )

                # 6. Prepare run messages
                run_messages: RunMessages = await aget_run_messages(
                    agent,
                    run_response=run_response,
                    run_context=run_context,
                    input=run_input.input_content,
                    session=agent_session,
                    user_id=user_id,
                    audio=run_input.audios,
                    images=run_input.images,
                    videos=run_input.videos,
                    files=run_input.files,
                    add_history_to_context=add_history_to_context,
                    add_dependencies_to_context=add_dependencies_to_context,
                    add_session_state_to_context=add_session_state_to_context,
                    tools=_tools,
                    **kwargs,
                )
                if len(run_messages.messages) == 0:
                    log_error("No messages to be sent to the model.")

                # 7. Start memory creation as a background task (runs concurrently with the main execution)
                from agno.agent import _managers

                memory_task = await _managers.astart_memory_task(
                    agent,
                    run_messages=run_messages,
                    user_id=user_id,
                    existing_task=memory_task,
                    run_response=run_response,
                )

                # Start learning extraction as a background task
                learning_task = await _managers.astart_learning_task(
                    agent,
                    run_messages=run_messages,
                    session=agent_session,
                    user_id=user_id,
                    existing_task=learning_task,
                    run_response=run_response,
                )

                # Start cultural knowledge creation as a background task (runs concurrently with the main execution)
                cultural_knowledge_task = await _managers.astart_cultural_knowledge_task(
                    agent,
                    run_messages=run_messages,
                    existing_task=cultural_knowledge_task,
                    run_response=run_response,
                )

                # Check for cancellation before model call
                await araise_if_cancelled(run_response.run_id)  # type: ignore

                # 8. Reason about the task if reasoning is enabled
                await ahandle_reasoning(
                    agent, run_response=run_response, run_messages=run_messages, run_context=run_context
                )

                # Check for cancellation before model call
                await araise_if_cancelled(run_response.run_id)  # type: ignore

                # 9. Generate a response from the Model (includes running function calls)
                model_response: ModelResponse = await agent.model.aresponse(
                    messages=run_messages.messages,
                    tools=_tools,
                    tool_choice=agent.tool_choice,
                    tool_call_limit=agent.tool_call_limit,
                    response_format=response_format,
                    send_media_to_model=agent.send_media_to_model,
                    run_response=run_response,
                    compression_manager=agent.compression_manager if agent.compress_tool_results else None,
                )

                # Check for cancellation after model call
                await araise_if_cancelled(run_response.run_id)  # type: ignore

                # If an output model is provided, generate output using the output model
                await agenerate_response_with_output_model(
                    agent, model_response=model_response, run_messages=run_messages, run_response=run_response
                )

                # If a parser model is provided, structure the response separately
                await aparse_response_with_parser_model(
                    agent,
                    model_response=model_response,
                    run_messages=run_messages,
                    run_context=run_context,
                    run_response=run_response,
                )

                # 10. Update the RunOutput with the model response
                update_run_response(
                    agent,
                    model_response=model_response,
                    run_response=run_response,
                    run_messages=run_messages,
                    run_context=run_context,
                )

                # We should break out of the run function
                if any(tool_call.is_paused for tool_call in run_response.tools or []):
                    await await_for_open_threads(
                        memory_task=memory_task,
                        cultural_knowledge_task=cultural_knowledge_task,
                        learning_task=learning_task,
                    )
                    return await ahandle_agent_run_paused(
                        agent,
                        run_response=run_response,
                        session=agent_session,
                        run_context=run_context,
                        user_id=user_id,
                    )

                # 11. Convert the response to the structured format if needed
                convert_response_to_structured_format(agent, run_response, run_context=run_context)

                # 12. Store media if enabled
                if agent.store_media:
                    store_media_util(run_response, model_response)

                # 13. Execute post-hooks (after output is generated but before response is returned)
                if agent.post_hooks is not None:
                    async for _ in aexecute_post_hooks(
                        agent,
                        hooks=agent.post_hooks,  # type: ignore
                        run_output=run_response,
                        run_context=run_context,
                        session=agent_session,
                        user_id=user_id,
                        debug_mode=debug_mode,
                        background_tasks=background_tasks,
                        **kwargs,
                    ):
                        pass

                # Check for cancellation
                await araise_if_cancelled(run_response.run_id)  # type: ignore

                # 14. Wait for background memory creation
                await await_for_open_threads(
                    memory_task=memory_task,
                    cultural_knowledge_task=cultural_knowledge_task,
                    learning_task=learning_task,
                )

                # 15. Create session summary
                if agent.session_summary_manager is not None and agent.enable_session_summaries:
                    # Upsert the RunOutput to Agent Session before creating the session summary
                    agent_session.upsert_run(run=run_response)
                    try:
                        await agent.session_summary_manager.acreate_session_summary(
                            session=agent_session, run_response=run_response
                        )
                    except Exception as e:
                        log_warning(f"Error in session summary creation: {str(e)}")

                run_response.status = RunStatus.completed

                # 16. Cleanup and store the run response and session
                await acleanup_and_store(
                    agent,
                    run_response=run_response,
                    session=agent_session,
                    run_context=run_context,
                    user_id=user_id,
                )

                # Log Agent Telemetry
                await alog_agent_telemetry(agent, session_id=agent_session.session_id, run_id=run_response.run_id)

                log_debug(f"Agent Run End: {run_response.run_id}", center=True, symbol="*")

                return run_response

            except RunCancelledException as e:
                # Handle run cancellation
                log_info(f"Run {run_response.run_id} was cancelled")
                run_response.content = str(e)
                run_response.status = RunStatus.cancelled

                # Cleanup and store the run response and session
                if agent_session is not None:
                    await acleanup_and_store(
                        agent,
                        run_response=run_response,
                        session=agent_session,
                        run_context=run_context,
                        user_id=user_id,
                    )

                return run_response
            except (InputCheckError, OutputCheckError) as e:
                # Handle exceptions during streaming
                run_response.status = RunStatus.error
                # If the content is None, set it to the error message
                if run_response.content is None:
                    run_response.content = str(e)

                log_error(f"Validation failed: {str(e)} | Check trigger: {e.check_trigger}")

                if agent_session is not None:
                    await acleanup_and_store(
                        agent,
                        run_response=run_response,
                        session=agent_session,
                        run_context=run_context,
                        user_id=user_id,
                    )

                return run_response

            except KeyboardInterrupt:
                run_response = cast(RunOutput, run_response)
                run_response.status = RunStatus.cancelled
                run_response.content = "Operation cancelled by user"
                return run_response
            except Exception as e:
                # Check if this is the last attempt
                if attempt < num_attempts - 1:
                    # Calculate delay with exponential backoff if enabled
                    if agent.exponential_backoff:
                        delay = agent.delay_between_retries * (2**attempt)
                    else:
                        delay = agent.delay_between_retries

                    log_warning(f"Attempt {attempt + 1}/{num_attempts} failed: {str(e)}. Retrying in {delay}s...")
                    await asyncio.sleep(delay)
                    continue

                run_response.status = RunStatus.error

                # If the content is None, set it to the error message
                if run_response.content is None:
                    run_response.content = str(e)

                log_error(f"Error in Agent run: {str(e)}")

                # Cleanup and store the run response and session
                if agent_session is not None:
                    await acleanup_and_store(
                        agent,
                        run_response=run_response,
                        session=agent_session,
                        run_context=run_context,
                        user_id=user_id,
                    )

                return run_response
    finally:
        # Always disconnect connectable tools
        disconnect_connectable_tools(agent)
        # Always disconnect MCP tools
        await disconnect_mcp_tools(agent)

        # Cancel background tasks on error (await_for_open_threads handles waiting on success)
        if memory_task is not None and not memory_task.done():
            memory_task.cancel()
            try:
                await memory_task
            except asyncio.CancelledError:
                pass
        if cultural_knowledge_task is not None and not cultural_knowledge_task.done():
            cultural_knowledge_task.cancel()
            try:
                await cultural_knowledge_task
            except asyncio.CancelledError:
                pass
        if learning_task is not None and not learning_task.done():
            learning_task.cancel()
            try:
                await learning_task
            except asyncio.CancelledError:
                pass

        # Always clean up the run tracking
        await acleanup_run(run_response.run_id)  # type: ignore

    return run_response


async def _arun_background(
    agent: Agent,
    run_response: RunOutput,
    run_context: RunContext,
    session_id: str,
    user_id: Optional[str] = None,
    add_history_to_context: Optional[bool] = None,
    add_dependencies_to_context: Optional[bool] = None,
    add_session_state_to_context: Optional[bool] = None,
    response_format: Optional[Union[Dict, Type[BaseModel]]] = None,
    debug_mode: Optional[bool] = None,
    background_tasks: Optional[Any] = None,
    **kwargs: Any,
) -> RunOutput:
    """Start an agent run in the background and return immediately with PENDING status.

    The run is persisted with PENDING status, then an asyncio task is spawned
    to execute the actual run. The task transitions through RUNNING -> COMPLETED/ERROR.

    Callers can poll for results via agent.aget_run_output(run_id, session_id).
    """
    from agno.agent._session import asave_session
    from agno.agent._storage import aread_or_create_session, update_metadata

    # 1. Register the run for cancellation tracking (before spawning the task)
    await aregister_run(run_context.run_id)

    # 2. Set status to PENDING
    run_response.status = RunStatus.pending

    # 3. Persist the PENDING run so polling can find it immediately
    agent_session = await aread_or_create_session(agent, session_id=session_id, user_id=user_id)
    update_metadata(agent, session=agent_session)
    agent_session.upsert_run(run=run_response)
    await asave_session(agent, session=agent_session)

    log_info(f"Background run {run_response.run_id} created with PENDING status")

    # 4. Spawn the background task
    async def _background_task() -> None:
        try:
            # Transition to RUNNING
            run_response.status = RunStatus.running
            agent_session.upsert_run(run=run_response)
            await asave_session(agent, session=agent_session)

            # Execute the actual run — _arun handles everything including
            # session persistence and cleanup
            await _arun(
                agent,
                run_response=run_response,
                run_context=run_context,
                user_id=user_id,
                response_format=response_format,
                session_id=session_id,
                add_history_to_context=add_history_to_context,
                add_dependencies_to_context=add_dependencies_to_context,
                add_session_state_to_context=add_session_state_to_context,
                debug_mode=debug_mode,
                background_tasks=background_tasks,
                **kwargs,
            )
        except Exception:
            log_error(f"Background run {run_response.run_id} failed", exc_info=True)
            # Persist ERROR status
            try:
                run_response.status = RunStatus.error
                agent_session.upsert_run(run=run_response)
                await asave_session(agent, session=agent_session)
            except Exception:
                log_error(f"Failed to persist error state for background run {run_response.run_id}", exc_info=True)
            # Note: acleanup_run is already called by _arun's finally block

    task = asyncio.create_task(_background_task())
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)

    # 5. Return immediately with the PENDING response
    return run_response


async def _arun_stream(
    agent: Agent,
    run_response: RunOutput,
    run_context: RunContext,
    session_id: str,
    user_id: Optional[str] = None,
    add_history_to_context: Optional[bool] = None,
    add_dependencies_to_context: Optional[bool] = None,
    add_session_state_to_context: Optional[bool] = None,
    response_format: Optional[Union[Dict, Type[BaseModel]]] = None,
    stream_events: bool = False,
    yield_run_output: Optional[bool] = None,
    debug_mode: Optional[bool] = None,
    background_tasks: Optional[Any] = None,
    pre_session: Optional[AgentSession] = None,
    **kwargs: Any,
) -> AsyncIterator[Union[RunOutputEvent, RunOutput]]:
    """Run the Agent and yield the RunOutput.

    Steps:
    1. Read or create session
    2. Update metadata and session state
    3. Resolve dependencies
    4. Execute pre-hooks
    5. Determine tools for model
    6. Prepare run messages
    7. Start memory creation in background task
    8. Reason about the task if reasoning is enabled
    9. Generate a response from the Model (includes running function calls)
    10. Parse response with parser model if provided
    11. Wait for background memory creation
    12. Create session summary
    13. Cleanup and store (scrub, stop timer, save to file, add to session, calculate metrics, save session)
    """
    from agno.agent._hooks import aexecute_post_hooks, aexecute_pre_hooks
    from agno.agent._init import disconnect_connectable_tools, disconnect_mcp_tools
    from agno.agent._messages import aget_run_messages
    from agno.agent._response import (
        agenerate_response_with_output_model_stream,
        ahandle_model_response_stream,
        ahandle_reasoning_stream,
        aparse_response_with_parser_model_stream,
    )
    from agno.agent._storage import aread_or_create_session, load_session_state, update_metadata
    from agno.agent._telemetry import alog_agent_telemetry
    from agno.agent._tools import determine_tools_for_model

    await aregister_run(run_context.run_id)
    log_debug(f"Agent Run Start: {run_response.run_id}", center=True)

    memory_task = None
    cultural_knowledge_task = None
    learning_task = None
    agent_session: Optional[AgentSession] = None

    # Set up retry logic
    num_attempts = agent.retries + 1
    try:
        for attempt in range(num_attempts):
            if attempt > 0:
                log_debug(f"Retrying Agent run {run_response.run_id}. Attempt {attempt + 1} of {num_attempts}...")

            try:
                # 1. Read or create session. Reuse pre-read session on first attempt.
                if attempt == 0 and pre_session is not None:
                    agent_session = pre_session
                else:
                    agent_session = await aread_or_create_session(agent, session_id=session_id, user_id=user_id)

                # Start the Run by yielding a RunStarted event
                if stream_events:
                    yield handle_event(  # type: ignore
                        create_run_started_event(run_response),
                        run_response,
                        events_to_skip=agent.events_to_skip,  # type: ignore
                        store_events=agent.store_events,
                    )

                # 2. Update metadata and session state
                if not (attempt == 0 and pre_session is not None):
                    update_metadata(agent, session=agent_session)

                # Initialize session state. Get it from DB if relevant.
                run_context.session_state = load_session_state(
                    agent,
                    session=agent_session,
                    session_state=run_context.session_state if run_context.session_state is not None else {},
                )
                _initialize_session_state(
                    run_context.session_state,
                    user_id=user_id,
                    session_id=session_id,
                    run_id=run_context.run_id,
                )

                # 3. Resolve dependencies
                if run_context.dependencies is not None:
                    await aresolve_run_dependencies(agent, run_context=run_context)

                # 4. Execute pre-hooks
                run_input = cast(RunInput, run_response.input)
                agent.model = cast(Model, agent.model)
                if agent.pre_hooks is not None:
                    pre_hook_iterator = aexecute_pre_hooks(
                        agent,
                        hooks=agent.pre_hooks,  # type: ignore
                        run_response=run_response,
                        run_context=run_context,
                        run_input=run_input,
                        session=agent_session,
                        user_id=user_id,
                        debug_mode=debug_mode,
                        stream_events=stream_events,
                        background_tasks=background_tasks,
                        **kwargs,
                    )
                    async for event in pre_hook_iterator:
                        await araise_if_cancelled(run_response.run_id)  # type: ignore
                        yield event

                # 5. Determine tools for model
                agent.model = cast(Model, agent.model)
                processed_tools = await agent.aget_tools(
                    run_response=run_response,
                    run_context=run_context,
                    session=agent_session,
                    user_id=user_id,
                )

                _tools = determine_tools_for_model(
                    agent,
                    model=agent.model,
                    processed_tools=processed_tools,
                    run_response=run_response,
                    run_context=run_context,
                    session=agent_session,
                    async_mode=True,
                )

                # 6. Prepare run messages
                run_messages: RunMessages = await aget_run_messages(
                    agent,
                    run_response=run_response,
                    run_context=run_context,
                    input=run_input.input_content,
                    session=agent_session,
                    user_id=user_id,
                    audio=run_input.audios,
                    images=run_input.images,
                    videos=run_input.videos,
                    files=run_input.files,
                    add_history_to_context=add_history_to_context,
                    add_dependencies_to_context=add_dependencies_to_context,
                    add_session_state_to_context=add_session_state_to_context,
                    tools=_tools,
                    **kwargs,
                )
                if len(run_messages.messages) == 0:
                    log_error("No messages to be sent to the model.")

                # 7. Start memory creation as a background task (runs concurrently with the main execution)
                from agno.agent import _managers

                memory_task = await _managers.astart_memory_task(
                    agent,
                    run_messages=run_messages,
                    user_id=user_id,
                    existing_task=memory_task,
                    run_response=run_response,
                )

                # Start learning extraction as a background task
                learning_task = await _managers.astart_learning_task(
                    agent,
                    run_messages=run_messages,
                    session=agent_session,
                    user_id=user_id,
                    existing_task=learning_task,
                    run_response=run_response,
                )

                # Start cultural knowledge creation as a background task (runs concurrently with the main execution)
                cultural_knowledge_task = await _managers.astart_cultural_knowledge_task(
                    agent,
                    run_messages=run_messages,
                    existing_task=cultural_knowledge_task,
                    run_response=run_response,
                )

                # 8. Reason about the task if reasoning is enabled
                async for item in ahandle_reasoning_stream(
                    agent,
                    run_response=run_response,
                    run_messages=run_messages,
                    run_context=run_context,
                    stream_events=stream_events,
                ):
                    await araise_if_cancelled(run_response.run_id)  # type: ignore
                    yield item

                await araise_if_cancelled(run_response.run_id)  # type: ignore

                # 9. Generate a response from the Model
                if agent.output_model is None:
                    async for event in ahandle_model_response_stream(
                        agent,
                        session=agent_session,
                        run_response=run_response,
                        run_messages=run_messages,
                        tools=_tools,
                        response_format=response_format,
                        stream_events=stream_events,
                        session_state=run_context.session_state,
                        run_context=run_context,
                    ):
                        await araise_if_cancelled(run_response.run_id)  # type: ignore
                        yield event
                else:
                    from agno.run.agent import (
                        IntermediateRunContentEvent,
                        RunContentEvent,
                    )  # type: ignore

                    async for event in ahandle_model_response_stream(
                        agent,
                        session=agent_session,
                        run_response=run_response,
                        run_messages=run_messages,
                        tools=_tools,
                        response_format=response_format,
                        stream_events=stream_events,
                        session_state=run_context.session_state,
                        run_context=run_context,
                    ):
                        await araise_if_cancelled(run_response.run_id)  # type: ignore
                        if isinstance(event, RunContentEvent):
                            if stream_events:
                                yield IntermediateRunContentEvent(
                                    content=event.content,
                                    content_type=event.content_type,
                                )
                        else:
                            yield event

                    # If an output model is provided, generate output using the output model
                    async for event in agenerate_response_with_output_model_stream(
                        agent,
                        session=agent_session,
                        run_response=run_response,
                        run_messages=run_messages,
                        stream_events=stream_events,
                    ):
                        await araise_if_cancelled(run_response.run_id)  # type: ignore
                        yield event  # type: ignore

                # Check for cancellation after model processing
                await araise_if_cancelled(run_response.run_id)  # type: ignore

                # 10. Parse response with parser model if provided
                async for event in aparse_response_with_parser_model_stream(
                    agent,
                    session=agent_session,
                    run_response=run_response,
                    stream_events=stream_events,
                    run_context=run_context,
                ):
                    yield event  # type: ignore

                if stream_events:
                    yield handle_event(  # type: ignore
                        create_run_content_completed_event(from_run_response=run_response),
                        run_response,
                        events_to_skip=agent.events_to_skip,  # type: ignore
                        store_events=agent.store_events,
                    )

                # Break out of the run function if a tool call is paused
                if any(tool_call.is_paused for tool_call in run_response.tools or []):
                    async for item in await_for_thread_tasks_stream(
                        memory_task=memory_task,
                        cultural_knowledge_task=cultural_knowledge_task,
                        learning_task=learning_task,
                        stream_events=stream_events,
                        run_response=run_response,
                        events_to_skip=agent.events_to_skip,
                        store_events=agent.store_events,
                        get_memories_callback=lambda: agent.aget_user_memories(user_id=user_id),
                    ):
                        yield item

                    async for item in ahandle_agent_run_paused_stream(  # type: ignore[assignment]
                        agent,
                        run_response=run_response,
                        session=agent_session,
                        run_context=run_context,
                        user_id=user_id,
                        yield_run_output=yield_run_output or False,
                    ):
                        yield item
                    return

                # Execute post-hooks (after output is generated but before response is returned)
                if agent.post_hooks is not None:
                    async for event in aexecute_post_hooks(
                        agent,
                        hooks=agent.post_hooks,  # type: ignore
                        run_output=run_response,
                        run_context=run_context,
                        session=agent_session,
                        user_id=user_id,
                        debug_mode=debug_mode,
                        stream_events=stream_events,
                        background_tasks=background_tasks,
                        **kwargs,
                    ):
                        yield event

                # 11. Wait for background memory creation
                async for item in await_for_thread_tasks_stream(
                    memory_task=memory_task,
                    cultural_knowledge_task=cultural_knowledge_task,
                    learning_task=learning_task,
                    stream_events=stream_events,
                    run_response=run_response,
                    events_to_skip=agent.events_to_skip,
                    store_events=agent.store_events,
                    get_memories_callback=lambda: agent.aget_user_memories(user_id=user_id),
                ):
                    yield item

                # 12. Create session summary
                if agent.session_summary_manager is not None and agent.enable_session_summaries:
                    # Upsert the RunOutput to Agent Session before creating the session summary
                    agent_session.upsert_run(run=run_response)

                    if stream_events:
                        yield handle_event(  # type: ignore
                            create_session_summary_started_event(from_run_response=run_response),
                            run_response,
                            events_to_skip=agent.events_to_skip,  # type: ignore
                            store_events=agent.store_events,
                        )
                    try:
                        await agent.session_summary_manager.acreate_session_summary(
                            session=agent_session, run_response=run_response
                        )
                    except Exception as e:
                        log_warning(f"Error in session summary creation: {str(e)}")
                    if stream_events:
                        yield handle_event(  # type: ignore
                            create_session_summary_completed_event(
                                from_run_response=run_response, session_summary=agent_session.summary
                            ),
                            run_response,
                            events_to_skip=agent.events_to_skip,  # type: ignore
                            store_events=agent.store_events,
                        )

                # Update run_response.session_state before creating RunCompletedEvent
                # This ensures the event has the final state after all tool modifications
                if agent_session.session_data is not None and "session_state" in agent_session.session_data:
                    run_response.session_state = agent_session.session_data["session_state"]

                # Create the run completed event
                completed_event = handle_event(
                    create_run_completed_event(from_run_response=run_response),
                    run_response,
                    events_to_skip=agent.events_to_skip,  # type: ignore
                    store_events=agent.store_events,
                )

                # Set the run status to completed
                run_response.status = RunStatus.completed

                # 13. Cleanup and store the run response and session
                await acleanup_and_store(
                    agent,
                    run_response=run_response,
                    session=agent_session,
                    run_context=run_context,
                    user_id=user_id,
                )

                if stream_events:
                    yield completed_event  # type: ignore

                if yield_run_output:
                    yield run_response

                # Log Agent Telemetry
                await alog_agent_telemetry(agent, session_id=agent_session.session_id, run_id=run_response.run_id)

                log_debug(f"Agent Run End: {run_response.run_id}", center=True, symbol="*")

                # Break out of the run function
                break

            except RunCancelledException as e:
                # Handle run cancellation during async streaming
                log_info(f"Run {run_response.run_id} was cancelled during async streaming")
                run_response.status = RunStatus.cancelled
                # Don't overwrite content - preserve any partial content that was streamed
                # Only set content if it's empty
                if not run_response.content:
                    run_response.content = str(e)

                # Yield the cancellation event
                yield handle_event(  # type: ignore
                    create_run_cancelled_event(from_run_response=run_response, reason=str(e)),
                    run_response,
                    events_to_skip=agent.events_to_skip,  # type: ignore
                    store_events=agent.store_events,
                )

                # Cleanup and store the run response and session
                if agent_session is not None:
                    await acleanup_and_store(
                        agent,
                        run_response=run_response,
                        session=agent_session,
                        run_context=run_context,
                        user_id=user_id,
                    )
                break

            except (InputCheckError, OutputCheckError) as e:
                # Handle exceptions during async streaming
                run_response.status = RunStatus.error
                # Add error event to list of events
                run_error = create_run_error_event(
                    run_response,
                    error=str(e),
                    error_id=e.error_id,
                    error_type=e.type,
                    additional_data=e.additional_data,
                )
                run_response.events = add_error_event(error=run_error, events=run_response.events)

                # If the content is None, set it to the error message
                if run_response.content is None:
                    run_response.content = str(e)

                log_error(f"Validation failed: {str(e)} | Check trigger: {e.check_trigger}")

                # Cleanup and store the run response and session
                if agent_session is not None:
                    await acleanup_and_store(
                        agent,
                        run_response=run_response,
                        session=agent_session,
                        run_context=run_context,
                        user_id=user_id,
                    )

                # Yield the error event
                yield run_error
                break

            except KeyboardInterrupt:
                run_response = cast(RunOutput, run_response)
                yield handle_event(  # type: ignore
                    create_run_cancelled_event(from_run_response=run_response, reason="Operation cancelled by user"),
                    run_response,
                    events_to_skip=agent.events_to_skip,  # type: ignore
                    store_events=agent.store_events,
                )
                break
            except Exception as e:
                # Check if this is the last attempt
                if attempt < num_attempts - 1:
                    # Calculate delay with exponential backoff if enabled
                    if agent.exponential_backoff:
                        delay = agent.delay_between_retries * (2**attempt)
                    else:
                        delay = agent.delay_between_retries

                    log_warning(f"Attempt {attempt + 1}/{num_attempts} failed: {str(e)}. Retrying in {delay}s...")
                    await asyncio.sleep(delay)
                    continue

                # Handle exceptions during async streaming
                run_response.status = RunStatus.error
                # Add error event to list of events
                run_error = create_run_error_event(run_response, error=str(e))
                run_response.events = add_error_event(error=run_error, events=run_response.events)

                # If the content is None, set it to the error message
                if run_response.content is None:
                    run_response.content = str(e)

                log_error(f"Error in Agent run: {str(e)}")

                # Cleanup and store the run response and session
                if agent_session is not None:
                    await acleanup_and_store(
                        agent,
                        run_response=run_response,
                        session=agent_session,
                        run_context=run_context,
                        user_id=user_id,
                    )

                # Yield the error event
                yield run_error
    finally:
        # Always disconnect connectable tools
        disconnect_connectable_tools(agent)
        # Always disconnect MCP tools
        await disconnect_mcp_tools(agent)

        # Cancel background tasks on error (await_for_thread_tasks_stream handles waiting on success)
        if memory_task is not None and not memory_task.done():
            memory_task.cancel()
            try:
                await memory_task
            except asyncio.CancelledError:
                pass

        if cultural_knowledge_task is not None and not cultural_knowledge_task.done():
            cultural_knowledge_task.cancel()
            try:
                await cultural_knowledge_task
            except asyncio.CancelledError:
                pass

        if learning_task is not None and not learning_task.done():
            learning_task.cancel()
            try:
                await learning_task
            except asyncio.CancelledError:
                pass

        # Always clean up the run tracking
        await acleanup_run(run_response.run_id)  # type: ignore


def arun_dispatch(  # type: ignore
    agent: Agent,
    input: Union[str, List, Dict, Message, BaseModel, List[Message]],
    *,
    stream: Optional[bool] = None,
    user_id: Optional[str] = None,
    session_id: Optional[str] = None,
    session_state: Optional[Dict[str, Any]] = None,
    run_context: Optional[RunContext] = None,
    run_id: Optional[str] = None,
    audio: Optional[Sequence[Audio]] = None,
    images: Optional[Sequence[Image]] = None,
    videos: Optional[Sequence[Video]] = None,
    files: Optional[Sequence[File]] = None,
    stream_events: Optional[bool] = None,
    knowledge_filters: Optional[Union[Dict[str, Any], List[FilterExpr]]] = None,
    add_history_to_context: Optional[bool] = None,
    add_dependencies_to_context: Optional[bool] = None,
    add_session_state_to_context: Optional[bool] = None,
    dependencies: Optional[Dict[str, Any]] = None,
    metadata: Optional[Dict[str, Any]] = None,
    output_schema: Optional[Union[Type[BaseModel], Dict[str, Any]]] = None,
    yield_run_output: Optional[bool] = None,
    debug_mode: Optional[bool] = None,
    background: bool = False,
    **kwargs: Any,
) -> Union[RunOutput, AsyncIterator[RunOutputEvent]]:
    """Async Run the Agent and return the response."""

    # Set the id for the run and register it immediately for cancellation tracking
    from agno.agent._response import get_response_format

    run_id = run_id or str(uuid4())

    if (add_history_to_context or agent.add_history_to_context) and not agent.db and not agent.team_id:
        log_warning(
            "add_history_to_context is True, but no database has been assigned to the agent. History will not be added to the context."
        )

    background_tasks = kwargs.pop("background_tasks", None)
    if background_tasks is not None:
        from fastapi import BackgroundTasks

        background_tasks: BackgroundTasks = background_tasks  # type: ignore

    # 2. Validate input against input_schema if provided
    validated_input = validate_input(input, agent.input_schema)

    # Normalise hooks & guardails
    if not agent._hooks_normalised:
        if agent.pre_hooks:
            agent.pre_hooks = normalize_pre_hooks(agent.pre_hooks, async_mode=True)  # type: ignore
        if agent.post_hooks:
            agent.post_hooks = normalize_post_hooks(agent.post_hooks, async_mode=True)  # type: ignore
        agent._hooks_normalised = True

    # Initialize session
    session_id, user_id = initialize_session(agent, session_id=session_id, user_id=user_id)

    # Initialize the Agent
    agent.initialize_agent(debug_mode=debug_mode)

    image_artifacts, video_artifacts, audio_artifacts, file_artifacts = validate_media_object_id(
        images=images, videos=videos, audios=audio, files=files
    )

    # Create RunInput to capture the original user input
    run_input = RunInput(
        input_content=validated_input,
        images=image_artifacts,
        videos=video_artifacts,
        audios=audio_artifacts,
        files=file_artifacts,
    )

    # Read existing session and update metadata BEFORE resolving run options,
    # so that session-stored metadata is visible to resolve_run_options.
    # Note: arun_dispatch is NOT async, so we can only pre-read with a sync DB.
    # For async DB, _arun/_arun_stream will handle the session read themselves.
    from agno.agent._init import has_async_db
    from agno.agent._storage import update_metadata

    _pre_session: Optional[AgentSession] = None
    if not has_async_db(agent):
        from agno.agent._storage import read_or_create_session

        _pre_session = read_or_create_session(agent, session_id=session_id, user_id=user_id)
        update_metadata(agent, session=_pre_session)

    # Resolve all run options centrally
    opts = resolve_run_options(
        agent,
        stream=stream,
        stream_events=stream_events,
        yield_run_output=yield_run_output,
        add_history_to_context=add_history_to_context,
        add_dependencies_to_context=add_dependencies_to_context,
        add_session_state_to_context=add_session_state_to_context,
        dependencies=dependencies,
        knowledge_filters=knowledge_filters,
        metadata=metadata,
        output_schema=output_schema,
    )

    agent.model = cast(Model, agent.model)

    # Initialize run context
    run_context = run_context or RunContext(
        run_id=run_id,
        session_id=session_id,
        user_id=user_id,
        session_state=session_state,
        dependencies=opts.dependencies,
        knowledge_filters=opts.knowledge_filters,
        metadata=opts.metadata,
        output_schema=opts.output_schema,
    )
    # Apply options with precedence: explicit args > existing run_context > resolved defaults.
    opts.apply_to_context(
        run_context,
        dependencies_provided=dependencies is not None,
        knowledge_filters_provided=knowledge_filters is not None,
        metadata_provided=metadata is not None,
    )

    # Prepare arguments for the model (must be after run_context is fully initialized)
    response_format = get_response_format(agent, run_context=run_context) if agent.parser_model is None else None

    # Create a new run_response for this attempt
    run_response = RunOutput(
        run_id=run_id,
        session_id=session_id,
        agent_id=agent.id,
        user_id=user_id,
        agent_name=agent.name,
        metadata=run_context.metadata,
        session_state=run_context.session_state,
        input=run_input,
    )

    run_response.model = agent.model.id if agent.model is not None else None
    run_response.model_provider = agent.model.provider if agent.model is not None else None

    # Start the run metrics timer, to calculate the run duration
    run_response.metrics = RunMetrics()
    run_response.metrics.start_timer()

    # Background execution: return immediately with PENDING status
    if background:
        if opts.stream:
            raise ValueError(
                "Background execution cannot be combined with streaming. Set stream=False when using background=True."
            )
        if not agent.db:
            raise ValueError(
                "Background execution requires a database to be configured on the agent for run persistence."
            )
        return _arun_background(  # type: ignore[return-value]
            agent,
            run_response=run_response,
            run_context=run_context,
            user_id=user_id,
            response_format=response_format,
            session_id=session_id,
            add_history_to_context=opts.add_history_to_context,
            add_dependencies_to_context=opts.add_dependencies_to_context,
            add_session_state_to_context=opts.add_session_state_to_context,
            debug_mode=debug_mode,
            background_tasks=background_tasks,
            **kwargs,
        )

    # Pass the new run_response to _arun
    if opts.stream:
        return _arun_stream(  # type: ignore
            agent,
            run_response=run_response,
            run_context=run_context,
            user_id=user_id,
            response_format=response_format,
            stream_events=opts.stream_events,
            yield_run_output=opts.yield_run_output,
            session_id=session_id,
            add_history_to_context=opts.add_history_to_context,
            add_dependencies_to_context=opts.add_dependencies_to_context,
            add_session_state_to_context=opts.add_session_state_to_context,
            debug_mode=debug_mode,
            background_tasks=background_tasks,
            pre_session=_pre_session,
            **kwargs,
        )  # type: ignore[assignment]
    else:
        return _arun(  # type: ignore
            agent,
            run_response=run_response,
            run_context=run_context,
            user_id=user_id,
            response_format=response_format,
            session_id=session_id,
            add_history_to_context=opts.add_history_to_context,
            add_dependencies_to_context=opts.add_dependencies_to_context,
            add_session_state_to_context=opts.add_session_state_to_context,
            debug_mode=debug_mode,
            background_tasks=background_tasks,
            pre_session=_pre_session,
            **kwargs,
        )


def continue_run_dispatch(
    agent: Agent,
    run_response: Optional[RunOutput] = None,
    *,
    run_id: Optional[str] = None,  # type: ignore
    updated_tools: Optional[List[ToolExecution]] = None,
    requirements: Optional[List[RunRequirement]] = None,
    stream: Optional[bool] = None,
    stream_events: Optional[bool] = False,
    user_id: Optional[str] = None,
    session_id: Optional[str] = None,
    run_context: Optional[RunContext] = None,
    knowledge_filters: Optional[Union[Dict[str, Any], List[FilterExpr]]] = None,
    dependencies: Optional[Dict[str, Any]] = None,
    metadata: Optional[Dict[str, Any]] = None,
    debug_mode: Optional[bool] = None,
    yield_run_output: bool = False,
    **kwargs,
) -> Union[RunOutput, Iterator[Union[RunOutputEvent, RunOutput]]]:
    """Continue a previous run.

    Args:
        run_response: The run response to continue.
        run_id: The run id to continue. Alternative to passing run_response.
        requirements: The requirements to continue the run. This or updated_tools is required with `run_id`.
        stream: Whether to stream the response.
        stream_events: Whether to stream all events.
        user_id: The user id to continue the run for.
        session_id: The session id to continue the run for.
        run_context: The run context to use for the run.
        knowledge_filters: The knowledge filters to use for the run.
        dependencies: The dependencies to use for the run.
        metadata: The metadata to use for the run.
        debug_mode: Whether to enable debug mode.
    """
    from agno.agent._init import has_async_db, set_default_model
    from agno.agent._messages import get_continue_run_messages
    from agno.agent._response import get_response_format
    from agno.agent._storage import load_session_state, read_or_create_session, update_metadata
    from agno.agent._tools import determine_tools_for_model

    if run_response is None and run_id is None:
        raise ValueError("Either run_response or run_id must be provided.")

    if run_response is None and (run_id is not None and (session_id is None and agent.session_id is None)):
        raise ValueError("Session ID is required to continue a run from a run_id.")

    if has_async_db(agent):
        raise Exception("continue_run() is not supported with an async DB. Please use acontinue_run() instead.")

    background_tasks = kwargs.pop("background_tasks", None)
    if background_tasks is not None:
        from fastapi import BackgroundTasks

        background_tasks: BackgroundTasks = background_tasks  # type: ignore

    session_id = run_response.session_id if run_response else session_id
    run_id: str = run_response.run_id if run_response else run_id  # type: ignore

    session_id, user_id = initialize_session(
        agent,
        session_id=session_id,
        user_id=user_id,
    )
    # Initialize the Agent
    agent.initialize_agent(debug_mode=debug_mode)

    # Read existing session from storage
    agent_session = read_or_create_session(agent, session_id=session_id, user_id=user_id)
    update_metadata(agent, session=agent_session)

    # Initialize session state. Get it from DB if relevant.
    session_state = load_session_state(agent, session=agent_session, session_state={})

    # Resolve all run options centrally
    opts = resolve_run_options(
        agent,
        stream=stream,
        stream_events=stream_events,
        yield_run_output=yield_run_output,
        dependencies=dependencies,
        knowledge_filters=knowledge_filters,
        metadata=metadata,
    )

    # Initialize run context
    run_context = run_context or RunContext(
        run_id=run_id,  # type: ignore
        session_id=session_id,
        user_id=user_id,
        session_state=session_state,
        dependencies=opts.dependencies,
        knowledge_filters=opts.knowledge_filters,
        metadata=opts.metadata,
    )
    # Apply options with precedence: explicit args > existing run_context > resolved defaults.
    opts.apply_to_context(
        run_context,
        dependencies_provided=dependencies is not None,
        knowledge_filters_provided=knowledge_filters is not None,
        metadata_provided=metadata is not None,
    )

    # Resolve dependencies
    if run_context.dependencies is not None:
        resolve_run_dependencies(agent, run_context=run_context)

    # Run can be continued from previous run response or from passed run_response context
    if run_response is not None:
        # The run is continued from a provided run_response. This contains the updated tools.
        input = run_response.messages or []
    elif run_id is not None:
        # The run is continued from a run_id, one of requirements or updated_tool (deprecated) is required.
        if updated_tools is None and requirements is None:
            raise ValueError("To continue a run from a given run_id, the requirements parameter must be provided.")

        runs = agent_session.runs or []
        run_response = next((r for r in runs if r.run_id == run_id), None)  # type: ignore
        if run_response is None:
            raise RuntimeError(f"No runs found for run ID {run_id}")

        input = run_response.messages or []

        # If we have updated_tools, set them in the run_response
        if updated_tools is not None:
            warnings.warn(
                "The 'updated_tools' parameter is deprecated and will be removed in future versions. Use 'requirements' instead.",
                DeprecationWarning,
                stacklevel=2,
            )
            run_response.tools = updated_tools

        # If we have requirements, get the updated tools and set them in the run_response
        elif requirements is not None:
            run_response.requirements = requirements
            updated_tools = [req.tool_execution for req in requirements if req.tool_execution is not None]
            if updated_tools and run_response.tools:
                updated_tools_map = {tool.tool_call_id: tool for tool in updated_tools}
                run_response.tools = [updated_tools_map.get(tool.tool_call_id, tool) for tool in run_response.tools]
            else:
                run_response.tools = updated_tools
    else:
        raise ValueError("Either run_response or run_id must be provided.")

    # Prepare arguments for the model
    set_default_model(agent)
    response_format = get_response_format(agent, run_context=run_context)
    agent.model = cast(Model, agent.model)

    processed_tools = agent.get_tools(
        run_response=run_response,
        run_context=run_context,
        session=agent_session,
        user_id=user_id,
    )

    _tools = determine_tools_for_model(
        agent,
        model=agent.model,
        processed_tools=processed_tools,
        run_response=run_response,
        run_context=run_context,
        session=agent_session,
    )

    run_response = cast(RunOutput, run_response)

    log_debug(f"Agent Run Start: {run_response.run_id}", center=True)

    # Prepare run messages
    run_messages = get_continue_run_messages(
        agent,
        input=input,
    )

    # Reset the run state
    run_response.status = RunStatus.running

    if opts.stream:
        response_iterator = _continue_run_stream(
            agent,
            run_response=run_response,
            run_messages=run_messages,
            run_context=run_context,
            tools=_tools,
            user_id=user_id,
            session=agent_session,
            response_format=response_format,
            stream_events=opts.stream_events,
            yield_run_output=opts.yield_run_output,
            debug_mode=debug_mode,
            background_tasks=background_tasks,
            **kwargs,
        )
        return response_iterator
    else:
        response = _continue_run(
            agent,
            run_response=run_response,
            run_messages=run_messages,
            run_context=run_context,
            tools=_tools,
            user_id=user_id,
            session=agent_session,
            response_format=response_format,
            debug_mode=debug_mode,
            background_tasks=background_tasks,
            **kwargs,
        )
        return response


def _continue_run(
    agent: Agent,
    run_response: RunOutput,
    run_messages: RunMessages,
    run_context: RunContext,
    session: AgentSession,
    tools: List[Union[Function, dict]],
    user_id: Optional[str] = None,
    response_format: Optional[Union[Dict, Type[BaseModel]]] = None,
    debug_mode: Optional[bool] = None,
    background_tasks: Optional[Any] = None,
    **kwargs,
) -> RunOutput:
    """Continue a previous run.

    Steps:
    1. Handle any updated tools
    2. Generate a response from the Model
    3. Update the RunOutput with the model response
    4. Convert response to structured format
    5. Store media if enabled
    6. Execute post-hooks
    7. Create session summary
    8. Cleanup and store (scrub, stop timer, save to file, add to session, calculate metrics, save session)
    """
    # Register run for cancellation tracking
    from agno.agent._hooks import execute_post_hooks
    from agno.agent._init import disconnect_connectable_tools
    from agno.agent._response import (
        convert_response_to_structured_format,
        generate_response_with_output_model,
        parse_response_with_parser_model,
        update_run_response,
    )
    from agno.agent._telemetry import log_agent_telemetry
    from agno.agent._tools import handle_tool_call_updates

    register_run(run_response.run_id)  # type: ignore

    agent.model = cast(Model, agent.model)

    # 1. Handle the updated tools
    handle_tool_call_updates(agent, run_response=run_response, run_messages=run_messages, tools=tools)

    try:
        num_attempts = agent.retries + 1
        for attempt in range(num_attempts):
            try:
                # Check for cancellation before model call
                raise_if_cancelled(run_response.run_id)  # type: ignore

                # 2. Generate a response from the Model (includes running function calls)
                agent.model = cast(Model, agent.model)
                model_response: ModelResponse = agent.model.response(
                    messages=run_messages.messages,
                    response_format=response_format,
                    tools=tools,
                    tool_choice=agent.tool_choice,
                    tool_call_limit=agent.tool_call_limit,
                    run_response=run_response,
                    send_media_to_model=agent.send_media_to_model,
                    compression_manager=agent.compression_manager if agent.compress_tool_results else None,
                )

                # Check for cancellation after model processing
                raise_if_cancelled(run_response.run_id)  # type: ignore

                # If an output model is provided, generate output using the output model
                generate_response_with_output_model(agent, model_response, run_messages, run_response=run_response)

                # If a parser model is provided, structure the response separately
                parse_response_with_parser_model(
                    agent, model_response, run_messages, run_context=run_context, run_response=run_response
                )

                # 3. Update the RunOutput with the model response
                update_run_response(
                    agent,
                    model_response=model_response,
                    run_response=run_response,
                    run_messages=run_messages,
                    run_context=run_context,
                )

                # We should break out of the run function
                if any(tool_call.is_paused for tool_call in run_response.tools or []):
                    return handle_agent_run_paused(
                        agent, run_response=run_response, session=session, run_context=run_context, user_id=user_id
                    )

                # 4. Convert the response to the structured format if needed
                convert_response_to_structured_format(agent, run_response, run_context=run_context)

                # 5. Store media if enabled
                if agent.store_media:
                    store_media_util(run_response, model_response)

                # 6. Execute post-hooks
                if agent.post_hooks is not None:
                    post_hook_iterator = execute_post_hooks(
                        agent,
                        hooks=agent.post_hooks,  # type: ignore
                        run_output=run_response,
                        run_context=run_context,
                        session=session,
                        user_id=user_id,
                        debug_mode=debug_mode,
                        background_tasks=background_tasks,
                        **kwargs,
                    )
                    deque(post_hook_iterator, maxlen=0)
                # Check for cancellation
                raise_if_cancelled(run_response.run_id)  # type: ignore

                # 7. Create session summary
                if agent.session_summary_manager is not None and agent.enable_session_summaries:
                    # Upsert the RunOutput to Agent Session before creating the session summary
                    session.upsert_run(run=run_response)

                    try:
                        agent.session_summary_manager.create_session_summary(session=session, run_response=run_response)
                    except Exception as e:
                        log_warning(f"Error in session summary creation: {str(e)}")

                # Set the run status to completed
                run_response.status = RunStatus.completed

                # 8. Cleanup and store the run response and session
                cleanup_and_store(
                    agent, run_response=run_response, session=session, run_context=run_context, user_id=user_id
                )

                # Log Agent Telemetry
                log_agent_telemetry(agent, session_id=session.session_id, run_id=run_response.run_id)

                return run_response
            except RunCancelledException as e:
                run_response = cast(RunOutput, run_response)
                # Handle run cancellation during async streaming
                log_info(f"Run {run_response.run_id} was cancelled")
                run_response.status = RunStatus.cancelled
                run_response.content = str(e)

                # Cleanup and store the run response and session
                cleanup_and_store(
                    agent, run_response=run_response, session=session, run_context=run_context, user_id=user_id
                )

                return run_response
            except (InputCheckError, OutputCheckError) as e:
                run_response = cast(RunOutput, run_response)
                # Handle exceptions during streaming
                run_response.status = RunStatus.error
                # If the content is None, set it to the error message
                if run_response.content is None:
                    run_response.content = str(e)

                log_error(f"Validation failed: {str(e)} | Check trigger: {e.check_trigger}")

                cleanup_and_store(
                    agent, run_response=run_response, session=session, run_context=run_context, user_id=user_id
                )

                return run_response
            except KeyboardInterrupt:
                run_response = cast(RunOutput, run_response)
                run_response.status = RunStatus.cancelled
                run_response.content = "Operation cancelled by user"
                return run_response

            except Exception as e:
                run_response = cast(RunOutput, run_response)
                # Check if this is the last attempt
                if attempt < num_attempts - 1:
                    # Calculate delay with exponential backoff if enabled
                    if agent.exponential_backoff:
                        delay = agent.delay_between_retries * (2**attempt)
                    else:
                        delay = agent.delay_between_retries

                    log_warning(f"Attempt {attempt + 1}/{num_attempts} failed: {str(e)}. Retrying in {delay}s...")
                    time.sleep(delay)
                    continue
                run_response.status = RunStatus.error

                # If the content is None, set it to the error message
                if run_response.content is None:
                    run_response.content = str(e)

                log_error(f"Error in Agent run: {str(e)}")

                # Cleanup and store the run response and session
                cleanup_and_store(
                    agent, run_response=run_response, session=session, run_context=run_context, user_id=user_id
                )

                return run_response
    finally:
        # Always disconnect connectable tools
        disconnect_connectable_tools(agent)
        # Always clean up the run tracking
        cleanup_run(run_response.run_id)  # type: ignore
    return run_response


def _continue_run_stream(
    agent: Agent,
    run_response: RunOutput,
    run_messages: RunMessages,
    run_context: RunContext,
    session: AgentSession,
    tools: List[Union[Function, dict]],
    user_id: Optional[str] = None,
    response_format: Optional[Union[Dict, Type[BaseModel]]] = None,
    stream_events: bool = False,
    debug_mode: Optional[bool] = None,
    yield_run_output: bool = False,
    background_tasks: Optional[Any] = None,
    **kwargs,
) -> Iterator[Union[RunOutputEvent, RunOutput]]:
    """Continue a previous run.

    Steps:
    1. Resolve dependencies
    2. Handle any updated tools
    3. Process model response
    4. Execute post-hooks
    5. Create session summary
    6. Cleanup and store the run response and session
    """

    from agno.agent._hooks import execute_post_hooks
    from agno.agent._init import disconnect_connectable_tools
    from agno.agent._response import handle_model_response_stream, parse_response_with_parser_model_stream
    from agno.agent._telemetry import log_agent_telemetry
    from agno.agent._tools import handle_tool_call_updates_stream

    register_run(run_response.run_id)  # type: ignore

    # Set up retry logic
    num_attempts = agent.retries + 1
    try:
        for attempt in range(num_attempts):
            try:
                # 1. Resolve dependencies
                if run_context.dependencies is not None:
                    resolve_run_dependencies(agent, run_context=run_context)

                # Start the Run by yielding a RunContinued event
                if stream_events:
                    yield handle_event(  # type: ignore
                        create_run_continued_event(run_response),
                        run_response,
                        events_to_skip=agent.events_to_skip,  # type: ignore
                        store_events=agent.store_events,
                    )

                # 2. Handle the updated tools
                yield from handle_tool_call_updates_stream(
                    agent,
                    run_response=run_response,
                    run_messages=run_messages,
                    tools=tools,
                    stream_events=stream_events,
                )

                # 3. Process model response
                for event in handle_model_response_stream(
                    agent,
                    session=session,
                    run_response=run_response,
                    run_messages=run_messages,
                    tools=tools,
                    response_format=response_format,
                    stream_events=stream_events,
                    session_state=run_context.session_state,
                    run_context=run_context,
                ):
                    yield event

                # Parse response with parser model if provided
                yield from parse_response_with_parser_model_stream(
                    agent,  # type: ignore
                    session=session,
                    run_response=run_response,
                    stream_events=stream_events,
                    run_context=run_context,
                )

                # Yield RunContentCompletedEvent
                if stream_events:
                    yield handle_event(  # type: ignore
                        create_run_content_completed_event(from_run_response=run_response),
                        run_response,
                        events_to_skip=agent.events_to_skip,  # type: ignore
                        store_events=agent.store_events,
                    )

                # We should break out of the run function
                if any(tool_call.is_paused for tool_call in run_response.tools or []):
                    yield from handle_agent_run_paused_stream(
                        agent,
                        run_response=run_response,
                        session=session,
                        run_context=run_context,
                        user_id=user_id,
                        yield_run_output=yield_run_output or False,
                    )
                    return

                # Execute post-hooks
                if agent.post_hooks is not None:
                    yield from execute_post_hooks(
                        agent,
                        hooks=agent.post_hooks,  # type: ignore
                        run_output=run_response,
                        session=session,
                        run_context=run_context,
                        user_id=user_id,
                        debug_mode=debug_mode,
                        stream_events=stream_events,
                        background_tasks=background_tasks,
                        **kwargs,
                    )

                # Check for cancellation before model call
                raise_if_cancelled(run_response.run_id)  # type: ignore

                # 4. Create session summary
                if agent.session_summary_manager is not None and agent.enable_session_summaries:
                    # Upsert the RunOutput to Agent Session before creating the session summary
                    session.upsert_run(run=run_response)

                    if stream_events:
                        yield handle_event(  # type: ignore
                            create_session_summary_started_event(from_run_response=run_response),
                            run_response,
                            events_to_skip=agent.events_to_skip,  # type: ignore
                            store_events=agent.store_events,
                        )
                    try:
                        agent.session_summary_manager.create_session_summary(session=session, run_response=run_response)
                    except Exception as e:
                        log_warning(f"Error in session summary creation: {str(e)}")

                    if stream_events:
                        yield handle_event(  # type: ignore
                            create_session_summary_completed_event(
                                from_run_response=run_response, session_summary=session.summary
                            ),
                            run_response,
                            events_to_skip=agent.events_to_skip,  # type: ignore
                            store_events=agent.store_events,
                        )

                # Update run_response.session_state before creating RunCompletedEvent
                # This ensures the event has the final state after all tool modifications
                if session.session_data is not None and "session_state" in session.session_data:
                    run_response.session_state = session.session_data["session_state"]

                # Create the run completed event
                completed_event = handle_event(
                    create_run_completed_event(run_response),
                    run_response,
                    events_to_skip=agent.events_to_skip,  # type: ignore
                    store_events=agent.store_events,
                )

                # Set the run status to completed
                run_response.status = RunStatus.completed

                # 5. Cleanup and store the run response and session
                cleanup_and_store(
                    agent, run_response=run_response, session=session, run_context=run_context, user_id=user_id
                )

                if stream_events:
                    yield completed_event  # type: ignore

                if yield_run_output:
                    yield run_response

                # Log Agent Telemetry
                log_agent_telemetry(agent, session_id=session.session_id, run_id=run_response.run_id)

                log_debug(f"Agent Run End: {run_response.run_id}", center=True, symbol="*")

                break
            except RunCancelledException as e:
                run_response = cast(RunOutput, run_response)
                # Handle run cancellation during async streaming
                log_info(f"Run {run_response.run_id} was cancelled during streaming")
                run_response.status = RunStatus.cancelled
                run_response.content = str(e)

                # Yield the cancellation event
                yield handle_event(  # type: ignore
                    create_run_cancelled_event(from_run_response=run_response, reason=str(e)),
                    run_response,
                    events_to_skip=agent.events_to_skip,  # type: ignore
                    store_events=agent.store_events,
                )

                # Cleanup and store the run response and session
                cleanup_and_store(
                    agent, run_response=run_response, session=session, run_context=run_context, user_id=user_id
                )
                break
            except (InputCheckError, OutputCheckError) as e:
                run_response = cast(RunOutput, run_response)
                # Handle exceptions during streaming
                run_response.status = RunStatus.error
                # Add error event to list of events
                run_error = create_run_error_event(
                    run_response,
                    error=str(e),
                    error_id=e.error_id,
                    error_type=e.type,
                    additional_data=e.additional_data,
                )
                run_response.events = add_error_event(error=run_error, events=run_response.events)

                # If the content is None, set it to the error message
                if run_response.content is None:
                    run_response.content = str(e)

                log_error(f"Validation failed: {str(e)} | Check trigger: {e.check_trigger}")

                cleanup_and_store(
                    agent, run_response=run_response, session=session, run_context=run_context, user_id=user_id
                )
                yield run_error
                break
            except KeyboardInterrupt:
                run_response = cast(RunOutput, run_response)
                yield handle_event(  # type: ignore
                    create_run_cancelled_event(from_run_response=run_response, reason="Operation cancelled by user"),
                    run_response,
                    events_to_skip=agent.events_to_skip,  # type: ignore
                    store_events=agent.store_events,
                )
                break

            except Exception as e:
                run_response = cast(RunOutput, run_response)
                # Check if this is the last attempt
                if attempt < num_attempts - 1:
                    # Calculate delay with exponential backoff if enabled
                    if agent.exponential_backoff:
                        delay = agent.delay_between_retries * (2**attempt)
                    else:
                        delay = agent.delay_between_retries

                    log_warning(f"Attempt {attempt + 1}/{num_attempts} failed: {str(e)}. Retrying in {delay}s...")
                    time.sleep(delay)
                    continue
                run_response.status = RunStatus.error
                # Add error event to list of events
                run_error = create_run_error_event(run_response, error=str(e))
                run_response.events = add_error_event(error=run_error, events=run_response.events)

                # If the content is None, set it to the error message
                if run_response.content is None:
                    run_response.content = str(e)

                log_error(f"Error in Agent run: {str(e)}")

                # Cleanup and store the run response and session
                cleanup_and_store(
                    agent, run_response=run_response, session=session, run_context=run_context, user_id=user_id
                )

                yield run_error
    finally:
        # Always disconnect connectable tools
        disconnect_connectable_tools(agent)
        # Always clean up the run tracking
        cleanup_run(run_response.run_id)  # type: ignore


def acontinue_run_dispatch(  # type: ignore
    agent: Agent,
    run_response: Optional[RunOutput] = None,
    *,
    run_id: Optional[str] = None,  # type: ignore
    updated_tools: Optional[List[ToolExecution]] = None,
    requirements: Optional[List[RunRequirement]] = None,
    stream: Optional[bool] = None,
    stream_events: Optional[bool] = None,
    user_id: Optional[str] = None,
    session_id: Optional[str] = None,
    run_context: Optional[RunContext] = None,
    knowledge_filters: Optional[Union[Dict[str, Any], List[FilterExpr]]] = None,
    dependencies: Optional[Dict[str, Any]] = None,
    metadata: Optional[Dict[str, Any]] = None,
    debug_mode: Optional[bool] = None,
    yield_run_output: bool = False,
    **kwargs,
) -> Union[RunOutput, AsyncIterator[Union[RunOutputEvent, RunOutput]]]:
    """Continue a previous run.

    Args:
        run_response: The run response to continue.
        run_id: The run id to continue. Alternative to passing run_response.

        requirements: The requirements to continue the run. This or updated_tools is required with `run_id`.
        stream: Whether to stream the response.
        stream_events: Whether to stream all events.
        user_id: The user id to continue the run for.
        session_id: The session id to continue the run for.
        run_context: The run context to use for the run.
        knowledge_filters: The knowledge filters to use for the run.
        dependencies: The dependencies to use for continuing the run.
        metadata: The metadata to use for continuing the run.
        debug_mode: Whether to enable debug mode.
        yield_run_output: Whether to yield the run response.
        (deprecated) updated_tools: Use 'requirements' instead.
    """
    from agno.agent._response import get_response_format

    if run_response is None and run_id is None:
        raise ValueError("Either run_response or run_id must be provided.")

    if run_response is None and (run_id is not None and (session_id is None and agent.session_id is None)):
        raise ValueError("Session ID is required to continue a run from a run_id.")

    if updated_tools is not None:
        warnings.warn(
            "The 'updated_tools' parameter is deprecated and will be removed in future versions. Use 'requirements' instead.",
            DeprecationWarning,
            stacklevel=2,
        )
    background_tasks = kwargs.pop("background_tasks", None)
    if background_tasks is not None:
        from fastapi import BackgroundTasks

        background_tasks: BackgroundTasks = background_tasks  # type: ignore

    session_id = run_response.session_id if run_response else session_id
    run_id: str = run_response.run_id if run_response else run_id  # type: ignore

    session_id, user_id = initialize_session(
        agent,
        session_id=session_id,
        user_id=user_id,
    )

    # Initialize the Agent
    agent.initialize_agent(debug_mode=debug_mode)

    # Read existing session and update metadata BEFORE resolving run options,
    # so that session-stored metadata is visible to resolve_run_options.
    from agno.agent._init import has_async_db

    _session_state: Dict[str, Any] = {}
    if not has_async_db(agent):
        from agno.agent._storage import load_session_state, read_or_create_session, update_metadata

        _pre_session = read_or_create_session(agent, session_id=session_id, user_id=user_id)
        update_metadata(agent, session=_pre_session)
        _session_state = load_session_state(agent, session=_pre_session, session_state={})

    # Resolve all run options centrally
    opts = resolve_run_options(
        agent,
        stream=stream,
        stream_events=stream_events,
        yield_run_output=yield_run_output,
        dependencies=dependencies,
        knowledge_filters=knowledge_filters,
        metadata=metadata,
    )

    # Prepare arguments for the model
    agent.model = cast(Model, agent.model)

    # Initialize run context before computing response_format (needs run_context)
    run_context = run_context or RunContext(
        run_id=run_id,  # type: ignore
        session_id=session_id,
        user_id=user_id,
        session_state=_session_state,
        dependencies=opts.dependencies,
        knowledge_filters=opts.knowledge_filters,
        metadata=opts.metadata,
    )
    # Apply options with precedence: explicit args > existing run_context > resolved defaults.
    opts.apply_to_context(
        run_context,
        dependencies_provided=dependencies is not None,
        knowledge_filters_provided=knowledge_filters is not None,
        metadata_provided=metadata is not None,
    )

    response_format = get_response_format(agent, run_context=run_context)

    if opts.stream:
        return _acontinue_run_stream(
            agent,
            run_response=run_response,
            run_context=run_context,
            updated_tools=updated_tools,
            requirements=requirements,
            run_id=run_id,
            user_id=user_id,
            session_id=session_id,
            response_format=response_format,
            stream_events=opts.stream_events,
            yield_run_output=opts.yield_run_output,
            debug_mode=debug_mode,
            background_tasks=background_tasks,
            **kwargs,
        )
    else:
        return _acontinue_run(  # type: ignore
            agent,
            session_id=session_id,
            run_response=run_response,
            run_context=run_context,
            updated_tools=updated_tools,
            requirements=requirements,
            run_id=run_id,
            user_id=user_id,
            response_format=response_format,
            debug_mode=debug_mode,
            background_tasks=background_tasks,
            **kwargs,
        )


async def _acontinue_run(
    agent: Agent,
    session_id: str,
    run_context: RunContext,
    run_response: Optional[RunOutput] = None,
    updated_tools: Optional[List[ToolExecution]] = None,
    requirements: Optional[List[RunRequirement]] = None,
    run_id: Optional[str] = None,
    user_id: Optional[str] = None,
    response_format: Optional[Union[Dict, Type[BaseModel]]] = None,
    debug_mode: Optional[bool] = None,
    background_tasks: Optional[Any] = None,
    **kwargs,
) -> RunOutput:
    """Continue a previous run.

    Steps:
    1. Read existing session from db
    2. Resolve dependencies
    3. Update metadata and session state
    4. Prepare run response
    5. Determine tools for model
    6. Prepare run messages
    7. Handle the updated tools
    8. Get model response
    9. Update the RunOutput with the model response
    10. Convert response to structured format
    11. Store media if enabled
    12. Execute post-hooks
    13. Create session summary
    14. Cleanup and store (scrub, stop timer, save to file, add to session, calculate metrics, save session)
    """
    from agno.agent._hooks import aexecute_post_hooks
    from agno.agent._init import disconnect_connectable_tools, disconnect_mcp_tools
    from agno.agent._messages import get_continue_run_messages
    from agno.agent._response import (
        agenerate_response_with_output_model,
        aparse_response_with_parser_model,
        convert_response_to_structured_format,
        update_run_response,
    )
    from agno.agent._storage import aread_or_create_session, load_session_state, update_metadata
    from agno.agent._telemetry import alog_agent_telemetry
    from agno.agent._tools import ahandle_tool_call_updates, determine_tools_for_model

    log_debug(f"Agent Run Continue: {run_response.run_id if run_response else run_id}", center=True)  # type: ignore
    agent_session: Optional[AgentSession] = None

    # Resolve retry parameters
    try:
        num_attempts = agent.retries + 1
        for attempt in range(num_attempts):
            try:
                if attempt > 0:
                    log_debug(f"Retrying Agent acontinue_run {run_id}. Attempt {attempt + 1} of {num_attempts}...")

                # 1. Read existing session from db
                agent_session = await aread_or_create_session(agent, session_id=session_id, user_id=user_id)

                # 2. Resolve dependencies
                if run_context.dependencies is not None:
                    await aresolve_run_dependencies(agent, run_context=run_context)

                # 3. Update metadata and session state
                update_metadata(agent, session=agent_session)

                # Initialize session state. Get it from DB if relevant.
                run_context.session_state = load_session_state(
                    agent,
                    session=agent_session,
                    session_state=run_context.session_state if run_context.session_state is not None else {},
                )
                _initialize_session_state(
                    run_context.session_state,
                    user_id=user_id,
                    session_id=session_id,
                    run_id=run_context.run_id,
                )

                # 4. Prepare run response
                if run_response is not None:
                    # The run is continued from a provided run_response. This contains the updated tools.
                    input = run_response.messages or []
                elif run_id is not None:
                    # The run is continued from a run_id. This requires the updated tools to be passed.
                    if updated_tools is None and requirements is None:
                        raise ValueError(
                            "Either updated tools or requirements are required to continue a run from a run_id."
                        )

                    runs = agent_session.runs or []
                    run_response = next((r for r in runs if r.run_id == run_id), None)  # type: ignore
                    if run_response is None:
                        raise RuntimeError(f"No runs found for run ID {run_id}")

                    input = run_response.messages or []

                    # If we have updated_tools, set them in the run_response
                    if updated_tools is not None:
                        run_response.tools = updated_tools

                    # If we have requirements, get the updated tools and set them in the run_response
                    elif requirements is not None:
                        run_response.requirements = requirements
                        updated_tools = [req.tool_execution for req in requirements if req.tool_execution is not None]
                        if updated_tools and run_response.tools:
                            updated_tools_map = {tool.tool_call_id: tool for tool in updated_tools}
                            run_response.tools = [
                                updated_tools_map.get(tool.tool_call_id, tool) for tool in run_response.tools
                            ]
                        else:
                            run_response.tools = updated_tools
                else:
                    raise ValueError("Either run_response or run_id must be provided.")

                run_response = cast(RunOutput, run_response)

                run_response.status = RunStatus.running

                # 5. Determine tools for model
                agent.model = cast(Model, agent.model)
                processed_tools = await agent.aget_tools(
                    run_response=run_response,
                    run_context=run_context,
                    session=agent_session,
                    user_id=user_id,
                )

                _tools = determine_tools_for_model(
                    agent,
                    model=agent.model,
                    processed_tools=processed_tools,
                    run_response=run_response,
                    run_context=run_context,
                    session=agent_session,
                    async_mode=True,
                )

                # 6. Prepare run messages
                run_messages: RunMessages = get_continue_run_messages(
                    agent,
                    input=input,
                )

                # Register run for cancellation tracking
                await aregister_run(run_response.run_id)  # type: ignore

                # 7. Handle the updated tools
                await ahandle_tool_call_updates(
                    agent, run_response=run_response, run_messages=run_messages, tools=_tools
                )

                # 8. Get model response
                model_response: ModelResponse = await agent.model.aresponse(
                    messages=run_messages.messages,
                    response_format=response_format,
                    tools=_tools,
                    tool_choice=agent.tool_choice,
                    tool_call_limit=agent.tool_call_limit,
                    run_response=run_response,
                    send_media_to_model=agent.send_media_to_model,
                    compression_manager=agent.compression_manager if agent.compress_tool_results else None,
                )
                # Check for cancellation after model call
                await araise_if_cancelled(run_response.run_id)  # type: ignore

                # If an output model is provided, generate output using the output model
                await agenerate_response_with_output_model(
                    agent, model_response=model_response, run_messages=run_messages, run_response=run_response
                )

                # If a parser model is provided, structure the response separately
                await aparse_response_with_parser_model(
                    agent,
                    model_response=model_response,
                    run_messages=run_messages,
                    run_context=run_context,
                    run_response=run_response,
                )

                # 9. Update the RunOutput with the model response
                update_run_response(
                    agent,
                    model_response=model_response,
                    run_response=run_response,
                    run_messages=run_messages,
                    run_context=run_context,
                )

                # Break out of the run function if a tool call is paused
                if any(tool_call.is_paused for tool_call in run_response.tools or []):
                    return await ahandle_agent_run_paused(
                        agent,
                        run_response=run_response,
                        session=agent_session,
                        run_context=run_context,
                        user_id=user_id,
                    )

                # 10. Convert the response to the structured format if needed
                convert_response_to_structured_format(agent, run_response, run_context=run_context)

                # 11. Store media if enabled
                if agent.store_media:
                    store_media_util(run_response, model_response)

                await araise_if_cancelled(run_response.run_id)  # type: ignore

                # 12. Execute post-hooks
                if agent.post_hooks is not None:
                    async for _ in aexecute_post_hooks(
                        agent,
                        hooks=agent.post_hooks,  # type: ignore
                        run_output=run_response,
                        run_context=run_context,
                        session=agent_session,
                        user_id=user_id,
                        debug_mode=debug_mode,
                        background_tasks=background_tasks,
                        **kwargs,
                    ):
                        pass

                # Check for cancellation
                await araise_if_cancelled(run_response.run_id)  # type: ignore

                # 13. Create session summary
                if agent.session_summary_manager is not None and agent.enable_session_summaries:
                    # Upsert the RunOutput to Agent Session before creating the session summary
                    agent_session.upsert_run(run=run_response)

                    try:
                        await agent.session_summary_manager.acreate_session_summary(
                            session=agent_session, run_response=run_response
                        )
                    except Exception as e:
                        log_warning(f"Error in session summary creation: {str(e)}")

                # Set the run status to completed
                run_response.status = RunStatus.completed

                # 14. Cleanup and store the run response and session
                await acleanup_and_store(
                    agent,
                    run_response=run_response,
                    session=agent_session,
                    run_context=run_context,
                    user_id=user_id,
                )

                # Log Agent Telemetry
                await alog_agent_telemetry(agent, session_id=agent_session.session_id, run_id=run_response.run_id)

                log_debug(f"Agent Run End: {run_response.run_id}", center=True, symbol="*")

                return run_response

            except RunCancelledException as e:
                if run_response is None:
                    run_response = RunOutput(run_id=run_id)
                run_response = cast(RunOutput, run_response)
                # Handle run cancellation
                log_info(f"Run {run_response.run_id if run_response else run_id} was cancelled")
                run_response.status = RunStatus.cancelled
                run_response.content = str(e)
                # Cleanup and store the run response and session
                if agent_session is not None:
                    await acleanup_and_store(
                        agent,
                        run_response=run_response,
                        session=agent_session,
                        run_context=run_context,
                        user_id=user_id,
                    )

                return run_response
            except (InputCheckError, OutputCheckError) as e:
                run_response = cast(RunOutput, run_response)
                # Handle exceptions during streaming
                run_response.status = RunStatus.error
                # If the content is None, set it to the error message
                if run_response.content is None:
                    run_response.content = str(e)

                log_error(f"Validation failed: {str(e)} | Check trigger: {e.check_trigger}")

                if agent_session is not None:
                    await acleanup_and_store(
                        agent,
                        run_response=run_response,
                        session=agent_session,
                        run_context=run_context,
                        user_id=user_id,
                    )

                return run_response

            except KeyboardInterrupt:
                run_response = cast(RunOutput, run_response)
                run_response.status = RunStatus.cancelled
                run_response.content = "Operation cancelled by user"
                return run_response
            except Exception as e:
                run_response = cast(RunOutput, run_response)
                # Check if this is the last attempt
                if attempt < num_attempts - 1:
                    # Calculate delay with exponential backoff if enabled
                    if agent.exponential_backoff:
                        delay = agent.delay_between_retries * (2**attempt)
                    else:
                        delay = agent.delay_between_retries

                    log_warning(f"Attempt {attempt + 1}/{num_attempts} failed: {str(e)}. Retrying in {delay}s...")
                    await asyncio.sleep(delay)
                    continue

                if not run_response:
                    run_response = RunOutput(run_id=run_id)

                run_response.status = RunStatus.error
                # Add error event to list of events
                run_error = create_run_error_event(run_response, error=str(e))  # type: ignore
                run_response.events = add_error_event(error=run_error, events=run_response.events)  # type: ignore

                # If the content is None, set it to the error message
                if run_response.content is None:  # type: ignore
                    run_response.content = str(e)  # type: ignore

                log_error(f"Error in Agent run: {str(e)}")

                # Cleanup and store the run response and session
                if agent_session is not None:
                    await acleanup_and_store(
                        agent,
                        run_response=run_response,  # type: ignore
                        session=agent_session,
                        run_context=run_context,
                        user_id=user_id,
                    )

                return run_response  # type: ignore

    finally:
        # Always disconnect connectable tools
        disconnect_connectable_tools(agent)
        # Always disconnect MCP tools
        await disconnect_mcp_tools(agent)

        # Always clean up the run tracking
        await acleanup_run(run_response.run_id)  # type: ignore
    return run_response  # type: ignore


async def _acontinue_run_stream(
    agent: Agent,
    session_id: str,
    run_context: RunContext,
    run_response: Optional[RunOutput] = None,
    updated_tools: Optional[List[ToolExecution]] = None,
    requirements: Optional[List[RunRequirement]] = None,
    run_id: Optional[str] = None,
    user_id: Optional[str] = None,
    response_format: Optional[Union[Dict, Type[BaseModel]]] = None,
    stream_events: bool = False,
    yield_run_output: bool = False,
    debug_mode: Optional[bool] = None,
    background_tasks: Optional[Any] = None,
    **kwargs,
) -> AsyncIterator[Union[RunOutputEvent, RunOutput]]:
    """Continue a previous run.

    Steps:
    1. Resolve dependencies
    2. Read existing session from db
    3. Update session state and metadata
    4. Prepare run response
    5. Determine tools for model
    6. Prepare run messages
    7. Handle the updated tools
    8. Process model response
    9. Create session summary
    10. Execute post-hooks
    11. Cleanup and store the run response and session
    """
    from agno.agent._hooks import aexecute_post_hooks
    from agno.agent._init import disconnect_connectable_tools, disconnect_mcp_tools
    from agno.agent._messages import get_continue_run_messages
    from agno.agent._response import (
        agenerate_response_with_output_model_stream,
        ahandle_model_response_stream,
        aparse_response_with_parser_model_stream,
    )
    from agno.agent._storage import aread_or_create_session, load_session_state, update_metadata
    from agno.agent._telemetry import alog_agent_telemetry
    from agno.agent._tools import ahandle_tool_call_updates_stream, determine_tools_for_model

    log_debug(f"Agent Run Continue: {run_response.run_id if run_response else run_id}", center=True)  # type: ignore

    agent_session: Optional[AgentSession] = None

    # Resolve retry parameters
    try:
        num_attempts = agent.retries + 1
        for attempt in range(num_attempts):
            try:
                # 1. Read existing session from db
                agent_session = await aread_or_create_session(agent, session_id=session_id, user_id=user_id)

                # 2. Update session state and metadata
                update_metadata(agent, session=agent_session)

                # Initialize session state. Get it from DB if relevant.
                run_context.session_state = load_session_state(
                    agent,
                    session=agent_session,
                    session_state=run_context.session_state if run_context.session_state is not None else {},
                )
                _initialize_session_state(
                    run_context.session_state,
                    user_id=user_id,
                    session_id=session_id,
                    run_id=run_context.run_id,
                )

                # 3. Resolve dependencies
                if run_context.dependencies is not None:
                    await aresolve_run_dependencies(agent, run_context=run_context)

                # 4. Prepare run response
                if run_response is not None:
                    # The run is continued from a provided run_response. This contains the updated tools.
                    input = run_response.messages or []

                elif run_id is not None:
                    # The run is continued from a run_id. This requires the updated tools or requirements to be passed.
                    if updated_tools is None and requirements is None:
                        raise ValueError(
                            "Either updated tools or requirements are required to continue a run from a run_id."
                        )

                    runs = agent_session.runs or []
                    run_response = next((r for r in runs if r.run_id == run_id), None)  # type: ignore
                    if run_response is None:
                        raise RuntimeError(f"No runs found for run ID {run_id}")

                    input = run_response.messages or []

                    # If we have updated_tools, set them in the run_response
                    if updated_tools is not None:
                        run_response.tools = updated_tools

                    # If we have requirements, get the updated tools and set them in the run_response
                    elif requirements is not None:
                        run_response.requirements = requirements
                        updated_tools = [req.tool_execution for req in requirements if req.tool_execution is not None]
                        if updated_tools and run_response.tools:
                            updated_tools_map = {tool.tool_call_id: tool for tool in updated_tools}
                            run_response.tools = [
                                updated_tools_map.get(tool.tool_call_id, tool) for tool in run_response.tools
                            ]
                        else:
                            run_response.tools = updated_tools
                else:
                    raise ValueError("Either run_response or run_id must be provided.")

                run_response = cast(RunOutput, run_response)

                run_response.status = RunStatus.running

                # 5. Determine tools for model
                agent.model = cast(Model, agent.model)
                processed_tools = await agent.aget_tools(
                    run_response=run_response,
                    run_context=run_context,
                    session=agent_session,
                    user_id=user_id,
                )

                _tools = determine_tools_for_model(
                    agent,
                    model=agent.model,
                    processed_tools=processed_tools,
                    run_response=run_response,
                    run_context=run_context,
                    session=agent_session,
                    async_mode=True,
                )

                # 6. Prepare run messages
                run_messages: RunMessages = get_continue_run_messages(
                    agent,
                    input=input,
                )

                # Register run for cancellation tracking
                await aregister_run(run_response.run_id)  # type: ignore

                # Start the Run by yielding a RunContinued event
                if stream_events:
                    yield handle_event(  # type: ignore
                        create_run_continued_event(run_response),
                        run_response,
                        events_to_skip=agent.events_to_skip,  # type: ignore
                        store_events=agent.store_events,
                    )

                # 7. Handle the updated tools
                async for event in ahandle_tool_call_updates_stream(
                    agent,
                    run_response=run_response,
                    run_messages=run_messages,
                    tools=_tools,
                    stream_events=stream_events,
                ):
                    await araise_if_cancelled(run_response.run_id)  # type: ignore
                    yield event

                # 8. Process model response
                if agent.output_model is None:
                    async for event in ahandle_model_response_stream(
                        agent,
                        session=agent_session,
                        run_response=run_response,
                        run_messages=run_messages,
                        tools=_tools,
                        response_format=response_format,
                        stream_events=stream_events,
                        run_context=run_context,
                    ):
                        await araise_if_cancelled(run_response.run_id)  # type: ignore
                        yield event
                else:
                    from agno.run.agent import (
                        IntermediateRunContentEvent,
                        RunContentEvent,
                    )  # type: ignore

                    async for event in ahandle_model_response_stream(
                        agent,
                        session=agent_session,
                        run_response=run_response,
                        run_messages=run_messages,
                        tools=_tools,
                        response_format=response_format,
                        stream_events=stream_events,
                        run_context=run_context,
                    ):
                        await araise_if_cancelled(run_response.run_id)  # type: ignore
                        if isinstance(event, RunContentEvent):
                            if stream_events:
                                yield IntermediateRunContentEvent(
                                    content=event.content,
                                    content_type=event.content_type,
                                )
                        else:
                            yield event

                    # If an output model is provided, generate output using the output model
                    async for event in agenerate_response_with_output_model_stream(
                        agent,
                        session=agent_session,
                        run_response=run_response,
                        run_messages=run_messages,
                        stream_events=stream_events,
                    ):
                        await araise_if_cancelled(run_response.run_id)  # type: ignore
                        yield event  # type: ignore

                # Check for cancellation after model processing
                await araise_if_cancelled(run_response.run_id)  # type: ignore

                # Parse response with parser model if provided
                async for event in aparse_response_with_parser_model_stream(
                    agent,
                    session=agent_session,
                    run_response=run_response,
                    stream_events=stream_events,
                    run_context=run_context,
                ):
                    yield event  # type: ignore

                # Yield RunContentCompletedEvent
                if stream_events:
                    yield handle_event(  # type: ignore
                        create_run_content_completed_event(from_run_response=run_response),
                        run_response,
                        events_to_skip=agent.events_to_skip,  # type: ignore
                        store_events=agent.store_events,
                    )

                # Break out of the run function if a tool call is paused
                if any(tool_call.is_paused for tool_call in run_response.tools or []):
                    async for item in ahandle_agent_run_paused_stream(
                        agent,
                        run_response=run_response,
                        session=agent_session,
                        run_context=run_context,
                        user_id=user_id,
                        yield_run_output=yield_run_output or False,
                    ):
                        yield item
                    return

                # 8. Execute post-hooks
                if agent.post_hooks is not None:
                    async for event in aexecute_post_hooks(
                        agent,
                        hooks=agent.post_hooks,  # type: ignore
                        run_output=run_response,
                        run_context=run_context,
                        session=agent_session,
                        user_id=user_id,
                        debug_mode=debug_mode,
                        stream_events=stream_events,
                        background_tasks=background_tasks,
                        **kwargs,
                    ):
                        yield event

                # Check for cancellation before model call
                await araise_if_cancelled(run_response.run_id)  # type: ignore

                # 9. Create session summary
                if agent.session_summary_manager is not None and agent.enable_session_summaries:
                    # Upsert the RunOutput to Agent Session before creating the session summary
                    agent_session.upsert_run(run=run_response)

                    if stream_events:
                        yield handle_event(  # type: ignore
                            create_session_summary_started_event(from_run_response=run_response),
                            run_response,
                            events_to_skip=agent.events_to_skip,  # type: ignore
                            store_events=agent.store_events,
                        )
                    try:
                        await agent.session_summary_manager.acreate_session_summary(
                            session=agent_session, run_response=run_response
                        )
                    except Exception as e:
                        log_warning(f"Error in session summary creation: {str(e)}")
                    if stream_events:
                        yield handle_event(  # type: ignore
                            create_session_summary_completed_event(
                                from_run_response=run_response, session_summary=agent_session.summary
                            ),
                            run_response,
                            events_to_skip=agent.events_to_skip,  # type: ignore
                            store_events=agent.store_events,
                        )

                # Update run_response.session_state before creating RunCompletedEvent
                # This ensures the event has the final state after all tool modifications
                if agent_session.session_data is not None and "session_state" in agent_session.session_data:
                    run_response.session_state = agent_session.session_data["session_state"]

                # Create the run completed event
                completed_event = handle_event(
                    create_run_completed_event(run_response),
                    run_response,
                    events_to_skip=agent.events_to_skip,  # type: ignore
                    store_events=agent.store_events,
                )

                # Set the run status to completed
                run_response.status = RunStatus.completed

                # 10. Cleanup and store the run response and session
                await acleanup_and_store(
                    agent, run_response=run_response, session=agent_session, run_context=run_context, user_id=user_id
                )

                if stream_events:
                    yield completed_event  # type: ignore

                if yield_run_output:
                    yield run_response

                # Log Agent Telemetry
                await alog_agent_telemetry(agent, session_id=agent_session.session_id, run_id=run_response.run_id)

                log_debug(f"Agent Run End: {run_response.run_id}", center=True, symbol="*")

                break
            except RunCancelledException as e:
                if run_response is None:
                    run_response = RunOutput(run_id=run_id)
                run_response = cast(RunOutput, run_response)
                # Handle run cancellation during streaming
                log_info(f"Run {run_response.run_id if run_response.run_id else run_id} was cancelled during streaming")
                run_response.status = RunStatus.cancelled
                # Don't overwrite content - preserve any partial content that was streamed
                # Only set content if it's empty
                if not run_response.content:
                    run_response.content = str(e)

                # Yield the cancellation event
                yield handle_event(  # type: ignore
                    create_run_cancelled_event(from_run_response=run_response, reason=str(e)),
                    run_response,
                    events_to_skip=agent.events_to_skip,  # type: ignore
                    store_events=agent.store_events,
                )

                # Cleanup and store the run response and session
                if agent_session is not None:
                    await acleanup_and_store(
                        agent,
                        run_response=run_response,
                        session=agent_session,
                        run_context=run_context,
                        user_id=user_id,
                    )
                break

            except (InputCheckError, OutputCheckError) as e:
                if run_response is None:
                    run_response = RunOutput(run_id=run_id)
                run_response = cast(RunOutput, run_response)
                # Handle exceptions during async streaming
                run_response.status = RunStatus.error
                # Add error event to list of events
                run_error = create_run_error_event(
                    run_response,
                    error=str(e),
                    error_id=e.error_id,
                    error_type=e.type,
                    additional_data=e.additional_data,
                )
                run_response.events = add_error_event(error=run_error, events=run_response.events)

                # If the content is None, set it to the error message
                if run_response.content is None:
                    run_response.content = str(e)

                log_error(f"Validation failed: {str(e)} | Check trigger: {e.check_trigger}")

                # Cleanup and store the run response and session
                if agent_session is not None:
                    await acleanup_and_store(
                        agent,
                        run_response=run_response,
                        session=agent_session,
                        run_context=run_context,
                        user_id=user_id,
                    )

                # Yield the error event
                yield run_error
                break
            except KeyboardInterrupt:
                if run_response is None:
                    run_response = RunOutput(run_id=run_id)
                run_response = cast(RunOutput, run_response)
                yield handle_event(  # type: ignore
                    create_run_cancelled_event(from_run_response=run_response, reason="Operation cancelled by user"),
                    run_response,
                    events_to_skip=agent.events_to_skip,  # type: ignore
                    store_events=agent.store_events,
                )
                break

            except Exception as e:
                if run_response is None:
                    run_response = RunOutput(run_id=run_id)
                run_response = cast(RunOutput, run_response)
                # Check if this is the last attempt
                if attempt < num_attempts - 1:
                    # Calculate delay with exponential backoff if enabled
                    if agent.exponential_backoff:
                        delay = agent.delay_between_retries * (2**attempt)
                    else:
                        delay = agent.delay_between_retries

                    log_warning(f"Attempt {attempt + 1}/{num_attempts} failed: {str(e)}. Retrying in {delay}s...")
                    await asyncio.sleep(delay)
                    continue

                # Handle exceptions during async streaming
                run_response.status = RunStatus.error
                # Add error event to list of events
                run_error = create_run_error_event(run_response, error=str(e))
                run_response.events = add_error_event(error=run_error, events=run_response.events)

                # If the content is None, set it to the error message
                if run_response.content is None:
                    run_response.content = str(e)

                log_error(f"Error in Agent run: {str(e)}")

                # Cleanup and store the run response and session
                if agent_session is not None:
                    await acleanup_and_store(
                        agent,
                        run_response=run_response,
                        session=agent_session,
                        run_context=run_context,
                        user_id=user_id,
                    )

                # Yield the error event
                yield run_error
    finally:
        # Always disconnect connectable tools
        disconnect_connectable_tools(agent)
        # Always disconnect MCP tools
        await disconnect_mcp_tools(agent)

        # Always clean up the run tracking
        cleanup_run_id = run_response.run_id if run_response and run_response.run_id is not None else run_id
        if cleanup_run_id is not None:
            await acleanup_run(cleanup_run_id)


# ---------------------------------------------------------------------------
# Post-run cleanup
# ---------------------------------------------------------------------------


def save_run_response_to_file(
    agent: Agent,
    run_response: RunOutput,
    input: Optional[Union[str, List, Dict, Message]] = None,
    session_id: Optional[str] = None,
    user_id: Optional[str] = None,
) -> None:
    if agent.save_response_to_file is not None and run_response is not None:
        message_str = None
        if input is not None:
            if isinstance(input, str):
                message_str = input
            else:
                log_warning("Did not use input in output file name: input is not a string")
        try:
            from pathlib import Path

            def _sanitize(value: Any) -> str:
                """Strip path-traversal characters from format values."""
                s = str(value) if value is not None else ""
                return s.replace("/", "_").replace("\\", "_").replace("..", "_")

            fn = agent.save_response_to_file.format(
                name=_sanitize(agent.name),
                session_id=_sanitize(session_id),
                user_id=_sanitize(user_id),
                message=_sanitize(message_str),
                run_id=_sanitize(run_response.run_id),
            )
            fn_path = Path(fn)
            if not fn_path.parent.exists():
                fn_path.parent.mkdir(parents=True, exist_ok=True)
            if isinstance(run_response.content, str):
                fn_path.write_text(run_response.content)
            else:
                import json

                fn_path.write_text(json.dumps(run_response.content, indent=2))
        except Exception as e:
            log_warning(f"Failed to save output to file: {e}")


def scrub_run_output_for_storage(agent: Agent, run_response: RunOutput) -> None:
    """Scrub run output based on storage flags before persisting to database."""
    if not agent.store_media:
        scrub_media_from_run_output(run_response)

    if not agent.store_tool_messages:
        scrub_tool_results_from_run_output(run_response)

    if not agent.store_history_messages:
        scrub_history_messages_from_run_output(run_response)


def cleanup_and_store(
    agent: Agent,
    run_response: RunOutput,
    session: AgentSession,
    run_context: Optional[RunContext] = None,
    user_id: Optional[str] = None,
) -> None:
    from agno.agent import _session

    # Scrub the stored run based on storage flags
    scrub_run_output_for_storage(agent, run_response)

    # Stop the timer for the Run duration
    if run_response.metrics:
        run_response.metrics.stop_timer()

    # Update run_response.session_state before saving
    # This ensures RunOutput reflects all tool modifications
    if run_context is not None and run_context.session_state is not None:
        run_response.session_state = run_context.session_state

    # Optional: Save output to file if save_response_to_file is set
    save_run_response_to_file(
        agent,
        run_response=run_response,
        input=run_response.input.input_content_string() if run_response.input else "",
        session_id=session.session_id,
        user_id=user_id,
    )

    # Add RunOutput to Agent Session
    session.upsert_run(run=run_response)

    # Calculate session metrics
    update_session_metrics(agent, session=session, run_response=run_response)

    # Update session state before saving the session
    if run_context is not None and run_context.session_state is not None:
        if session.session_data is not None:
            session.session_data["session_state"] = run_context.session_state
        else:
            session.session_data = {"session_state": run_context.session_state}

    # Save session to memory
    _session.save_session(agent, session=session)


async def acleanup_and_store(
    agent: Agent,
    run_response: RunOutput,
    session: AgentSession,
    run_context: Optional[RunContext] = None,
    user_id: Optional[str] = None,
) -> None:
    from agno.agent import _session

    # Scrub the stored run based on storage flags
    scrub_run_output_for_storage(agent, run_response)

    # Stop the timer for the Run duration
    if run_response.metrics:
        run_response.metrics.stop_timer()

    # Update run_response.session_state before saving
    # This ensures RunOutput reflects all tool modifications
    if run_context is not None and run_context.session_state is not None:
        run_response.session_state = run_context.session_state

    # Optional: Save output to file if save_response_to_file is set
    save_run_response_to_file(
        agent,
        run_response=run_response,
        input=run_response.input.input_content_string() if run_response.input else "",
        session_id=session.session_id,
        user_id=user_id,
    )

    # Add RunOutput to Agent Session
    session.upsert_run(run=run_response)

    # Calculate session metrics
    update_session_metrics(agent, session=session, run_response=run_response)

    # Update session state before saving the session
    if run_context is not None and run_context.session_state is not None:
        if session.session_data is not None:
            session.session_data["session_state"] = run_context.session_state
        else:
            session.session_data = {"session_state": run_context.session_state}

    # Save session to memory
    await _session.asave_session(agent, session=session)


# ---------------------------------------------------------------------------
# Run cancellation — re-export from agno.run.cancel
# ---------------------------------------------------------------------------

cancel_run = cancel_run_global
acancel_run = acancel_run_global
