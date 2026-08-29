"""Agent-side compaction glue: the cross-run seam, run-state construction, persist drain.

The engine (agno.compaction) is pure; this module binds it to the agent's session, model and
storage. The team twin mirrors this file.
"""

import threading
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional, Tuple

from agno.compaction._notice import NoticeInputs
from agno.compaction._state import CompactionRunState, FoldHandle, clear_fold, in_flight_fold, register_fold
from agno.compaction._tokens import ContextGauge, estimate_tokens
from agno.compaction._view import build_view, notice_message, summary_message
from agno.compaction.compaction import (
    Compaction,
    CompactionRecord,
    EffectiveLimits,
    acomplete_pass,
    complete_pass,
    get_owner_records,
    merge_records_into_session_data,
    prepare_pass,
    resolve_active_record,
)
from agno.models.message import Message
from agno.run.base import HISTORY_SKIP_STATUSES
from agno.utils.log import log_debug, log_error
from agno.utils.message import copy_history_message

if TYPE_CHECKING:
    from agno.agent.agent import Agent
    from agno.run.messages import RunMessages
    from agno.session.agent import AgentSession


def summarizer_model(agent: "Agent"):
    config = agent._compaction
    return config.model if config is not None and config.model is not None else agent.model


def resolve_limits(agent: "Agent") -> EffectiveLimits:
    config = agent._compaction
    assert config is not None
    return config.resolve_limits(getattr(agent.model, "context_window", None) if agent.model is not None else None)


def compaction_notice_inputs(agent: "Agent", session_id: Optional[str]) -> NoticeInputs:
    """Probe durable state for the survival notice. Every probe is defensive: a failing source
    contributes nothing rather than failing the pass."""
    inputs = NoticeInputs()
    if not session_id:
        return inputs
    try:
        store = agent.result_store
        if store is not None:
            inputs.result_ids = [ref.result_id for ref in store.live_ids(session_id, limit=100)]
    except Exception:
        pass
    try:
        for tool in agent.tools or []:
            if type(tool).__name__ == "CodeMode" and hasattr(tool, "variables"):
                inputs.variables = sorted((tool.variables(session_id) or {}).keys())
                break
    except Exception:
        pass
    return inputs


async def acompaction_notice_inputs(agent: "Agent", session_id: Optional[str]) -> NoticeInputs:
    """Async twin of compaction_notice_inputs."""
    inputs = NoticeInputs()
    if not session_id:
        return inputs
    try:
        store = agent.result_store
        if store is not None:
            inputs.result_ids = [ref.result_id for ref in await store.alive_ids(session_id, limit=100)]
    except Exception:
        pass
    try:
        for tool in agent.tools or []:
            if type(tool).__name__ == "CodeMode" and hasattr(tool, "avariables"):
                inputs.variables = sorted((await tool.avariables(session_id) or {}).keys())
                break
    except Exception:
        pass
    return inputs


def record_validity_for_session(session: "AgentSession") -> Callable[[CompactionRecord], bool]:
    """L1(a): a record anchored in a run that history builders exclude must not govern a view."""
    runs_by_id: Dict[str, Any] = {}
    for run in session.runs or []:
        run_id = getattr(run, "run_id", None)
        if run_id:
            runs_by_id[run_id] = run

    def valid(record: CompactionRecord) -> bool:
        for run_id in (record.created_by_run_id, record.first_kept_run_id):
            if run_id:
                run = runs_by_id.get(run_id)
                if run is None:
                    return False
                status = getattr(run, "status", None)
                if status in HISTORY_SKIP_STATUSES:
                    return False
        return True

    return valid


def _find_message_index(messages: List[Message], message_id: str) -> Optional[int]:
    for index, message in enumerate(messages):
        if message.id == message_id:
            return index
    return None


