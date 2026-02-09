"""Pre/post hooks and pause handling for Agent."""

from __future__ import annotations

from inspect import iscoroutinefunction
from typing import (
    TYPE_CHECKING,
    Any,
    AsyncIterator,
    Callable,
    Iterator,
    List,
    Optional,
)

if TYPE_CHECKING:
    from agno.agent.agent import Agent

from agno.exceptions import InputCheckError, OutputCheckError
from agno.run import RunContext, RunStatus
from agno.run.agent import RunInput, RunOutput, RunOutputEvent
from agno.session import AgentSession
from agno.utils.events import (
    create_post_hook_completed_event,
    create_post_hook_started_event,
    create_pre_hook_completed_event,
    create_pre_hook_started_event,
    create_run_paused_event,
    handle_event,
)
from agno.utils.hooks import (
    copy_args_for_background,
    filter_hook_args,
    should_run_hook_in_background,
)
from agno.utils.log import (
    log_debug,
    log_error,
    log_exception,
)
from agno.utils.response import get_paused_content

# ---------------------------------------------------------------------------
# Pre/Post Hooks
# ---------------------------------------------------------------------------


def execute_pre_hooks(
    agent: Agent,
    hooks: Optional[List[Callable[..., Any]]],
    run_response: RunOutput,
    run_input: RunInput,
    session: AgentSession,
    run_context: RunContext,
    user_id: Optional[str] = None,
    debug_mode: Optional[bool] = None,
    stream_events: bool = False,
    background_tasks: Optional[Any] = None,
    **kwargs: Any,
) -> Iterator[RunOutputEvent]:
    """Execute multiple pre-hook functions in succession."""
    if hooks is None:
        return
    # Prepare arguments for this hook
    all_args = {
        "run_input": run_input,
        "run_context": run_context,
        "agent": agent,
        "session": session,
        "user_id": user_id,
        "debug_mode": debug_mode or agent.debug_mode,
    }

    # Check if background_tasks is available and ALL hooks should run in background
    # Note: Pre-hooks running in background may not be able to modify run_input
    if agent._run_hooks_in_background is True and background_tasks is not None:
        # Schedule ALL pre_hooks as background tasks
        # Copy args to prevent race conditions
        bg_args = copy_args_for_background(all_args)
        for hook in hooks:
            # Filter arguments to only include those that the hook accepts
            filtered_args = filter_hook_args(hook, bg_args)

            # Add to background tasks
            background_tasks.add_task(hook, **filtered_args)
        return

    all_args.update(kwargs)

    for i, hook in enumerate(hooks):
        # Check if this specific hook should run in background (via @hook decorator)
        if should_run_hook_in_background(hook) and background_tasks is not None:
            # Copy args to prevent race conditions
            bg_args = copy_args_for_background(all_args)
            filtered_args = filter_hook_args(hook, bg_args)
            background_tasks.add_task(hook, **filtered_args)
            continue

        if stream_events:
            yield handle_event(  # type: ignore
                run_response=run_response,
                event=create_pre_hook_started_event(
                    from_run_response=run_response,
                    run_input=run_input,
                    pre_hook_name=hook.__name__,
                ),
                events_to_skip=agent.events_to_skip,  # type: ignore
                store_events=agent.store_events,
            )
        try:
            # Filter arguments to only include those that the hook accepts
            filtered_args = filter_hook_args(hook, all_args)

            hook(**filtered_args)

            if stream_events:
                yield handle_event(  # type: ignore
                    run_response=run_response,
                    event=create_pre_hook_completed_event(
                        from_run_response=run_response,
                        run_input=run_input,
                        pre_hook_name=hook.__name__,
                    ),
                    events_to_skip=agent.events_to_skip,  # type: ignore
                    store_events=agent.store_events,
                )

        except (InputCheckError, OutputCheckError) as e:
            raise e
        except Exception as e:
            log_error(f"Pre-hook #{i + 1} execution failed: {str(e)}")
            log_exception(e)
        finally:
            # Reset global log mode incase an agent in the pre-hook changed it
            agent._set_debug(debug_mode=debug_mode)

    # Update the input on the run_response
    run_response.input = run_input


