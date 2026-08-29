"""In-run compaction: the loop-top check, view derivation, and overflow recovery.

Called from the four Model.response* loops when a CompactionRunState is present. Records created
here activate immediately for the running loop and ride pending_records to the commit-on-COMPLETED
persist; the loop itself never touches storage.
"""

import threading
from typing import TYPE_CHECKING, List, Optional

from agno.compaction._state import CompactionRunState, FoldHandle, clear_fold, in_flight_fold, register_fold
from agno.compaction._view import build_view
from agno.compaction.compaction import (
    CompactionRecord,
    PassPlan,
    acomplete_pass,
    complete_pass,
    prepare_pass,
)
from agno.models.message import Message
from agno.utils.log import log_debug, log_error, log_warning

if TYPE_CHECKING:
    from agno.models.base import Model
    from agno.models.response import ModelResponse


def outbound_view(messages: List[Message], state: CompactionRunState) -> List[Message]:
    """The payload for the next provider call, derived fresh from the canonical list."""
    return build_view(
        messages,
        state.active_record,
        elide_exclude_tools=state.config.elide_exclude_tools,
        strip_provider_chaining=state.strip_provider_chaining,
    )


def _summarizer(model: "Model", state: CompactionRunState) -> "Model":
    return state.config.model if state.config.model is not None else model


def _maybe_refresh_limits(model: "Model", state: CompactionRunState) -> None:
    """Under a fallback the active model changes; the window follows it."""
    model_window = getattr(model, "context_window", None)
    resolved = state.config.resolve_window(model_window)
    if resolved != state.limits.window:
        state.limits = state.config.resolve_limits(model_window)
        state.gauge.limits = state.limits


def _emit(state: CompactionRunState, event_type: str, **payload) -> None:
    state.event_buffer.append({"type": event_type, **payload})


def _activate(state: CompactionRunState, record: CompactionRecord, messages: List[Message]) -> None:
    """Make a record govern the loop from the next view on. Commit happens at persist (L2)."""
    state.active_record = record
    state.chain.append(record)
    state.pending_records.append(record)
    # The newest usage sample measures the pre-pass context; post-pass readings are view estimates.
    state.gauge.invalidate_anchor()
    post_reading = state.gauge.reading(outbound_view(messages, state))
    record.stats["tokens_after"] = post_reading
    state.gauge.suppress_soft(post_reading)
    if post_reading > state.limits.trigger_tokens:
        state.still_over_trigger = True
        state.gauge.suppress_hard(post_reading)
        if not record.stats.get("still_over_warned"):
            record.stats["still_over_warned"] = True
            log_warning(
                "Compaction pass left the view over the trigger (one oversized kept message?); "
                "continuing without further passes until the context grows"
            )
    else:
        state.still_over_trigger = False
    _emit(
        state,
        "completed",
        reason=record.reason,
        record_id=record.id,
        tokens_before=record.stats.get("tokens_before"),
        tokens_after=post_reading,
        messages_folded=record.stats.get("messages_folded"),
        duration_ms=record.stats.get("duration_ms"),
        still_over_trigger=state.still_over_trigger,
    )


def drain_marker_events(state: CompactionRunState) -> List["ModelResponse"]:
    """Convert buffered pass events into ModelResponse markers (stream loops yield these)."""
    from agno.models.response import ModelResponse, ModelResponseEvent

    markers: List[ModelResponse] = []
    for item in state.event_buffer:
        event = (
            ModelResponseEvent.compaction_started.value
            if item.get("type") == "started"
            else ModelResponseEvent.compaction_completed.value
        )
        payload = {key: value for key, value in item.items() if key != "type"}
        markers.append(ModelResponse(event=event, compaction_stats=payload))
    state.event_buffer.clear()
    return markers


def _prepare(
    state: CompactionRunState,
    messages: List[Message],
    reason: str,
    *,
    elision_target_tokens: Optional[int] = None,
    call_instructions: Optional[str] = None,
    untrusted_instructions: Optional[str] = None,
) -> Optional[PassPlan]:
    notice_inputs = None
    if state.notice_sources is not None:
        try:
            notice_inputs = state.notice_sources()
        except Exception:
            notice_inputs = None
    # No floor at the history boundary: an in-run cut may land in the history region — run
    # attribution is stamped from message ids at persist, and commit routing below keys off
    # whether the fold reached the run's own messages.
    plan = prepare_pass(
        state.config,
        state.limits,
        messages,
        reason=reason,  # type: ignore[arg-type]
        previous_record=state.active_record,
        created_by_run_id=None,
        notice_inputs=notice_inputs,
        call_instructions=call_instructions,
        untrusted_instructions=untrusted_instructions,
        allow_tool_batch_heads=state.allow_tool_batch_heads,
        elision_target_tokens=elision_target_tokens,
    )
    if plan is not None:
        # A fold that reaches into the current run's own messages is only valid while this run is;
        # one that covered only the history region stands on completed runs alone.
        if not plan.elision_only and plan.boundary_index is not None:
            plan.created_by_run_id = state.run_id if plan.boundary_index > state.first_own_message_index else None
    return plan