def stamp_run_attribution(session: "AgentSession", record: CompactionRecord) -> None:
    """Map the boundary message id onto stored-run coordinates (run id, run position, message
    position in the stored run)."""
    if not record.first_kept_message_id:
        return
    for run_index, run in enumerate(session.runs or []):
        for message_index, message in enumerate(getattr(run, "messages", None) or []):
            if message.id == record.first_kept_message_id:
                record.first_kept_run_id = getattr(run, "run_id", None)
                record.first_kept_run_index = run_index
                record.first_kept_message_index = message_index
                return


def load_compacted_history(
    agent: "Agent",
    session: "AgentSession",
    skip_role: Optional[str],
) -> Tuple[List[Message], Optional[CompactionRecord], List[CompactionRecord]]:
    """Resolve the owner's active record and load history from its boundary on.

    Runs before the boundary run are never flattened or copied; an anchor miss walks the chain
    back and at worst falls open to full raw history."""
    owner_id = agent.id or ""
    chain = get_owner_records(session.session_data, owner_id)
    valid = record_validity_for_session(session)
    record = resolve_active_record(chain, record_is_valid=valid)

    get_kwargs: Dict[str, Any] = {
        "skip_roles": [skip_role] if skip_role else None,
        "agent_id": agent.id if agent.team_id is not None else None,
    }
    if record is not None and record.first_kept_run_id:
        history = session.get_messages(after_run_id=record.first_kept_run_id, **get_kwargs)
    else:
        history = session.get_messages(**get_kwargs)

    if record is not None and record.first_kept_message_id:
        boundary = _find_message_index(history, record.first_kept_message_id)
        if boundary is None:
            # Message-level anchor miss (scrub or partial load): re-resolve against the full list.
            history = session.get_messages(**get_kwargs)
            available_ids = {message.id for message in history}
            record = resolve_active_record(
                chain,
                record_is_valid=lambda r: valid(r)
                and (not r.first_kept_message_id or r.first_kept_message_id in available_ids),
            )
            boundary = (
                _find_message_index(history, record.first_kept_message_id)
                if record is not None and record.first_kept_message_id
                else None
            )
        if boundary is not None:
            history = history[boundary:]
    return history, record, chain


def _run_build_pass_sync(
    agent: "Agent",
    session: "AgentSession",
    plan,
) -> Optional[CompactionRecord]:
    config = agent._compaction
    assert config is not None
    try:
        record = complete_pass(
            plan,
            config=config,
            model=summarizer_model(agent),
            summarizer_window=getattr(summarizer_model(agent), "context_window", None),
        )
    except Exception as exc:
        log_error(f"Compaction pass failed; continuing with the uncompacted view: {exc}")
        return None
    stamp_run_attribution(session, record)
    _commit_record(session, agent.id or "", record)
    return record


def _commit_record(session: "AgentSession", owner_id: str, record: CompactionRecord) -> None:
    if session.session_data is None:
        session.session_data = {}
    merge_records_into_session_data(session.session_data, owner_id, [record])


def _start_background_fold(agent: "Agent", session: "AgentSession", plan) -> None:
    """Run the fold on a thread; the plan's segment is frozen text, so nothing races. The record
    is delivered at the next sync point (loop-top, next build, or terminal persist) that finds
    the finished handle in the registry."""
    config = agent._compaction
    assert config is not None
    session_id = session.session_id or ""
    owner_id = agent.id or ""
    handle = FoldHandle(plan=plan)
    if not register_fold(session_id, owner_id, handle):
        return
    model = summarizer_model(agent)
    window = getattr(model, "context_window", None)

    def _worker() -> None:
        try:
            handle.record = complete_pass(plan, config=config, model=model, summarizer_window=window)
        except Exception as exc:  # pure fold: failure loses nothing
            handle.error = exc
            log_debug(f"Background compaction fold failed (will retry at the next trigger): {exc}")

    thread = threading.Thread(target=_worker, name="agno-compaction-fold", daemon=True)
    handle.thread = thread
    thread.start()


