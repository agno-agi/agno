"""Hook execution helpers for Team."""

from __future__ import annotations

from typing import (
    TYPE_CHECKING,
    Any,
    AsyncIterator,
    Callable,
    Iterator,
    List,
    Optional,
    Union,
)

from agno.exceptions import (
    InputCheckError,
    OutputCheckError,
)
from agno.run import RunContext, RunStatus
from agno.run.agent import RunOutputEvent
from agno.run.team import (
    TeamRunInput,
    TeamRunOutput,
    TeamRunOutputEvent,
)
from agno.session import TeamSession
from agno.utils.events import (
    create_team_post_hook_completed_event,
    create_team_post_hook_started_event,
    create_team_pre_hook_completed_event,
    create_team_pre_hook_started_event,
    create_team_run_paused_event,
    handle_event,
)
from agno.utils.hooks import (
    copy_args_for_background,
    filter_hook_args,
    is_guardrail_hook,
    should_run_hook_in_background,
)
from agno.utils.log import (
    log_debug,
    log_error,
    log_exception,
)

if TYPE_CHECKING:
    from agno.team.team import Team


# ---------------------------------------------------------------------------
# HITL pause handlers
# ---------------------------------------------------------------------------


def _get_team_paused_content(run_response: TeamRunOutput) -> str:
    """Generate human-readable content for a paused team run."""
    if not run_response.requirements:
        return "Team run paused."
    active = [req for req in run_response.requirements if not req.is_resolved()]
    if not active:
        return "Team run paused."
    parts: list[str] = []
    for req in active:
        member = req.member_agent_name or "team"
        tool_name = req.tool_execution.tool_name if req.tool_execution else "unknown"
        if req.needs_confirmation:
            parts.append(f"- {member}: {tool_name} requires confirmation")
        elif req.needs_user_input:
            parts.append(f"- {member}: {tool_name} requires user input")
        elif req.needs_external_execution:
            parts.append(f"- {member}: {tool_name} requires external execution")
    return "Team run paused. The following require input:\n" + "\n".join(parts)


def handle_team_run_paused(
    team: "Team",
    run_response: TeamRunOutput,
    session: TeamSession,
    run_context: Optional[RunContext] = None,
) -> TeamRunOutput:
    from agno.run.approval import create_approval_from_pause
    from agno.team._run import _cleanup_and_store

    run_response.status = RunStatus.paused
    if not run_response.content:
        run_response.content = _get_team_paused_content(run_response)

    handle_event(
        create_team_run_paused_event(
            from_run_response=run_response,
            tools=run_response.tools,
            requirements=run_response.requirements,
        ),
        run_response,
        events_to_skip=team.events_to_skip,  # type: ignore
        store_events=team.store_events,
    )

    _cleanup_and_store(team, run_response=run_response, session=session, run_context=run_context)
    create_approval_from_pause(
        db=team.db, run_response=run_response, team_id=team.id, team_name=team.name, user_id=team.user_id
    )

    log_debug(f"Team Run Paused: {run_response.run_id}", center=True, symbol="*")
    return run_response


def handle_team_run_paused_stream(
    team: "Team",
    run_response: TeamRunOutput,
    session: TeamSession,
    run_context: Optional[RunContext] = None,
) -> Iterator[Union[TeamRunOutputEvent, RunOutputEvent]]:
    from agno.run.approval import create_approval_from_pause
    from agno.team._run import _cleanup_and_store

    run_response.status = RunStatus.paused
    if not run_response.content:
        run_response.content = _get_team_paused_content(run_response)

    pause_event = handle_event(
        create_team_run_paused_event(
            from_run_response=run_response,
            tools=run_response.tools,
            requirements=run_response.requirements,
        ),
        run_response,
        events_to_skip=team.events_to_skip,  # type: ignore
        store_events=team.store_events,
    )

    _cleanup_and_store(team, run_response=run_response, session=session, run_context=run_context)
    create_approval_from_pause(
        db=team.db, run_response=run_response, team_id=team.id, team_name=team.name, user_id=team.user_id
    )

    if pause_event is not None:
        yield pause_event

    log_debug(f"Team Run Paused: {run_response.run_id}", center=True, symbol="*")


