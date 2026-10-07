"""Run path for agents whose `model` is a DecisionModel.

A decision model answers the fields of `output_schema` as typed questions in one request. There is no message
loop, tool calling or text generation, so this path skips those steps and reuses the session, hook, cancellation
and storage helpers of the chat run path.
"""

from __future__ import annotations

import asyncio
import time
from collections import deque
from typing import TYPE_CHECKING, Any, AsyncIterator, Iterator, Optional, Type, Union, cast

from pydantic import BaseModel

from agno.exceptions import InputCheckError, OutputCheckError, RunCancelledException
from agno.metrics import MessageMetrics, ModelType, accumulate_model_metrics
from agno.models.decision.base import DecisionModel
from agno.models.decision.schema import build_output, plan_schema, questions_from_schema
from agno.models.decision.types import DecisionResult, State
from agno.models.message import Message
from agno.models.response import ModelResponse
from agno.run import RunContext, RunStatus
from agno.run.agent import RunInput, RunOutput, RunOutputEvent
from agno.run.cancel import (
    acleanup_run,
    araise_if_cancelled,
    aregister_run,
    cleanup_run,
    raise_if_cancelled,
    register_run,
)
from agno.session import AgentSession
from agno.utils.events import (
    add_error_event,
    create_run_completed_event,
    create_run_error_event,
    create_run_output_content_event,
    create_run_started_event,
    error_type_of,
    handle_event,
)
from agno.utils.log import log_debug, log_error, log_warning

if TYPE_CHECKING:
    from agno.agent.agent import Agent


def is_decision_agent(agent: "Agent") -> bool:
    return isinstance(agent.model, DecisionModel)


def validate_decision_agent(agent: "Agent", output_schema: Optional[Any], require_schema: bool = True) -> None:
    """Raise ValueError when an agent's settings need a chat model.

    Runs at construction, where the schema may still arrive per run, and again at each run with the run's schema.
    """
    name = type(agent.model).__name__
    if output_schema is None:
        if require_schema:
            raise ValueError(f"{name} is a decision model, so the agent needs an `output_schema` to fill")
    else:
        plan_schema(output_schema)

    unsupported = {
        "tools": bool(agent.tools),
        "knowledge": agent.knowledge is not None and agent.search_knowledge,
        "skills": agent.skills is not None,
        "reasoning_model": agent.reasoning_model is not None or agent.reasoning_agent is not None,
        "parser_model": agent.parser_model is not None,
        "output_model": agent.output_model is not None,
        "fallback_config": agent.fallback_config is not None,
        "learning": bool(agent.learning),
        "introduction": agent.introduction is not None,
        "memory": agent.update_memory_on_run or agent.enable_agentic_memory or agent.memory_manager is not None,
        "session summaries": agent.enable_session_summaries or agent.session_summary_manager is not None,
        "compression": agent.compress_tool_results or agent.compression_manager is not None,
        "followups": agent.followups,
        "add_history_to_context": agent.add_history_to_context,
    }
    for setting, used in unsupported.items():
        if used:
            raise ValueError(f"{name} is a decision model and does not support `{setting}`")


def reject_media(**media: Any) -> None:
    """Decision models read only the text or structured input, so attachments would be silently ignored."""
    attached = [kind for kind, value in media.items() if value]
    if attached:
        raise ValueError(f"Decision models do not accept {', '.join(attached)}; pass the content as text instead")


# ---------------------------------------------------------------------------
# Entry points
# ---------------------------------------------------------------------------


def run_decision(agent: "Agent", run_response: RunOutput, **kwargs: Any) -> RunOutput:
    deque(_decision_events(agent, run_response, stream=False, **kwargs), maxlen=0)
    return run_response


def run_decision_stream(
    agent: "Agent", run_response: RunOutput, **kwargs: Any
) -> Iterator[Union[RunOutputEvent, RunOutput]]:
    yield from _decision_events(agent, run_response, stream=True, **kwargs)


async def arun_decision(agent: "Agent", run_response: RunOutput, **kwargs: Any) -> RunOutput:
    async for _ in _adecision_events(agent, run_response, stream=False, **kwargs):
        pass
    return run_response


async def arun_decision_stream(
    agent: "Agent", run_response: RunOutput, **kwargs: Any
) -> AsyncIterator[Union[RunOutputEvent, RunOutput]]:
    async for event in _adecision_events(agent, run_response, stream=True, **kwargs):
        yield event


# ---------------------------------------------------------------------------
# Run loop
# ---------------------------------------------------------------------------