def adopt_finished_fold(agent: "Agent", session: "AgentSession") -> Optional[CompactionRecord]:
    """If a registry-visible fold for this (session, owner) has finished, commit and return its
    record; None otherwise. Never blocks.

    A record scoped to another run's own messages (created_by_run_id set) is dropped here: only
    the creating run may commit it, and if that run died its content never persisted."""
    session_id = session.session_id or ""
    owner_id = agent.id or ""
    handle = in_flight_fold(session_id, owner_id)
    if handle is None or not handle.done():
        return None
    clear_fold(session_id, owner_id, handle)
    if handle.record is None or handle.record.created_by_run_id is not None:
        return None
    record = handle.record
    stamp_run_attribution(session, record)
    _commit_record(session, owner_id, record)
    return record


def drain_compaction_state_at_persist(agent: "Agent", run_response, session: "AgentSession", storage_copy) -> None:
    """Commit routing at the persist funnel: records created in-run reach the session row only
    when the creating run completed; error, cancel, and pause discard them (the transcript they
    summarise is excluded from history anyway) and abandon any in-flight fold un-joined."""
    from agno.run.base import RunStatus

    state = getattr(run_response, "_compaction_state", None)
    if state is None:
        return
    status = run_response.status
    if status == RunStatus.completed:
        handle = state.fold_future
        if handle is not None:
            if not handle.done() and handle.thread is not None:
                # Join before persist; the record commits for the next run's benefit only — it
                # never activated, so this run's compaction_id keeps naming the record its final
                # provider call actually used.
                handle.join()
            clear_fold(state.session_id, state.owner_id, handle)
            if handle.record is not None and handle.record not in state.pending_records:
                state.pending_records.append(handle.record)
            state.fold_future = None
        if state.pending_records:
            if session.session_data is None:
                session.session_data = {}
            for record in state.pending_records:
                if record.first_kept_message_id and record.first_kept_run_index is None:
                    stamp_run_attribution(session, record)
            merge_records_into_session_data(session.session_data, state.owner_id, state.pending_records)
            state.pending_records = []
        if state.active_record is not None:
            run_response.compaction_id = state.active_record.id
            if storage_copy is not None:
                storage_copy.compaction_id = state.active_record.id
    elif status in (RunStatus.error, RunStatus.cancelled, RunStatus.paused):
        state.pending_records = []
        # Abandon, never join: the fold is pure and its result is simply dropped. The registry
        # entry stays until the thread finishes so a concurrent fold cannot double-start.
        state.fold_future = None


