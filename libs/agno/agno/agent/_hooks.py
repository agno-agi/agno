"""Pre/post hooks for Agent."""

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
from agno.run import RunContext
from agno.run.agent import RunInput, RunOutput, RunOutputEvent
from agno.session import AgentSession
from agno.utils.events import (
    create_post_hook_completed_event,
    create_post_hook_started_event,
    create_pre_hook_completed_event,
    create_pre_hook_started_event,
    handle_event,
)
from agno.utils.hooks import (
    copy_args_for_background,
    filter_hook_args,
    is_guardrail_hook,
    should_run_hook_in_background,
)
from agno.utils.log import (
    log_error,
    log_exception,
    log_warning,
)


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
    from agno.agent._init import set_debug

    if hooks is None:
        return
    # Prepare arguments for this hook
    all_args = {
        "run_input": run_input,
        "run_context": run_context,
        "agent": agent,
        "session": session,
        "user_id": user_id,
        "debug_mode": debug_mode if debug_mode is not None else agent.debug_mode,
        "metadata": run_context.metadata if run_context else None,
    }

    all_args.update(kwargs)

    # Global background mode: run guardrails synchronously, buffer everything else.
    # Guardrails MUST block so InputCheckError/OutputCheckError can propagate.
    # Non-guardrail hooks are buffered and only queued after ALL guardrails pass —
    # this prevents side-effects (logging, webhooks) from firing on rejected input.
    # deepcopy runs AFTER the guardrail loop so mutations (e.g. PII masking) propagate.
    if agent._run_hooks_in_background is True and background_tasks is not None:
        pending_bg_hooks = []
        for hook in hooks:
            if is_guardrail_hook(hook):
                filtered_args = filter_hook_args(hook, all_args)
                try:
                    hook(**filtered_args)
                except (InputCheckError, OutputCheckError):
                    raise
                except Exception as e:
                    log_error(f"Background guardrail '{hook.__name__}' execution failed: {str(e)}")
                    log_exception(e)
            else:
                pending_bg_hooks.append(hook)
        bg_args = copy_args_for_background(all_args)
        for hook in pending_bg_hooks:
            filtered_args = filter_hook_args(hook, bg_args)
            background_tasks.add_task(hook, **filtered_args)
        return

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
                log_warning(
                    f"Async hook '{hook.__name__}' cannot be used with sync run(). Use arun() instead. Skipping hook."
                )
                continue

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
            set_debug(agent, debug_mode=debug_mode)

    # Update the input on the run_response
    run_response.input = run_input


async def aexecute_pre_hooks(
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
) -> AsyncIterator[RunOutputEvent]:
    """Execute multiple pre-hook functions in succession (async version)."""
    from agno.agent._init import set_debug

    if hooks is None:
        return
    # Prepare arguments for this hook
    all_args = {
        "run_input": run_input,
        "agent": agent,
        "session": session,
        "run_context": run_context,
        "user_id": user_id,
        "debug_mode": debug_mode if debug_mode is not None else agent.debug_mode,
        "metadata": run_context.metadata if run_context else None,
    }

    all_args.update(kwargs)

    # Global background mode — see execute_pre_hooks for pattern explanation.
    if agent._run_hooks_in_background is True and background_tasks is not None:
        pending_bg_hooks = []
        for hook in hooks:
            if is_guardrail_hook(hook):
                filtered_args = filter_hook_args(hook, all_args)
                try:
                    if iscoroutinefunction(hook):
                        await hook(**filtered_args)
                    else:
                        hook(**filtered_args)
                except (InputCheckError, OutputCheckError):
                    raise
                except Exception as e:
                    log_error(f"Background guardrail '{hook.__name__}' execution failed: {str(e)}")
                    log_exception(e)
            else:
                pending_bg_hooks.append(hook)
        bg_args = copy_args_for_background(all_args)
        for hook in pending_bg_hooks:
            filtered_args = filter_hook_args(hook, bg_args)
            background_tasks.add_task(hook, **filtered_args)
        return

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
            set_debug(agent, debug_mode=debug_mode)

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
    from agno.agent._init import set_debug

    if hooks is None:
        return

    # Prepare arguments for this hook
    all_args = {
        "run_output": run_output,
        "agent": agent,
        "session": session,
        "user_id": user_id,
        "run_context": run_context,
        "debug_mode": debug_mode if debug_mode is not None else agent.debug_mode,
        "metadata": run_context.metadata if run_context else None,
    }

    all_args.update(kwargs)

    # Global background mode — see execute_pre_hooks for pattern explanation.
    if agent._run_hooks_in_background is True and background_tasks is not None:
        pending_bg_hooks = []
        for hook in hooks:
            if is_guardrail_hook(hook):
                filtered_args = filter_hook_args(hook, all_args)
                try:
                    hook(**filtered_args)
                except (InputCheckError, OutputCheckError):
                    raise
                except Exception as e:
                    log_error(f"Background guardrail '{hook.__name__}' execution failed: {str(e)}")
                    log_exception(e)
            else:
                pending_bg_hooks.append(hook)
        bg_args = copy_args_for_background(all_args)
        for hook in pending_bg_hooks:
            filtered_args = filter_hook_args(hook, bg_args)
            background_tasks.add_task(hook, **filtered_args)
        return

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
                log_warning(
                    f"Async hook '{hook.__name__}' cannot be used with sync run(). Use arun() instead. Skipping hook."
                )
                continue

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
            set_debug(agent, debug_mode=debug_mode)


async def aexecute_post_hooks(
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
) -> AsyncIterator[RunOutputEvent]:
    """Execute multiple post-hook functions in succession (async version)."""
    from agno.agent._init import set_debug

    if hooks is None:
        return

    # Prepare arguments for this hook
    all_args = {
        "run_output": run_output,
        "agent": agent,
        "session": session,
        "run_context": run_context,
        "user_id": user_id,
        "debug_mode": debug_mode if debug_mode is not None else agent.debug_mode,
        "metadata": run_context.metadata if run_context else None,
    }

    all_args.update(kwargs)

    # Global background mode — see execute_pre_hooks for pattern explanation.
    if agent._run_hooks_in_background is True and background_tasks is not None:
        pending_bg_hooks = []
        for hook in hooks:
            if is_guardrail_hook(hook):
                filtered_args = filter_hook_args(hook, all_args)
                try:
                    if iscoroutinefunction(hook):
                        await hook(**filtered_args)
                    else:
                        hook(**filtered_args)
                except (InputCheckError, OutputCheckError):
                    raise
                except Exception as e:
                    log_error(f"Background guardrail '{hook.__name__}' execution failed: {str(e)}")
                    log_exception(e)
            else:
                pending_bg_hooks.append(hook)
        bg_args = copy_args_for_background(all_args)
        for hook in pending_bg_hooks:
            filtered_args = filter_hook_args(hook, bg_args)
            background_tasks.add_task(hook, **filtered_args)
        return

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
            set_debug(agent, debug_mode=debug_mode)