async def aexecute_pre_hooks(
    agent: Agent,
    hooks: Optional[List[Callable[..., Any]]],
    run_response: RunOutput,
    run_input: RunInput,
    run_context: RunContext,
    session: AgentSession,
    user_id: Optional[str] = None,
    debug_mode: Optional[bool] = None,
    stream_events: bool = False,
    background_tasks: Optional[Any] = None,
    **kwargs: Any,
) -> AsyncIterator[RunOutputEvent]:
    """Execute multiple pre-hook functions in succession (async version)."""
    if hooks is None:
        return
    # Prepare arguments for this hook
    all_args = {
        "run_input": run_input,
        "agent": agent,
        "session": session,
        "run_context": run_context,
        "user_id": user_id,
        "debug_mode": debug_mode or agent.debug_mode,
    }

    # Check if background_tasks is available and ALL hooks should run in background
    # Note: Pre-hooks running in background may not be able to modify run_input
    if agent._run_hooks_in_background is True and background_tasks is not None:
        # Schedule ALL pre_hooks as background tasks
        # Copy args to prevent race conditions
        bg_args = copy_args_for_background(all_args)
        for hook in hooks:
            # Filter arguments to only include those that the hook accepts
            filtered_args = filter_hook_args(hook, bg_args)

            # Add to background tasks (both sync and async hooks supported)
            background_tasks.add_task(hook, **filtered_args)
        return

    all_args.update(kwargs)

    for i, hook in enumerate(hooks):
        # Check if this specific hook should run in background (via @hook decorator)
        if should_run_hook_in_background(hook) and background_tasks is not None:
            # Copy args to prevent race conditions
            bg_args = copy_args_for_background(all_args)
            filtered_args = filter_hook_args(hook, bg_args)
            background_tasks.add_task(hook, **filtered_args)
            continue

        if stream_events:
            yield handle_event(  # type: ignore
                run_response=run_response,
                event=create_pre_hook_started_event(
                    from_run_response=run_response,
                    run_input=run_input,
                    pre_hook_name=hook.__name__,
                ),
                events_to_skip=agent.events_to_skip,  # type: ignore
                store_events=agent.store_events,
            )
        try:
            # Filter arguments to only include those that the hook accepts
            filtered_args = filter_hook_args(hook, all_args)

            if iscoroutinefunction(hook):
                await hook(**filtered_args)
            else:
                # Synchronous function
                hook(**filtered_args)

            if stream_events:
                yield handle_event(  # type: ignore
                    run_response=run_response,
                    event=create_pre_hook_completed_event(
                        from_run_response=run_response,
                        run_input=run_input,
                        pre_hook_name=hook.__name__,
                    ),
                    events_to_skip=agent.events_to_skip,  # type: ignore
                    store_events=agent.store_events,
                )

        except (InputCheckError, OutputCheckError) as e:
            raise e
        except Exception as e:
            log_error(f"Pre-hook #{i + 1} execution failed: {str(e)}")
            log_exception(e)
        finally:
            # Reset global log mode incase an agent in the pre-hook changed it
            agent._set_debug(debug_mode=debug_mode)

    # Update the input on the run_response
    run_response.input = run_input


def execute_post_hooks(
    agent: Agent,
    hooks: Optional[List[Callable[..., Any]]],
    run_output: RunOutput,
    session: AgentSession,
    run_context: RunContext,
    user_id: Optional[str] = None,
    debug_mode: Optional[bool] = None,
    stream_events: bool = False,
    background_tasks: Optional[Any] = None,
    **kwargs: Any,
) -> Iterator[RunOutputEvent]:
    """Execute multiple post-hook functions in succession."""
    if hooks is None:
        return

    # Prepare arguments for this hook
    all_args = {
        "run_output": run_output,
        "agent": agent,
        "session": session,
        "user_id": user_id,
        "run_context": run_context,
        "debug_mode": debug_mode or agent.debug_mode,
    }

    # Check if background_tasks is available and ALL hooks should run in background
    if agent._run_hooks_in_background is True and background_tasks is not None:
        # Schedule ALL post_hooks as background tasks
        # Copy args to prevent race conditions
        bg_args = copy_args_for_background(all_args)
        for hook in hooks:
            # Filter arguments to only include those that the hook accepts
            filtered_args = filter_hook_args(hook, bg_args)

            # Add to background tasks
            background_tasks.add_task(hook, **filtered_args)
        return

    all_args.update(kwargs)

    for i, hook in enumerate(hooks):
        # Check if this specific hook should run in background (via @hook decorator)
        if should_run_hook_in_background(hook) and background_tasks is not None:
            # Copy args to prevent race conditions
            bg_args = copy_args_for_background(all_args)
            filtered_args = filter_hook_args(hook, bg_args)
            background_tasks.add_task(hook, **filtered_args)
            continue

        if stream_events:
            yield handle_event(  # type: ignore
                run_response=run_output,
                event=create_post_hook_started_event(
                    from_run_response=run_output,
                    post_hook_name=hook.__name__,
                ),
                events_to_skip=agent.events_to_skip,  # type: ignore
                store_events=agent.store_events,
            )
        try:
            # Filter arguments to only include those that the hook accepts
            filtered_args = filter_hook_args(hook, all_args)

            hook(**filtered_args)

            if stream_events:
                yield handle_event(  # type: ignore
                    run_response=run_output,
                    event=create_post_hook_completed_event(
                        from_run_response=run_output,
                        post_hook_name=hook.__name__,
                    ),
                    events_to_skip=agent.events_to_skip,  # type: ignore
                    store_events=agent.store_events,
                )
        except (InputCheckError, OutputCheckError) as e:
            raise e
        except Exception as e:
            log_error(f"Post-hook #{i + 1} execution failed: {str(e)}")
            log_exception(e)
        finally:
            # Reset global log mode incase an agent in the pre-hook changed it
            agent._set_debug(debug_mode=debug_mode)