def _decision_events(
    agent: "Agent",
    run_response: RunOutput,
    run_context: RunContext,
    session_id: str,
    user_id: Optional[str] = None,
    *,
    stream: bool,
    stream_events: bool = False,
    yield_run_output: bool = False,
    debug_mode: Optional[bool] = None,
    background_tasks: Optional[Any] = None,
    pre_session: Optional[AgentSession] = None,
    **kwargs: Any,
) -> Iterator[Union[RunOutputEvent, RunOutput]]:
    from agno.agent._hooks import execute_post_hooks, execute_pre_hooks
    from agno.agent._init import _initialize_session_state
    from agno.agent._run import (
        _build_cancel_terminal_events,
        _handle_run_cancellation,
        cleanup_and_store,
        resolve_run_dependencies,
    )
    from agno.agent._storage import load_session_state, read_or_create_session, update_metadata
    from agno.agent._telemetry import log_agent_telemetry

    model = cast(DecisionModel, agent.model)
    register_run(run_context.run_id)
    log_debug(f"Agent Decision Run Start: {run_response.run_id}", center=True)
    agent_session: Optional[AgentSession] = None

    try:
        num_attempts = agent.retries + 1
        for attempt in range(num_attempts):
            try:
                if attempt == 0 and pre_session is not None:
                    agent_session = pre_session
                else:
                    agent_session = read_or_create_session(agent, session_id=session_id, user_id=user_id)
                    update_metadata(agent, session=agent_session)
                run_context.session_state = load_session_state(
                    agent,
                    session=agent_session,
                    session_state=run_context.session_state if run_context.session_state is not None else {},
                )
                _initialize_session_state(
                    run_context.session_state, user_id=user_id, session_id=session_id, run_id=run_context.run_id
                )
                if run_context.dependencies is not None:
                    resolve_run_dependencies(
                        agent, run_context=run_context, run_input=run_response.input, session=agent_session
                    )
                raise_if_cancelled(run_response.run_id)  # type: ignore

                run_input = cast(RunInput, run_response.input)
                if agent.pre_hooks is not None:
                    deque(
                        execute_pre_hooks(
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
                        ),
                        maxlen=0,
                    )

                if stream and stream_events:
                    yield _event(agent, run_response, create_run_started_event(run_response))

                schema = _schema(run_context)
                result = model.decide(state_from_input(run_input), questions_from_schema(schema))
                raise_if_cancelled(run_response.run_id)  # type: ignore
                _apply_result(model, run_response, run_input, schema, result)

                if stream:
                    yield _content_event(agent, run_response)

                if agent.post_hooks is not None:
                    deque(
                        execute_post_hooks(
                            agent,
                            hooks=agent.post_hooks,  # type: ignore
                            run_output=run_response,
                            run_context=run_context,
                            session=agent_session,
                            user_id=user_id,
                            debug_mode=debug_mode,
                            background_tasks=background_tasks,
                            **kwargs,
                        ),
                        maxlen=0,
                    )
                raise_if_cancelled(run_response.run_id)  # type: ignore

                completed_event = (
                    _event(agent, run_response, create_run_completed_event(from_run_response=run_response))
                    if stream and stream_events
                    else None
                )
                run_response.status = RunStatus.completed
                cleanup_and_store(
                    agent, run_response=run_response, session=agent_session, run_context=run_context, user_id=user_id
                )
                if completed_event is not None:
                    yield completed_event
                if stream and yield_run_output:
                    yield run_response

                log_agent_telemetry(agent, session_id=agent_session.session_id, run_id=run_response.run_id)
                log_debug(f"Agent Decision Run End: {run_response.run_id}", center=True, symbol="*")
                return

            except (RunCancelledException, KeyboardInterrupt) as e:
                cancel_error = e if isinstance(e, RunCancelledException) else KeyboardInterrupt()
                run_response = _handle_run_cancellation(run_response, cancel_error)
                terminal_events = _build_cancel_terminal_events(
                    agent, run_response, error=cancel_error, run_context=run_context
                )
                try:
                    if agent_session is not None:
                        cleanup_and_store(
                            agent,
                            run_response=run_response,
                            session=agent_session,
                            run_context=run_context,
                            user_id=user_id,
                        )
                except Exception as store_err:
                    log_warning(f"Failed to persist cancelled run: {store_err}")
                if stream:
                    yield from terminal_events
                    if yield_run_output:
                        yield run_response
                return

            except Exception as e:
                is_check_error = isinstance(e, (InputCheckError, OutputCheckError))
                if not is_check_error and attempt < num_attempts - 1:
                    delay = _retry_delay(agent, attempt)
                    log_warning(f"Attempt {attempt + 1}/{num_attempts} failed. Retrying in {delay}s...: {e}")
                    time.sleep(delay)
                    continue
                run_error = _record_error(run_response, e, stream=stream)
                if agent_session is not None:
                    cleanup_and_store(
                        agent,
                        run_response=run_response,
                        session=agent_session,
                        run_context=run_context,
                        user_id=user_id,
                    )
                if stream:
                    yield run_error
                return
    finally:
        cleanup_run(run_response.run_id)  # type: ignore