def add_compacted_history(
    agent: "Agent",
    run_messages: "RunMessages",
    session: "AgentSession",
    skip_role: Optional[str],
) -> None:
    """The cross-run seam: history under compaction. Replaces the num_history_runs window."""
    config = agent._compaction
    assert config is not None
    limits = resolve_limits(agent)

    # A background fold from a previous run may have landed; use it before measuring.
    adopt_finished_fold(agent, session)

    history, record, chain = load_compacted_history(agent, session, skip_role)
    history_copy = [copy_history_message(message) for message in history]

    candidate = list(run_messages.messages) + history_copy
    view = build_view(candidate, record, elide_exclude_tools=config.elide_exclude_tools)
    reading = estimate_tokens(view)

    if reading > limits.trigger_tokens and reading >= limits.worth_it_floor:
        # Hard trigger at build: wait for a registry-visible in-flight fold before folding twice.
        handle = in_flight_fold(session.session_id or "", agent.id or "")
        if handle is not None and handle.thread is not None:
            handle.join()
            adopted = adopt_finished_fold(agent, session)
            if adopted is not None:
                history, record, chain = load_compacted_history(agent, session, skip_role)
                history_copy = [copy_history_message(message) for message in history]
                candidate = list(run_messages.messages) + history_copy
                view = build_view(candidate, record, elide_exclude_tools=config.elide_exclude_tools)
                reading = estimate_tokens(view)
        if reading > limits.trigger_tokens:
            plan = prepare_pass(
                config,
                limits,
                candidate,
                reason="threshold",
                previous_record=record,
                created_by_run_id=None,
                notice_inputs=compaction_notice_inputs(agent, session.session_id),
                allow_tool_batch_heads=agent.store_tool_messages,
            )
            if plan is not None:
                new_record = _run_build_pass_sync(agent, session, plan)
                if new_record is not None:
                    record = new_record
                    if record.first_kept_message_id:
                        boundary = _find_message_index(history_copy, record.first_kept_message_id)
                        if boundary is not None:
                            history_copy = history_copy[boundary:]
    elif (
        limits.soft_trigger_tokens is not None
        and reading > limits.soft_trigger_tokens
        and reading >= limits.worth_it_floor
        and in_flight_fold(session.session_id or "", agent.id or "") is None
    ):
        plan = prepare_pass(
            config,
            limits,
            candidate,
            reason="threshold",
            previous_record=record,
            created_by_run_id=None,
            notice_inputs=compaction_notice_inputs(agent, session.session_id),
            allow_tool_batch_heads=agent.store_tool_messages,
            elision_target_tokens=limits.soft_trigger_tokens,
        )
        if plan is not None:
            if plan.elision_only:
                # Elision costs no model call; commit it inline.
                new_record = _run_build_pass_sync(agent, session, plan)
                if new_record is not None:
                    record = new_record
            else:
                _start_background_fold(agent, session, plan)

    if record is not None and record.summary and history_copy and history_copy[0].id == record.first_kept_message_id:
        run_messages.messages.append(summary_message(record))
        if record.notice:
            run_messages.messages.append(notice_message(record))
    if history_copy:
        log_debug(f"Adding {len(history_copy)} messages from history (compaction active)")
        run_messages.messages += history_copy
    run_messages.compaction_record = record


async def aadd_compacted_history(
    agent: "Agent",
    run_messages: "RunMessages",
    session: "AgentSession",
    skip_role: Optional[str],
) -> None:
    """Async twin of add_compacted_history."""
    config = agent._compaction
    assert config is not None
    limits = resolve_limits(agent)

    adopt_finished_fold(agent, session)

    history, record, chain = load_compacted_history(agent, session, skip_role)
    history_copy = [copy_history_message(message) for message in history]

    candidate = list(run_messages.messages) + history_copy
    view = build_view(candidate, record, elide_exclude_tools=config.elide_exclude_tools)
    reading = estimate_tokens(view)

    if reading > limits.trigger_tokens and reading >= limits.worth_it_floor:
        handle = in_flight_fold(session.session_id or "", agent.id or "")
        if handle is not None:
            await handle.ajoin()
            adopted = adopt_finished_fold(agent, session)
            if adopted is not None:
                history, record, chain = load_compacted_history(agent, session, skip_role)
                history_copy = [copy_history_message(message) for message in history]
                candidate = list(run_messages.messages) + history_copy
                view = build_view(candidate, record, elide_exclude_tools=config.elide_exclude_tools)
                reading = estimate_tokens(view)
        if reading > limits.trigger_tokens:
            plan = prepare_pass(
                config,
                limits,
                candidate,
                reason="threshold",
                previous_record=record,
                created_by_run_id=None,
                notice_inputs=await acompaction_notice_inputs(agent, session.session_id),
                allow_tool_batch_heads=agent.store_tool_messages,
            )
            if plan is not None:
                try:
                    new_record = await acomplete_pass(
                        plan,
                        config=config,
                        model=summarizer_model(agent),
                        summarizer_window=getattr(summarizer_model(agent), "context_window", None),
                    )
                except Exception as exc:
                    log_error(f"Compaction pass failed; continuing with the uncompacted view: {exc}")
                    new_record = None
                if new_record is not None:
                    stamp_run_attribution(session, new_record)
                    _commit_record(session, agent.id or "", new_record)
                    record = new_record
                    if record.first_kept_message_id:
                        boundary = _find_message_index(history_copy, record.first_kept_message_id)
                        if boundary is not None:
                            history_copy = history_copy[boundary:]
    elif (
        limits.soft_trigger_tokens is not None
        and reading > limits.soft_trigger_tokens
        and reading >= limits.worth_it_floor
        and in_flight_fold(session.session_id or "", agent.id or "") is None
    ):
        plan = prepare_pass(
            config,
            limits,
            candidate,
            reason="threshold",
            previous_record=record,
            created_by_run_id=None,
            notice_inputs=await acompaction_notice_inputs(agent, session.session_id),
            allow_tool_batch_heads=agent.store_tool_messages,
            elision_target_tokens=limits.soft_trigger_tokens,
        )
        if plan is not None:
            if plan.elision_only:
                new_record = _run_build_pass_sync(agent, session, plan)
                if new_record is not None:
                    record = new_record
            else:
                _start_background_fold(agent, session, plan)

    if record is not None and record.summary and history_copy and history_copy[0].id == record.first_kept_message_id:
        run_messages.messages.append(summary_message(record))
        if record.notice:
            run_messages.messages.append(notice_message(record))
    if history_copy:
        log_debug(f"Adding {len(history_copy)} messages from history (compaction active)")
        run_messages.messages += history_copy
    run_messages.compaction_record = record