async def ahandle_team_run_paused(
    team: "Team",
    run_response: TeamRunOutput,
    session: TeamSession,
    run_context: Optional[RunContext] = None,
) -> TeamRunOutput:
    from agno.run.approval import acreate_approval_from_pause
    from agno.team._run import _acleanup_and_store

    run_response.status = RunStatus.paused
    if not run_response.content:
        run_response.content = _get_team_paused_content(run_response)

    handle_event(
        create_team_run_paused_event(
            from_run_response=run_response,
            tools=run_response.tools,
            requirements=run_response.requirements,
        ),
        run_response,
        events_to_skip=team.events_to_skip,  # type: ignore
        store_events=team.store_events,
    )

    await _acleanup_and_store(team, run_response=run_response, session=session, run_context=run_context)
    await acreate_approval_from_pause(
        db=team.db, run_response=run_response, team_id=team.id, team_name=team.name, user_id=team.user_id
    )

    log_debug(f"Team Run Paused: {run_response.run_id}", center=True, symbol="*")
    return run_response


async def ahandle_team_run_paused_stream(
    team: "Team",
    run_response: TeamRunOutput,
    session: TeamSession,
    run_context: Optional[RunContext] = None,
) -> AsyncIterator[Union[TeamRunOutputEvent, RunOutputEvent]]:
    from agno.run.approval import acreate_approval_from_pause
    from agno.team._run import _acleanup_and_store

    run_response.status = RunStatus.paused
    if not run_response.content:
        run_response.content = _get_team_paused_content(run_response)

    pause_event = handle_event(
        create_team_run_paused_event(
            from_run_response=run_response,
            tools=run_response.tools,
            requirements=run_response.requirements,
        ),
        run_response,
        events_to_skip=team.events_to_skip,  # type: ignore
        store_events=team.store_events,
    )

    await _acleanup_and_store(team, run_response=run_response, session=session, run_context=run_context)
    await acreate_approval_from_pause(
        db=team.db, run_response=run_response, team_id=team.id, team_name=team.name, user_id=team.user_id
    )

    if pause_event is not None:
        yield pause_event

    log_debug(f"Team Run Paused: {run_response.run_id}", center=True, symbol="*")


def _execute_pre_hooks(
    team: "Team",
    hooks: Optional[List[Callable[..., Any]]],
    run_response: TeamRunOutput,
    run_input: TeamRunInput,
    session: TeamSession,
    run_context: RunContext,
    user_id: Optional[str] = None,
    debug_mode: Optional[bool] = None,
    stream_events: bool = False,
    background_tasks: Optional[Any] = None,
    **kwargs: Any,
) -> Iterator[TeamRunOutputEvent]:
    """Execute multiple pre-hook functions in succession."""
    from agno.team._init import _set_debug

    if hooks is None:
        return

    # Prepare arguments for hooks
    effective_debug_mode = debug_mode if debug_mode is not None else team.debug_mode
    all_args = {
        "run_input": run_input,
        "run_context": run_context,
        "team": team,
        "session": session,
        "user_id": user_id,
        "debug_mode": effective_debug_mode,
        "metadata": run_context.metadata if run_context else None,
    }

    all_args.update(kwargs)

    # Global background mode: run guardrails synchronously, buffer everything else.
    # See agent/_hooks.py execute_pre_hooks for full pattern explanation.
    if team._run_hooks_in_background is True and background_tasks is not None:
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
            bg_args = copy_args_for_background(all_args)
            filtered_args = filter_hook_args(hook, bg_args)
            background_tasks.add_task(hook, **filtered_args)
            continue

        if stream_events:
            yield handle_event(  # type: ignore
                run_response=run_response,
                event=create_team_pre_hook_started_event(
                    from_run_response=run_response, run_input=run_input, pre_hook_name=hook.__name__
                ),
                events_to_skip=team.events_to_skip,
                store_events=team.store_events,
            )
        try:
            filtered_args = filter_hook_args(hook, all_args)

            hook(**filtered_args)

            if stream_events:
                yield handle_event(  # type: ignore
                    run_response=run_response,
                    event=create_team_pre_hook_completed_event(
                        from_run_response=run_response, run_input=run_input, pre_hook_name=hook.__name__
                    ),
                    events_to_skip=team.events_to_skip,
                    store_events=team.store_events,
                )

        except (InputCheckError, OutputCheckError) as e:
            raise e
        except Exception as e:
            log_error(f"Pre-hook #{i + 1} execution failed: {str(e)}")
            log_exception(e)
        finally:
            # Reset global log mode incase an agent in the pre-hook changed it
            _set_debug(team, debug_mode=debug_mode)

    # Update the input on the run_response
    run_response.input = run_input