async def _adecision_events(
    agent: "Agent",
    run_response: RunOutput,
    run_context: RunContext,
    session_id: str,
    user_id: Optional[str] = None,
    *,
    stream: bool,
    stream_events: bool = False,
    yield_run_output: bool = False,
    debug_mode: Optional[bool] = None,
    background_tasks: Optional[Any] = None,
    pre_session: Optional[AgentSession] = None,
    **kwargs: Any,
) -> AsyncIterator[Union[RunOutputEvent, RunOutput]]:
    from agno.agent._hooks import aexecute_post_hooks, aexecute_pre_hooks
    from agno.agent._init import _initialize_session_state
    from agno.agent._run import (
        _build_cancel_terminal_events,
        _handle_run_cancellation,
        _persist_cancelled_run_in_background,
        acleanup_and_store,
        aresolve_run_dependencies,
    )
    from agno.agent._storage import aread_or_create_session, load_session_state, update_metadata
    from agno.agent._telemetry import alog_agent_telemetry

    model = cast(DecisionModel, agent.model)
    await aregister_run(run_context.run_id)
    log_debug(f"Agent Decision Run Start: {run_response.run_id}", center=True)
    agent_session: Optional[AgentSession] = None

    try:
        num_attempts = agent.retries + 1
        for attempt in range(num_attempts):
            try:
                if attempt == 0 and pre_session is not None:
                    agent_session = pre_session
                else:
                    agent_session = await aread_or_create_session(agent, session_id=session_id, user_id=user_id)
                    update_metadata(agent, session=agent_session)
                run_context.session_state = load_session_state(
                    agent,
                    session=agent_session,
                    session_state=run_context.session_state if run_context.session_state is not None else {},
                )
                _initialize_session_state(
                    run_context.session_state, user_id=user_id, session_id=session_id, run_id=run_context.run_id
                )
                if run_context.dependencies is not None:
                    await aresolve_run_dependencies(
                        agent, run_context=run_context, run_input=run_response.input, session=agent_session
                    )
                await araise_if_cancelled(run_response.run_id)  # type: ignore

                run_input = cast(RunInput, run_response.input)
                if agent.pre_hooks is not None:
                    async for _ in aexecute_pre_hooks(
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
                    ):
                        pass

                if stream and stream_events:
                    yield _event(agent, run_response, create_run_started_event(run_response))

                schema = _schema(run_context)
                result = await model.adecide(state_from_input(run_input), questions_from_schema(schema))
                await araise_if_cancelled(run_response.run_id)  # type: ignore
                _apply_result(model, run_response, run_input, schema, result)

                if stream:
                    yield _content_event(agent, run_response)

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
                await araise_if_cancelled(run_response.run_id)  # type: ignore

                completed_event = (
                    _event(agent, run_response, create_run_completed_event(from_run_response=run_response))
                    if stream and stream_events
                    else None
                )
                run_response.status = RunStatus.completed
                await acleanup_and_store(
                    agent, run_response=run_response, session=agent_session, run_context=run_context, user_id=user_id
                )
                if completed_event is not None:
                    yield completed_event
                if stream and yield_run_output:
                    yield run_response

                await alog_agent_telemetry(agent, session_id=agent_session.session_id, run_id=run_response.run_id)
                log_debug(f"Agent Decision Run End: {run_response.run_id}", center=True, symbol="*")
                return

            except (RunCancelledException, KeyboardInterrupt, asyncio.CancelledError) as e:
                cancel_error = e if isinstance(e, RunCancelledException) else KeyboardInterrupt()
                run_response = _handle_run_cancellation(run_response, cancel_error)
                terminal_events = _build_cancel_terminal_events(
                    agent, run_response, error=cancel_error, run_context=run_context
                )
                if agent_session is not None:
                    if isinstance(e, asyncio.CancelledError):
                        # Client disconnect: persist on a detached task so the cancel scope can't abort the write
                        _persist_cancelled_run_in_background(
                            agent,
                            run_response=run_response,
                            session=agent_session,
                            run_context=run_context,
                            user_id=user_id,
                        )
                    else:
                        try:
                            await acleanup_and_store(
                                agent,
                                run_response=run_response,
                                session=agent_session,
                                run_context=run_context,
                                user_id=user_id,
                            )
                        except Exception as store_err:
                            log_warning(f"Failed to persist cancelled run: {store_err}")
                if isinstance(e, asyncio.CancelledError):
                    raise
                if stream:
                    for terminal_event in terminal_events:
                        yield terminal_event
                    if yield_run_output:
                        yield run_response
                return

            except Exception as e:
                is_check_error = isinstance(e, (InputCheckError, OutputCheckError))
                if not is_check_error and attempt < num_attempts - 1:
                    delay = _retry_delay(agent, attempt)
                    log_warning(f"Attempt {attempt + 1}/{num_attempts} failed. Retrying in {delay}s...: {e}")
                    await asyncio.sleep(delay)
                    continue
                run_error = _record_error(run_response, e, stream=stream)
                if agent_session is not None:
                    await acleanup_and_store(
                        agent,
                        run_response=run_response,
                        session=agent_session,
                        run_context=run_context,
                        user_id=user_id,
                    )
                if stream:
                    yield run_error
                return
    finally:
        await acleanup_run(run_response.run_id)  # type: ignore


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def state_from_input(run_input: RunInput) -> State:
    """The decision `state` for a run's input: text stays text, structured input becomes a dict."""
    content = run_input.input_content
    if isinstance(content, str):
        return content
    if isinstance(content, BaseModel):
        return content.model_dump(mode="json")
    if isinstance(content, dict):
        return content
    if isinstance(content, Message):
        return content.get_content_string()
    if isinstance(content, list) and all(isinstance(item, str) for item in content):
        return list(content)
    return run_input.input_content_string()