def record_compaction_events(agent: "Agent", run_response) -> None:
    """Convert buffered pass events into stored run events on the non-streaming path.

    Streaming runs bridge marker events live; non-streaming has no live channel, so whatever the
    loop buffered is converted after the call returns and lands in run_response.events under
    store_events."""
    state = getattr(run_response, "_compaction_state", None)
    if state is None or not state.event_buffer:
        return
    from agno.utils.events import (
        create_compaction_completed_event,
        create_compaction_started_event,
        handle_event,
    )

    for item in state.event_buffer:
        if item.get("type") == "started":
            event = create_compaction_started_event(
                from_run_response=run_response,
                reason=item.get("reason"),
                tokens_before=item.get("tokens_before"),
            )
        else:
            event = create_compaction_completed_event(
                from_run_response=run_response,
                reason=item.get("reason"),
                tokens_before=item.get("tokens_before"),
                tokens_after=item.get("tokens_after"),
                messages_folded=item.get("messages_folded"),
                record_id=item.get("record_id"),
                duration_ms=item.get("duration_ms"),
                still_over_trigger=item.get("still_over_trigger"),
            )
        handle_event(event, run_response, events_to_skip=agent.events_to_skip, store_events=agent.store_events)
    state.event_buffer.clear()


def compact_session(
    agent: "Agent",
    session_id: Optional[str] = None,
    user_id: Optional[str] = None,
    instructions: Optional[str] = None,
) -> Optional[CompactionRecord]:
    """The /compact analog: fold everything older than the keep tail, host-side, outside a run.

    Skips the trigger check entirely; returns None only when there is nothing to fold. Operator
    instructions are trusted and may narrow retention for this pass."""
    if agent.db is None:
        raise ValueError("agent.compact() requires a db: there is no durable session to compact")
    agent.initialize_agent()
    if agent._compaction is None:
        raise ValueError("agent.compact() requires compaction to be enabled on the agent")
    config = agent._compaction
    limits = resolve_limits(agent)
    session = agent.get_session(session_id=session_id, user_id=user_id)
    if session is None:
        raise ValueError(f"Session not found: {session_id}")

    skip_role = agent.system_message_role if agent.system_message_role not in ["user", "assistant", "tool"] else None
    history, record, chain = load_compacted_history(agent, session, skip_role)
    plan = prepare_pass(
        config,
        limits,
        history,
        reason="manual",
        previous_record=record,
        created_by_run_id=None,
        notice_inputs=compaction_notice_inputs(agent, session.session_id),
        call_instructions=instructions,
        allow_tool_batch_heads=agent.store_tool_messages,
    )
    if plan is None:
        return None
    new_record = complete_pass(
        plan,
        config=config,
        model=summarizer_model(agent),
        summarizer_window=getattr(summarizer_model(agent), "context_window", None),
    )
    stamp_run_attribution(session, new_record)
    _commit_record(session, agent.id or "", new_record)
    from agno.agent import _session

    _session.save_session(agent, session=session)
    return new_record