async def aexecute_post_hooks(
    agent: Agent,
    hooks: Optional[List[Callable[..., Any]]],
    run_output: RunOutput,
    run_context: RunContext,
    session: AgentSession,
    user_id: Optional[str] = None,
    debug_mode: Optional[bool] = None,
    stream_events: bool = False,
    background_tasks: Optional[Any] = None,
    **kwargs: Any,
) -> AsyncIterator[RunOutputEvent]:
    """Execute multiple post-hook functions in succession (async version)."""
    if hooks is None:
        return

    # Prepare arguments for this hook
    all_args = {
        "run_output": run_output,
        "agent": agent,
        "session": session,
        "run_context": run_context,
        "user_id": user_id,
        "debug_mode": debug_mode or agent.debug_mode,
    }
    # Check if background_tasks is available and ALL hooks should run in background
    if agent._run_hooks_in_background is True and background_tasks is not None:
        # Copy args to prevent race conditions
        bg_args = copy_args_for_background(all_args)
        for hook in hooks:
            # Filter arguments to only include those that the hook accepts
            filtered_args = filter_hook_args(hook, bg_args)

            # Add to background tasks (both sync and async hooks supported)
            background_tasks.add_task(hook, **filtered_args)
        return

    all_args.update(kwargs)

    for i, hook in enumerate(hooks):
        # Check if this specific hook should run in background (via @hook decorator)
        if should_run_hook_in_background(hook) and background_tasks is not None:
            # Copy args to prevent race conditions
            bg_args = copy_args_for_background(all_args)
            filtered_args = filter_hook_args(hook, bg_args)
            background_tasks.add_task(hook, **filtered_args)
            continue

        if stream_events:
            yield handle_event(  # type: ignore
                run_response=run_output,
                event=create_post_hook_started_event(
                    from_run_response=run_output,
                    post_hook_name=hook.__name__,
                ),
                events_to_skip=agent.events_to_skip,  # type: ignore
                store_events=agent.store_events,
            )
        try:
            # Filter arguments to only include those that the hook accepts
            filtered_args = filter_hook_args(hook, all_args)
            if iscoroutinefunction(hook):
                await hook(**filtered_args)
            else:
                hook(**filtered_args)

            if stream_events:
                yield handle_event(  # type: ignore
                    run_response=run_output,
                    event=create_post_hook_completed_event(
                        from_run_response=run_output,
                        post_hook_name=hook.__name__,
                    ),
                    events_to_skip=agent.events_to_skip,  # type: ignore
                    store_events=agent.store_events,
                )

        except (InputCheckError, OutputCheckError) as e:
            raise e
        except Exception as e:
            log_error(f"Post-hook #{i + 1} execution failed: {str(e)}")
            log_exception(e)
        finally:
            # Reset global log mode incase an agent in the pre-hook changed it
            agent._set_debug(debug_mode=debug_mode)


# ---------------------------------------------------------------------------
# Pause Handling
# ---------------------------------------------------------------------------


def handle_agent_run_paused(
    agent: Agent,
    run_response: RunOutput,
    session: AgentSession,
    user_id: Optional[str] = None,
) -> RunOutput:
    from agno.agent import _storage

    # Set the run response to paused

    run_response.status = RunStatus.paused
    if not run_response.content:
        run_response.content = get_paused_content(run_response)

    _storage.cleanup_and_store(agent, run_response=run_response, session=session, user_id=user_id)

    log_debug(f"Agent Run Paused: {run_response.run_id}", center=True, symbol="*")

    # We return and await confirmation/completion for the tools that require it
    return run_response


def handle_agent_run_paused_stream(
    agent: Agent,
    run_response: RunOutput,
    session: AgentSession,
    user_id: Optional[str] = None,
) -> Iterator[RunOutputEvent]:
    from agno.agent import _storage

    # Set the run response to paused

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

    _storage.cleanup_and_store(agent, run_response=run_response, session=session, user_id=user_id)

    yield pause_event  # type: ignore

    log_debug(f"Agent Run Paused: {run_response.run_id}", center=True, symbol="*")


async def ahandle_agent_run_paused(
    agent: Agent,
    run_response: RunOutput,
    session: AgentSession,
    user_id: Optional[str] = None,
) -> RunOutput:
    from agno.agent import _storage

    # Set the run response to paused

    run_response.status = RunStatus.paused
    if not run_response.content:
        run_response.content = get_paused_content(run_response)

    await _storage.acleanup_and_store(agent, run_response=run_response, session=session, user_id=user_id)

    log_debug(f"Agent Run Paused: {run_response.run_id}", center=True, symbol="*")

    # We return and await confirmation/completion for the tools that require it
    return run_response


async def ahandle_agent_run_paused_stream(
    agent: Agent,
    run_response: RunOutput,
    session: AgentSession,
    user_id: Optional[str] = None,
) -> AsyncIterator[RunOutputEvent]:
    from agno.agent import _storage

    # Set the run response to paused

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

    await _storage.acleanup_and_store(agent, run_response=run_response, session=session, user_id=user_id)

    yield pause_event  # type: ignore

    log_debug(f"Agent Run Paused: {run_response.run_id}", center=True, symbol="*")