async def _aexecute_pre_hooks(
    team: "Team",
    hooks: Optional[List[Callable[..., Any]]],
    run_response: TeamRunOutput,
    run_input: TeamRunInput,
    session: TeamSession,
    run_context: RunContext,
    user_id: Optional[str] = None,
    debug_mode: Optional[bool] = None,
    stream_events: bool = False,
    background_tasks: Optional[Any] = None,
    **kwargs: Any,
) -> AsyncIterator[TeamRunOutputEvent]:
    """Execute multiple pre-hook functions in succession (async version)."""
    from agno.team._init import _set_debug

    if hooks is None:
        return

    # Prepare arguments for hooks
    effective_debug_mode = debug_mode if debug_mode is not None else team.debug_mode
    all_args = {
        "run_input": run_input,
        "run_context": run_context,
        "team": team,
        "session": session,
        "user_id": user_id,
        "debug_mode": effective_debug_mode,
        "metadata": run_context.metadata if run_context else None,
    }

    all_args.update(kwargs)

    # Global background mode — see _execute_pre_hooks for pattern explanation.
    if team._run_hooks_in_background is True and background_tasks is not None:
        pending_bg_hooks = []
        for hook in hooks:
            if is_guardrail_hook(hook):
                filtered_args = filter_hook_args(hook, all_args)
                try:
                    from inspect import iscoroutinefunction

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
            bg_args = copy_args_for_background(all_args)
            filtered_args = filter_hook_args(hook, bg_args)
            background_tasks.add_task(hook, **filtered_args)
            continue

        if stream_events:
            yield handle_event(  # type: ignore
                run_response=run_response,
                event=create_team_pre_hook_started_event(
                    from_run_response=run_response, run_input=run_input, pre_hook_name=hook.__name__
                ),
                events_to_skip=team.events_to_skip,
                store_events=team.store_events,
            )
        try:
            filtered_args = filter_hook_args(hook, all_args)

            from inspect import iscoroutinefunction

            if iscoroutinefunction(hook):
                await hook(**filtered_args)
            else:
                hook(**filtered_args)

            if stream_events:
                yield handle_event(  # type: ignore
                    run_response=run_response,
                    event=create_team_pre_hook_completed_event(
                        from_run_response=run_response, run_input=run_input, pre_hook_name=hook.__name__
                    ),
                    events_to_skip=team.events_to_skip,
                    store_events=team.store_events,
                )

        except (InputCheckError, OutputCheckError) as e:
            raise e
        except Exception as e:
            log_error(f"Pre-hook #{i + 1} execution failed: {str(e)}")
            log_exception(e)
        finally:
            # Reset global log mode incase an agent in the pre-hook changed it
            _set_debug(team, debug_mode=debug_mode)

    # Update the input on the run_response
    run_response.input = run_input