def _schema(run_context: RunContext) -> Type[BaseModel]:
    schema = run_context.output_schema
    if not (isinstance(schema, type) and issubclass(schema, BaseModel)):
        raise ValueError("A decision model needs `output_schema` to be a pydantic BaseModel class")
    return schema


def _apply_result(
    model: DecisionModel,
    run_response: RunOutput,
    run_input: RunInput,
    schema: Type[BaseModel],
    result: DecisionResult,
) -> None:
    content = build_output(schema, result)
    run_response.content = content
    run_response.content_type = schema.__name__
    run_response.decisions = dict(result.answers)
    run_response.messages = [
        Message(role="user", content=run_input.input_content_string()),
        Message(role="assistant", content=content.model_dump_json(), metrics=result.metrics or MessageMetrics()),
    ]
    if result.metrics is not None:
        accumulate_model_metrics(
            ModelResponse(response_usage=result.metrics), model, ModelType.MODEL, run_response.metrics
        )


def _event(agent: "Agent", run_response: RunOutput, event: RunOutputEvent) -> RunOutputEvent:
    return handle_event(  # type: ignore
        event,
        run_response,
        events_to_skip=agent.events_to_skip,  # type: ignore
        store_events=agent.store_events,
    )


def _content_event(agent: "Agent", run_response: RunOutput) -> RunOutputEvent:
    return _event(
        agent,
        run_response,
        create_run_output_content_event(
            from_run_response=run_response,
            content=run_response.content,
            content_type=run_response.content_type,
        ),
    )


def _record_error(run_response: RunOutput, error: Exception, stream: bool) -> RunOutputEvent:
    run_response.status = RunStatus.error
    if isinstance(error, (InputCheckError, OutputCheckError)):
        run_error = create_run_error_event(
            run_response,
            error=str(error),
            error_id=error.error_id,
            error_type=error.type,
            additional_data=error.additional_data,
        )
        log_error(f"Validation failed: {error} | Check trigger: {error.check_trigger}")
    else:
        run_error = create_run_error_event(run_response, error=str(error), error_type=error_type_of(error))
        log_error(f"Error in Agent run: {error}")
    if stream:
        run_response.events = add_error_event(error=run_error, events=run_response.events)
    if run_response.content is None:
        run_response.content = str(error)
    return run_error


def _retry_delay(agent: "Agent", attempt: int) -> float:
    if agent.exponential_backoff:
        return agent.delay_between_retries * (2**attempt)
    return agent.delay_between_retries