def _run_pass_sync(
    model: "Model",
    messages: List[Message],
    state: CompactionRunState,
    reason: str,
    run_metrics=None,
    **prepare_kwargs,
) -> Optional[CompactionRecord]:
    plan = _prepare(state, messages, reason, **prepare_kwargs)
    if plan is None:
        return None
    _emit(state, "started", reason=reason, tokens_before=plan.tokens_before)
    summarizer = _summarizer(model, state)
    try:
        record = complete_pass(
            plan,
            config=state.config,
            model=summarizer,
            summarizer_window=getattr(summarizer, "context_window", None),
            run_metrics=run_metrics,
        )
    except Exception as exc:
        log_error(f"Compaction pass failed; continuing with the uncompacted view: {exc}")
        return None
    if record.created_by_run_id and record.first_kept_run_id is None:
        record.first_kept_run_id = record.created_by_run_id
    _activate(state, record, messages)
    return record


async def _run_pass_async(
    model: "Model",
    messages: List[Message],
    state: CompactionRunState,
    reason: str,
    run_metrics=None,
    **prepare_kwargs,
) -> Optional[CompactionRecord]:
    plan = _prepare(state, messages, reason, **prepare_kwargs)
    if plan is None:
        return None
    _emit(state, "started", reason=reason, tokens_before=plan.tokens_before)
    summarizer = _summarizer(model, state)
    try:
        record = await acomplete_pass(
            plan,
            config=state.config,
            model=summarizer,
            summarizer_window=getattr(summarizer, "context_window", None),
            run_metrics=run_metrics,
        )
    except Exception as exc:
        log_error(f"Compaction pass failed; continuing with the uncompacted view: {exc}")
        return None
    if record.created_by_run_id and record.first_kept_run_id is None:
        record.first_kept_run_id = record.created_by_run_id
    _activate(state, record, messages)
    return record


def _adopt_finished_fold(state: CompactionRunState, messages: List[Message]) -> bool:
    """Activate a finished background fold at this loop-top. Never blocks.

    A record scoped to a different run's own messages is dropped: only its creating run may use
    or commit it."""
    handle = in_flight_fold(state.session_id, state.owner_id)
    if handle is None or not handle.done():
        return False
    clear_fold(state.session_id, state.owner_id, handle)
    if state.fold_future is handle:
        state.fold_future = None
    record = handle.record
    if record is None or (record.created_by_run_id is not None and record.created_by_run_id != state.run_id):
        return False
    _activate(state, record, messages)
    return True


def _start_background_fold(model: "Model", messages: List[Message], state: CompactionRunState, plan: PassPlan) -> None:
    handle = FoldHandle(plan=plan)
    if not register_fold(state.session_id, state.owner_id, handle):
        return
    _emit(state, "started", reason=plan.reason, tokens_before=plan.tokens_before, background=True)
    summarizer = _summarizer(model, state)
    window = getattr(summarizer, "context_window", None)
    config = state.config

    def _worker() -> None:
        try:
            handle.record = complete_pass(plan, config=config, model=summarizer, summarizer_window=window)
        except Exception as exc:
            handle.error = exc
            log_debug(f"Background compaction fold failed (will retry at the next trigger): {exc}")
        finally:
            handle.finished = True

    thread = threading.Thread(target=_worker, name="agno-compaction-fold", daemon=True)
    handle.thread = thread
    state.fold_future = handle
    thread.start()


def loop_top(model: "Model", messages: List[Message], state: CompactionRunState, run_response=None) -> None:
    """The threshold seam at the top of each loop iteration. Never raises."""
    try:
        _loop_top_shared(model, messages, state, run_response, async_mode=False)
    except Exception as exc:
        log_error(f"Compaction loop check failed; continuing uncompacted: {exc}")