def _execute_post_hooks(
    team: "Team",
    hooks: Optional[List[Callable[..., Any]]],
    run_output: TeamRunOutput,
    session: TeamSession,
    run_context: RunContext,
    user_id: Optional[str] = None,
    debug_mode: Optional[bool] = None,
    stream_events: bool = False,
    background_tasks: Optional[Any] = None,
    **kwargs: Any,
) -> Iterator[TeamRunOutputEvent]:
    """Execute multiple post-hook functions in succession."""
    from agno.team._init import _set_debug

    if hooks is None:
        return

    # Prepare arguments for hooks
    effective_debug_mode = debug_mode if debug_mode is not None else team.debug_mode
    all_args = {
        "run_output": run_output,
        "run_context": run_context,
        "team": team,
        "session": session,
        "user_id": user_id,
        "debug_mode": effective_debug_mode,
        "metadata": run_context.metadata if run_context else None,
    }

    all_args.update(kwargs)

    # Global background mode — see _execute_pre_hooks for pattern explanation.
    if team._run_hooks_in_background is True and background_tasks is not None:
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
            bg_args = copy_args_for_background(all_args)
            filtered_args = filter_hook_args(hook, bg_args)
            background_tasks.add_task(hook, **filtered_args)
            continue

        if stream_events:
            yield handle_event(  # type: ignore
                run_response=run_output,
                event=create_team_post_hook_started_event(  # type: ignore
                    from_run_response=run_output,
                    post_hook_name=hook.__name__,
                ),
                events_to_skip=team.events_to_skip,
                store_events=team.store_events,
            )
        try:
            filtered_args = filter_hook_args(hook, all_args)

            hook(**filtered_args)

            if stream_events:
                yield handle_event(  # type: ignore
                    run_response=run_output,
                    event=create_team_post_hook_completed_event(  # type: ignore
                        from_run_response=run_output,
                        post_hook_name=hook.__name__,
                    ),
                    events_to_skip=team.events_to_skip,
                    store_events=team.store_events,
                )

        except (InputCheckError, OutputCheckError) as e:
            raise e
        except Exception as e:
            log_error(f"Post-hook #{i + 1} execution failed: {str(e)}")
            log_exception(e)
        finally:
            # Reset global log mode incase an agent in the post-hook changed it
            _set_debug(team, debug_mode=debug_mode)


async def _aexecute_post_hooks(
    team: "Team",
    hooks: Optional[List[Callable[..., Any]]],
    run_output: TeamRunOutput,
    session: TeamSession,
    run_context: RunContext,
    user_id: Optional[str] = None,
    debug_mode: Optional[bool] = None,
    stream_events: bool = False,
    background_tasks: Optional[Any] = None,
    **kwargs: Any,
) -> AsyncIterator[TeamRunOutputEvent]:
    """Execute multiple post-hook functions in succession (async version)."""
    from agno.team._init import _set_debug

    if hooks is None:
        return

    # Prepare arguments for hooks
    effective_debug_mode = debug_mode if debug_mode is not None else team.debug_mode
    all_args = {
        "run_output": run_output,
        "run_context": run_context,
        "team": team,
        "session": session,
        "user_id": user_id,
        "debug_mode": effective_debug_mode,
        "metadata": run_context.metadata if run_context else None,
    }

    all_args.update(kwargs)

    # Global background mode — see _execute_pre_hooks for pattern explanation.
    if team._run_hooks_in_background is True and background_tasks is not None:
        pending_bg_hooks = []
        for hook in hooks:
            if is_guardrail_hook(hook):
                filtered_args = filter_hook_args(hook, all_args)
                try:
                    from inspect import iscoroutinefunction

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
            bg_args = copy_args_for_background(all_args)
            filtered_args = filter_hook_args(hook, bg_args)
            background_tasks.add_task(hook, **filtered_args)
            continue

        if stream_events:
            yield handle_event(  # type: ignore
                run_response=run_output,
                event=create_team_post_hook_started_event(  # type: ignore
                    from_run_response=run_output,
                    post_hook_name=hook.__name__,
                ),
                events_to_skip=team.events_to_skip,
                store_events=team.store_events,
            )
        try:
            filtered_args = filter_hook_args(hook, all_args)

            from inspect import iscoroutinefunction

            if iscoroutinefunction(hook):
                await hook(**filtered_args)
            else:
                hook(**filtered_args)

            if stream_events:
                yield handle_event(  # type: ignore
                    run_response=run_output,
                    event=create_team_post_hook_completed_event(  # type: ignore
                        from_run_response=run_output,
                        post_hook_name=hook.__name__,
                    ),
                    events_to_skip=team.events_to_skip,
                    store_events=team.store_events,
                )
        except (InputCheckError, OutputCheckError) as e:
            raise e
        except Exception as e:
            log_error(f"Post-hook #{i + 1} execution failed: {str(e)}")
            log_exception(e)
        finally:
            # Reset global log mode incase an agent in the post-hook changed it
            _set_debug(team, debug_mode=debug_mode)