async def acompact_session(
    agent: "Agent",
    session_id: Optional[str] = None,
    user_id: Optional[str] = None,
    instructions: Optional[str] = None,
) -> Optional[CompactionRecord]:
    """Async twin of compact_session."""
    if agent.db is None:
        raise ValueError("agent.compact() requires a db: there is no durable session to compact")
    agent.initialize_agent()
    if agent._compaction is None:
        raise ValueError("agent.compact() requires compaction to be enabled on the agent")
    config = agent._compaction
    limits = resolve_limits(agent)
    session = await agent.aget_session(session_id=session_id, user_id=user_id)
    if session is None:
        raise ValueError(f"Session not found: {session_id}")

    skip_role = agent.system_message_role if agent.system_message_role not in ["user", "assistant", "tool"] else None
    history, record, chain = load_compacted_history(agent, session, skip_role)
    plan = prepare_pass(
        config,
        limits,
        history,
        reason="manual",
        previous_record=record,
        created_by_run_id=None,
        notice_inputs=await acompaction_notice_inputs(agent, session.session_id),
        call_instructions=instructions,
        allow_tool_batch_heads=agent.store_tool_messages,
    )
    if plan is None:
        return None
    new_record = await acomplete_pass(
        plan,
        config=config,
        model=summarizer_model(agent),
        summarizer_window=getattr(summarizer_model(agent), "context_window", None),
    )
    stamp_run_attribution(session, new_record)
    _commit_record(session, agent.id or "", new_record)
    from agno.agent import _session

    await _session.asave_session(agent, session=session)
    return new_record


def make_run_state(
    agent: "Agent",
    session: "AgentSession",
    run_response,
    run_messages: "RunMessages",
) -> CompactionRunState:
    """Build the per-run carrier after the message build. Everything appended from here on is the
    run's own, so in-run cuts land at or after the current list length."""
    config = agent._compaction
    assert config is not None
    limits = resolve_limits(agent)
    session_id = session.session_id or ""
    chain = get_owner_records(session.session_data, agent.id or "")
    record = run_messages.compaction_record
    if not isinstance(record, CompactionRecord):
        record = None
    if record is None and getattr(run_response, "compaction_id", None):
        # Resume/fork: the run builds from its own record, not the chain head.
        record = next((r for r in chain if r.id == run_response.compaction_id), None)
    state = CompactionRunState(
        config=config,
        limits=limits,
        gauge=ContextGauge(limits=limits),
        session_id=session_id,
        owner_id=agent.id or "",
        run_id=getattr(run_response, "run_id", None),
        active_record=record,
        chain=chain,
        notice_sources=lambda: compaction_notice_inputs(agent, session_id),
        strip_provider_chaining=True,
        first_own_message_index=len(run_messages.messages),
        allow_tool_batch_heads=agent.store_tool_messages,
    )
    return state


def compaction_state_kwargs(agent: "Agent", *, session: "AgentSession", run_response, run_messages) -> Dict[str, Any]:
    """The ``compaction_state=`` kwarg for a model call, or nothing at all when compaction is off.

    The kwarg is omitted entirely when off so Model.response* overrides without the parameter
    keep working. The state is created once per run and rides the run output object (a private,
    never-serialized attribute) so persist points can drain it."""
    if agent._compaction is None:
        return {}
    state = getattr(run_response, "_compaction_state", None)
    if state is None:
        state = make_run_state(agent, session, run_response, run_messages)
        run_response._compaction_state = state
    return {"compaction_state": state}