async def aloop_top(model: "Model", messages: List[Message], state: CompactionRunState, run_response=None) -> None:
    """Async twin of loop_top."""
    try:
        run_metrics = getattr(run_response, "metrics", None)
        _maybe_refresh_limits(model, state)
        _adopt_finished_fold(state, messages)
        if state.scheduled:
            state.scheduled = False
            instructions = state.scheduled_instructions
            state.scheduled_instructions = None
            reading = state.gauge.reading(outbound_view(messages, state))
            # A requested pass shares the post-pass suppression window and the worth-it floor, so
            # a looping model cannot buy a summariser call per turn.
            if state.gauge.meets_floor(reading) and not (
                state.gauge.suppress_soft_below is not None and reading < state.gauge.suppress_soft_below
            ):
                await _run_pass_async(
                    model, messages, state, "requested", run_metrics=run_metrics, untrusted_instructions=instructions
                )
            return
        reading = state.gauge.reading(outbound_view(messages, state))
        if state.gauge.over_hard(reading) and state.gauge.meets_floor(reading):
            handle = in_flight_fold(state.session_id, state.owner_id)
            if handle is not None:
                await handle.ajoin()
                _adopt_finished_fold(state, messages)
                reading = state.gauge.reading(outbound_view(messages, state))
            if reading > state.limits.trigger_tokens:
                await _run_pass_async(model, messages, state, "threshold", run_metrics=run_metrics)
        elif (
            state.limits.soft_trigger_tokens is not None
            and state.gauge.over_soft(reading)
            and state.gauge.meets_floor(reading)
            and in_flight_fold(state.session_id, state.owner_id) is None
        ):
            plan = _prepare(state, messages, "threshold", elision_target_tokens=state.limits.soft_trigger_tokens)
            if plan is not None:
                if plan.elision_only:
                    record = complete_pass(plan, config=state.config, model=None)
                    _activate(state, record, messages)
                else:
                    _start_background_fold(model, messages, state, plan)
    except Exception as exc:
        log_error(f"Compaction loop check failed; continuing uncompacted: {exc}")


def _loop_top_shared(
    model: "Model", messages: List[Message], state: CompactionRunState, run_response, async_mode: bool
) -> None:
    run_metrics = getattr(run_response, "metrics", None)
    _maybe_refresh_limits(model, state)
    _adopt_finished_fold(state, messages)
    if state.scheduled:
        state.scheduled = False
        instructions = state.scheduled_instructions
        state.scheduled_instructions = None
        reading = state.gauge.reading(outbound_view(messages, state))
        # A requested pass shares the post-pass suppression window and the worth-it floor, so a
        # looping model cannot buy a summariser call per turn.
        if state.gauge.meets_floor(reading) and not (
            state.gauge.suppress_soft_below is not None and reading < state.gauge.suppress_soft_below
        ):
            _run_pass_sync(
                model, messages, state, "requested", run_metrics=run_metrics, untrusted_instructions=instructions
            )
        return
    reading = state.gauge.reading(outbound_view(messages, state))
    if state.gauge.over_hard(reading) and state.gauge.meets_floor(reading):
        handle = in_flight_fold(state.session_id, state.owner_id)
        if handle is not None and handle.thread is not None:
            handle.join()
            _adopt_finished_fold(state, messages)
            reading = state.gauge.reading(outbound_view(messages, state))
        if reading > state.limits.trigger_tokens:
            _run_pass_sync(model, messages, state, "threshold", run_metrics=run_metrics)
    elif (
        state.limits.soft_trigger_tokens is not None
        and state.gauge.over_soft(reading)
        and state.gauge.meets_floor(reading)
        and in_flight_fold(state.session_id, state.owner_id) is None
    ):
        plan = _prepare(state, messages, "threshold", elision_target_tokens=state.limits.soft_trigger_tokens)
        if plan is not None:
            if plan.elision_only:
                record = complete_pass(plan, config=state.config, model=None)
                _activate(state, record, messages)
            else:
                _start_background_fold(model, messages, state, plan)


def observe_provider_success(state: CompactionRunState, assistant_message: Message) -> None:
    state.gauge.observe_actual(assistant_message)
    state.overflow_attempted = False


def handle_overflow(model: "Model", messages: List[Message], state: CompactionRunState, run_response=None) -> bool:
    """Compact after a provider context-window error; True when the call should be retried once."""
    if state.overflow_attempted:
        return False
    state.overflow_attempted = True
    run_metrics = getattr(run_response, "metrics", None)
    handle = in_flight_fold(state.session_id, state.owner_id)
    if handle is not None and handle.thread is not None:
        handle.join()
        if _adopt_finished_fold(state, messages):
            return True
    record = _run_pass_sync(model, messages, state, "overflow", run_metrics=run_metrics)
    return record is not None


async def ahandle_overflow(
    model: "Model", messages: List[Message], state: CompactionRunState, run_response=None
) -> bool:
    """Async twin of handle_overflow."""
    if state.overflow_attempted:
        return False
    state.overflow_attempted = True
    run_metrics = getattr(run_response, "metrics", None)
    handle = in_flight_fold(state.session_id, state.owner_id)
    if handle is not None:
        await handle.ajoin()
        if _adopt_finished_fold(state, messages):
            return True
    record = await _run_pass_async(model, messages, state, "overflow", run_metrics=run_metrics)
    return record is not None
