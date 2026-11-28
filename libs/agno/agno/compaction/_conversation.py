"""Compaction over one stored conversation, whoever holds it: an Agent or a Team.

The threshold, the cut, the summary, the stored record and the recovery after a rejected request
are the same for both. Two things differ and are passed in by the caller: how it reads its stored
messages (``fetch``) and which of the session's messages are its own (``own_message_ids``).
"""

from __future__ import annotations

from collections import Counter
from copy import copy as shallow_copy
from dataclasses import replace
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional, Sequence, Set, Tuple, Union

from agno.compaction._cut import leading_system_count
from agno.compaction._tokens import acount_request, count_request, estimate_tokens
from agno.compaction.compaction import Compaction
from agno.compaction.types import CompactionRecord, CompactionResult, CompactionStatus
from agno.metrics import RunMetrics, SessionMetrics, merge_background_metrics
from agno.models.message import Message
from agno.run.agent import RunOutput
from agno.run.base import RunStatus
from agno.utils.log import log_info, log_warning

if TYPE_CHECKING:
    from agno.agent.agent import Agent
    from agno.run.messages import RunMessages
    from agno.run.team import TeamRunOutput
    from agno.session import AgentSession, TeamSession
    from agno.team.team import Team

    CompactionOwner = Union[Agent, Team]
    CompactionSession = Union[AgentSession, TeamSession]
    CompactionRun = Union[RunOutput, TeamRunOutput]

# The ids of the messages in the caller's own conversation, with the live messages it is given
# added, or None when the session holds no other conversation. A Team and its members run in one
# session and compaction records are stored by session, so each reads only the records anchored
# on its own messages.
OwnMessageIds = Callable[[Optional[List[Message]]], Optional[Set[str]]]
# Reads the caller's stored messages: fetch(last_n_runs, limit).
Fetch = Callable[[Optional[int], Optional[int]], List[Message]]


def compaction_of(owner: "CompactionOwner") -> Optional["Compaction"]:
    """The Agent's or Team's Compaction, or None when compaction is off.

    set_compaction turns compaction=True into a Compaction at init, so anything else left on the
    field means compaction is off.
    """
    return owner.compaction if isinstance(owner.compaction, Compaction) else None


def message_ids_of(read: Callable[[], List[Message]], messages: Optional[List[Message]] = None) -> Set[str]:
    """The ids of the stored messages ``read`` returns, and of ``messages``.

    ``messages`` is a live message list, for a fold anchored inside the current run.
    """
    stored: List[Message] = []
    try:
        stored = read()
    except Exception as e:  # noqa: BLE001 - an unreadable session leaves only the live messages
        log_warning(f"Could not read the session's messages for compaction: {e}")
    return {m.id for m in [*stored, *(messages or [])] if m.id is not None}


def _runs_before(session: "CompactionSession", run_id: Optional[str]) -> Tuple[List[str], Optional[int]]:
    """The ids of the session's runs before ``run_id``, and when that run began.

    A run that made no fold inherited one from a run before it, so resolving the fold a run saw
    needs the runs that came first. Both are empty when the run is not in the session.
    """
    runs = getattr(session, "runs", None) or []
    index = next((i for i, run in enumerate(runs) if run_id is not None and run.run_id == run_id), None)
    if index is None:
        return [], None
    return [run.run_id for run in runs[:index] if run.run_id], getattr(runs[index], "created_at", None)


def _stored_compaction(
    owner: "CompactionOwner",
    session: "CompactionSession",
    up_to_run_id: Optional[str] = None,
    messages: Optional[List[Message]] = None,
    *,
    own_message_ids: OwnMessageIds,
) -> Optional[CompactionRecord]:
    """The compaction in force for this run.

    Read from the record table rather than from a value on the session: records are immutable
    facts about single runs, so two containers writing different runs never clobber one another,
    and a resumed run can resolve the fold it actually saw.
    """
    compaction = compaction_of(owner)
    if compaction is None:
        return None
    archive = compaction.archive_for(session.session_id, owner.db, message_ids=own_message_ids(messages))
    if archive is None:
        return None
    earlier_run_ids, started_at = _runs_before(session, up_to_run_id)
    row = archive.latest(up_to_run_id, earlier_run_ids=earlier_run_ids, started_at=started_at)
    if not row:
        return None
    try:
        return CompactionRecord.from_dict(row)
    except Exception as e:  # noqa: BLE001
        log_warning(f"Ignoring unreadable compaction record: {e}")
        return None


def _compaction_as_of(run_response: Optional["CompactionRun"]) -> Optional[str]:
    """The run whose fold this run must inherit, if it is resuming one.

    A fresh run returns None and takes the latest. A fork or regeneration returns the run it
    branched from, so it rebuilds the context that run actually had rather than one summarizing
    its own future.
    """
    if run_response is None:
        return None
    return getattr(run_response, "forked_from_run_id", None) or getattr(run_response, "regenerated_from", None)


def _estimated_context_tokens(
    owner: "CompactionOwner", messages: List[Message], tools: Optional[List[Any]] = None
) -> Optional[int]:
    """Local estimate for the model-bound context this compaction decision is about.

    RunMetrics.input_tokens is billing telemetry. It accumulates every model call in a tool loop,
    plus background and compaction model calls, so it can be much larger than any single request
    the provider had to fit. ``compact_at_tokens`` is a context-size threshold, so use the current
    message view instead.

    Counted by the model or ``Compaction.token_counter`` when one is chosen, and locally otherwise.
    """
    from agno.utils.tokens import count_tokens

    counted = count_request(_sync_counter(owner), messages, tools)
    if counted is not None:
        return counted
    model_id = getattr(owner.model, "id", None) or "gpt-4o"
    try:
        return count_tokens(messages, tools=tools, model_id=model_id)
    except Exception as e:  # noqa: BLE001 - token estimation must never fail a run
        log_warning(f"Could not estimate tokens for compaction: {e}")
        return None


def _compaction_inputs(
    owner: "CompactionOwner", messages: Optional[List[Message]] = None, tools: Optional[List[Any]] = None
) -> Dict[str, Any]:
    return {
        "context_tokens": _estimated_context_tokens(owner, messages, tools) if messages is not None else None,
        "model": owner.model,
    }


async def _acompaction_inputs(
    owner: "CompactionOwner", messages: Optional[List[Message]] = None, tools: Optional[List[Any]] = None
) -> Dict[str, Any]:
    """``_compaction_inputs`` for async runs, counting without blocking the event loop."""
    if messages is None:
        return _compaction_inputs(owner, messages, tools)
    counted = await _acount(owner, messages, tools)
    return {
        "context_tokens": counted if counted is not None else _estimated_context_tokens(owner, messages, tools),
        "model": owner.model,
    }


def _sync_counter(owner: "CompactionOwner") -> Any:
    """What counts a request in a sync run: the model's own count_tokens when use_model_token_count
    is set, else the token_counter, else nothing - the local estimate."""
    compaction = owner.compaction
    if getattr(compaction, "use_model_token_count", False) and owner.model is not None:
        return owner.model.count_tokens
    return getattr(compaction, "token_counter", None)


async def _acount(owner: "CompactionOwner", messages: List[Message], tools: Optional[List[Any]]) -> Optional[int]:
    """A request's count in an async run, or None to use the local estimate.

    The model's own count is awaited through acount_tokens. An async token_counter is awaited too;
    a sync one is usually a network call, so it runs in a worker thread rather than blocking the
    event loop.
    """
    compaction = owner.compaction
    if getattr(compaction, "use_model_token_count", False) and owner.model is not None:
        try:
            return int(await owner.model.acount_tokens(messages, tools))
        except Exception as e:  # noqa: BLE001 - counting is never worth failing a run
            log_warning(f"Compaction: the model's token count failed, using the local estimate instead: {e}")
            return None
    return await acount_request(getattr(compaction, "token_counter", None), messages, tools)


def _request_tokens(owner: "CompactionOwner", messages: List[Message], tools: Optional[List[Any]]) -> int:
    """A request's size for overflow recovery, counted the way the trigger counts it, so before and
    after are comparable."""
    counted = count_request(_sync_counter(owner), messages, tools)
    return counted if counted is not None else estimate_tokens(messages, tools)


async def _arequest_tokens(owner: "CompactionOwner", messages: List[Message], tools: Optional[List[Any]]) -> int:
    """``_request_tokens`` for async runs."""
    counted = await _acount(owner, messages, tools)
    return counted if counted is not None else estimate_tokens(messages, tools)


def _log_compaction(record: CompactionRecord) -> None:
    """Report what one fold achieved. Sizes were measured when the record was built."""
    detail = f"Compacted {record.messages_compacted} messages"
    if record.tokens_before and record.tokens_after:
        saved = record.tokens_before - record.tokens_after
        detail += f" ({record.tokens_before} -> {record.tokens_after} tokens, saved {saved})"
    if record.archived:
        detail += ", originals archived"
    log_info(detail)


def _compaction_events(
    run_response: Optional["CompactionRun"], record: Optional[CompactionRecord], started: bool = False
) -> List[Any]:
    """The events one compaction raises, when there is a run to attach them to. A Team's run raises
    the Team's events."""
    if run_response is None:
        return []
    from agno.utils.events import (
        create_compaction_completed_event,
        create_compaction_started_event,
        create_team_compaction_completed_event,
        create_team_compaction_started_event,
    )

    create_started: Any = create_compaction_started_event
    create_completed: Any = create_compaction_completed_event
    if not isinstance(run_response, RunOutput):
        create_started, create_completed = create_team_compaction_started_event, create_team_compaction_completed_event

    if started or record is None:
        return [create_started(from_run_response=run_response)]
    return [
        create_completed(
            from_run_response=run_response,
            messages_compacted=record.messages_compacted,
            tokens_before=record.tokens_before,
            tokens_after=record.tokens_after,
            archived=record.archived,
        )
    ]


# Headroom over compact_at_tokens for the planner's own window. The planner must see enough
# history to find a foldable span BEFORE the trigger fires, plus the tail it will keep; a window
# sized exactly at the trigger would leave nothing in front of the tail to fold.
_PLANNER_WINDOW_MAX_RUNS = 500


def _compaction_history_runs(owner: "CompactionOwner") -> Optional[int]:
    """How many runs the compaction planner may read, or None for no extra limit.

    num_history_runs governs how much history a RUN replays and defaults to 3. Compaction folds
    what sits in FRONT of the kept tail, so a 3-run window leaves it nothing to fold and it never
    fires - and worse, an anchor outside that window cannot resolve, which drops the summary
    silently along with the turns it replaced.

    So the planner reads its own window. Bounded, not unlimited: capped so a long session costs
    no more than a short one. Never narrower than num_history_runs, though.
    """
    if compaction_of(owner) is None:
        return owner.num_history_runs
    return max(owner.num_history_runs or 0, _PLANNER_WINDOW_MAX_RUNS)


def history_for_run(
    owner: "CompactionOwner",
    session: "CompactionSession",
    run_response: Optional["CompactionRun"],
    fetch: Fetch,
    *,
    own_message_ids: OwnMessageIds,
) -> Tuple[List[Message], Optional[CompactionRecord], Optional[Counter[str]]]:
    """The history a run works from, the fold in force for it, and the ids of the messages a run
    replays before the first fold - or None when it replays all of the history.
    ``fetch(last_n_runs, limit)`` reads the conversation's stored messages.

    With a compact_at_tokens threshold, compaction owns the window: everything since the last fold
    is replayed, so the trigger, the fold and its metrics measure what the model is sent. Without
    one, num_history_runs and num_history_messages still bound the replay before the first fold,
    since nothing else would stop it growing. The ids are counted - a fork copies its source run's
    messages with the same ids, so one id can stand for more than one message.

    Once a fold exists its anchor has to be in what is read, however old it is - the view replays
    the summary and everything from the anchor onward, and an anchor that is not found drops the
    summary along with the turns it replaced. What sits in front of it is already folded.
    """
    compaction = compaction_of(owner)
    if compaction is None:
        return fetch(owner.num_history_runs, owner.num_history_messages), None, None

    history = fetch(_compaction_history_runs(owner), None)
    # A continued or regenerated run brings its own messages, where a fold made inside it is anchored
    run_input = getattr(run_response, "messages", None) or []
    record = _stored_compaction(
        owner, session, _compaction_as_of(run_response), messages=run_input or None, own_message_ids=own_message_ids
    )
    anchor = record.first_kept_message_id if record is not None and record.summary else None
    if anchor is not None and not any(m.id == anchor for m in [*history, *run_input]):
        everything = fetch(None, None)
        start = next((i for i, m in enumerate(everything) if m.id == anchor), None)
        if start is not None:
            history = everything[start:]

    if compaction.compact_at_tokens is not None:
        # A threshold is the limit, so compaction owns the window: everything since the last fold
        # is replayed. Capping it at num_history_runs meant a threshold above a few turns never
        # fired, older turns fell out unsummarized, and the fold measured a list never sent.
        return history, record, None
    # No threshold - compaction=True, or manual folds only - so nothing would stop the replay
    # growing until the provider rejects a request. Keep num_history_runs until the first fold.
    replay = fetch(owner.num_history_runs, owner.num_history_messages)
    return history, record, Counter(m.id for m in replay if m.id is not None)


def replayed_history(
    owner: "CompactionOwner",
    history: List[Message],
    record: Optional[CompactionRecord],
    replay_ids: Optional[Counter[str]],
    run_input: Optional[List[Message]] = None,
) -> List[Message]:
    """What a continued run sends from ``history``: the stored fold replayed, never a new one.

    The run checked this same history before it paused, and its own messages are never folded.
    ``run_input`` is the continued run's own messages, which a fold made inside that run is
    anchored on. Without compaction the history comes back as it is.
    """
    compaction = compaction_of(owner)
    if compaction is None:
        return history
    return _replayed_view(compaction, history, record, replay_ids, run_input)


def _replayed_view(
    compaction: Compaction,
    history: List[Message],
    record: Optional[CompactionRecord],
    replay_ids: Optional[Counter[str]],
    run_input: Optional[List[Message]] = None,
) -> List[Message]:
    """What a run sends from ``history``.

    Once a fold exists, the summary and everything from its anchor onward - the anchor has to be
    replayed, or the summary is dropped along with the turns it replaced. When the anchor is in
    ``run_input`` instead, all of ``history`` sits in front of it, so the summary is sent alone.
    Before the first fold, the replay window when there is one, else all of ``history``.
    """
    if record is not None and record.summary and record.first_kept_message_id:
        anchor = record.first_kept_message_id
        if any(m.id == anchor for m in history):
            return compaction.apply_record(history, record)
        if any(m.id == anchor for m in run_input or []):
            # A stand-in for the anchor lets the view place the summary; the run's input follows it
            return compaction.apply_record([*history, Message(id=anchor, role="user")], record)[:-1]
    if replay_ids is None:
        return history
    # The window is the newest runs, so match it from the end, each id as many times as the window
    # holds it. A plain membership test would also let in a fork's source run from outside the
    # window, since the fork's copies share its message ids, and send those turns twice.
    remaining = Counter(replay_ids)
    kept: List[Message] = []
    for message in reversed(history):
        if message.id is not None and remaining[message.id] > 0:
            remaining[message.id] -= 1
            kept.append(message)
    kept.reverse()
    return kept


def _last_sent(
    owner: "CompactionOwner",
    session: "CompactionSession",
    compaction: Compaction,
    fetch: Fetch,
    own_message_ids: OwnMessageIds,
) -> List[Message]:
    """The history the model was last sent, which is what a fold's "before" size measures.

    A manual fold folds everything the planner reads, but without a threshold the model was only
    sent the num_history_runs window - recording the planner's read would overstate what the fold
    reclaimed from the context.
    """
    history, record, replay_ids = history_for_run(owner, session, None, fetch, own_message_ids=own_message_ids)
    return _replayed_view(compaction, history, record, replay_ids)


def _compaction_result(new_record: CompactionRecord, metrics: Optional[RunMetrics] = None) -> CompactionResult:
    return CompactionResult(
        status=CompactionStatus.COMPACTED,
        message=(
            f"Compacted {new_record.messages_compacted} messages "
            f"({new_record.tokens_before} -> {new_record.tokens_after} tokens)."
        ),
        record=new_record,
        metrics=metrics,
    )


def compact_history(
    owner: "CompactionOwner",
    session: "CompactionSession",
    history: List[Message],
    *,
    fetch: Fetch,
    own_message_ids: OwnMessageIds,
) -> CompactionResult:
    """Fold ``history`` now, without waiting for the size trigger.

    The explicit counterpart to the automatic path: same boundary, same guards, same archive.
    Only ``compact_at_tokens`` is bypassed - a caller asking to compact has supplied the
    judgement that threshold exists to make.

    ``fetch`` reads the caller's stored messages. It is used to work out the history the model
    was last sent, which is what the fold's "before" size measures.

    Every other guard still applies, and a decline is reported rather than raised. The ratio
    guard in particular is not a preference: a summary costs a few hundred tokens whatever it
    replaces, so folding a smaller span leaves the context BIGGER while spending a model call
    and discarding the prompt-cache prefix. Declining is the correct outcome, and the returned
    status says so in terms a UI can show.
    """
    compaction = compaction_of(owner)
    if compaction is None:
        # An Agent and a Team each report this in their own words before calling.
        return CompactionResult(status=CompactionStatus.NOT_ENABLED, message="Compaction is not enabled.")
    if not history:
        return CompactionResult(status=CompactionStatus.NO_HISTORY, message="This session has no stored history yet.")

    record = _stored_compaction(owner, session, own_message_ids=own_message_ids)
    boundary, status, reason = compaction.plan_with_reason(history, record)
    if boundary is None:
        return CompactionResult(status=status, message=reason)

    log_info("Compacting conversation history")
    # No run to add the summarizer's usage to, so it is collected here and returned.
    run_metrics = RunMetrics()
    new_record = compaction.compact(
        history,
        session_id=session.session_id,
        db=owner.db,
        user_id=session.user_id,
        previous=record,
        run_metrics=run_metrics,
        sent_messages=_last_sent(owner, session, compaction, fetch, own_message_ids),
    )
    metrics = run_metrics if run_metrics.details else None
    if new_record is None:
        return CompactionResult(
            status=CompactionStatus.SUMMARY_FAILED,
            message="The summarizer returned nothing, so history was left unchanged.",
            metrics=metrics,
        )
    _log_compaction(new_record)
    return _compaction_result(new_record, metrics)


async def acompact_history(
    owner: "CompactionOwner",
    session: "CompactionSession",
    history: List[Message],
    *,
    fetch: Fetch,
    own_message_ids: OwnMessageIds,
) -> CompactionResult:
    """Async variant of :func:`compact_history`."""
    compaction = compaction_of(owner)
    if compaction is None:
        # An Agent and a Team each report this in their own words before calling.
        return CompactionResult(status=CompactionStatus.NOT_ENABLED, message="Compaction is not enabled.")
    if not history:
        return CompactionResult(status=CompactionStatus.NO_HISTORY, message="This session has no stored history yet.")

    record = _stored_compaction(owner, session, own_message_ids=own_message_ids)
    boundary, status, reason = compaction.plan_with_reason(history, record)
    if boundary is None:
        return CompactionResult(status=status, message=reason)

    log_info("Compacting conversation history")
    # No run to add the summarizer's usage to, so it is collected here and returned.
    run_metrics = RunMetrics()
    new_record = await compaction.acompact(
        history,
        session_id=session.session_id,
        db=owner.db,
        user_id=session.user_id,
        previous=record,
        run_metrics=run_metrics,
        sent_messages=_last_sent(owner, session, compaction, fetch, own_message_ids),
    )
    metrics = run_metrics if run_metrics.details else None
    if new_record is None:
        return CompactionResult(
            status=CompactionStatus.SUMMARY_FAILED,
            message="The summarizer returned nothing, so history was left unchanged.",
            metrics=metrics,
        )
    _log_compaction(new_record)
    return _compaction_result(new_record, metrics)


def add_usage_to_latest_run(
    session: "CompactionSession", metrics: RunMetrics, is_own_run: Callable[[Any], bool]
) -> Optional[Any]:
    """Add a manual compaction's usage to the conversation's latest finished run, returned for saving.

    A manual compaction has no run of its own, so that run carries its model call. With no such run
    the usage is kept in the session's compaction metrics, which the session's metrics add to its
    runs'. ``is_own_run`` says which of the session's runs belong to the caller's conversation. The
    caller updates the session's metrics afterwards.
    """
    if session.session_data is None:
        session.session_data = {}
    runs = session.runs or []
    # A run that can still change, failed and running runs included, would drop the usage when it is saved again, and
    # a run copied into a forked session is counted in the session it was made in
    finished = [
        index
        for index, run in enumerate(runs)
        if is_own_run(run)
        and run.status in (RunStatus.completed, RunStatus.cancelled)
        and not run.forked_from_session_id
    ]
    if not finished:
        compaction_metrics = SessionMetrics.from_dict(session.session_data.get("compaction_metrics") or {})
        compaction_metrics.accumulate_from_run(metrics)
        session.session_data["compaction_metrics"] = compaction_metrics.to_dict()
        return None
    # Update a copy, never the loaded run: history run objects are shared between reads of the same session
    latest_run = shallow_copy(runs[finished[-1]])
    latest_run.metrics = RunMetrics.from_dict(latest_run.metrics.to_dict()) if latest_run.metrics else RunMetrics()
    merge_background_metrics(latest_run.metrics, [metrics])
    runs[finished[-1]] = latest_run
    return latest_run


def _plan_overflow_fold(
    owner: "CompactionOwner", run_messages: "RunMessages"
) -> Optional[Tuple[Compaction, Compaction, List[Message]]]:
    """Where to cut after a context-window rejection: the Compaction, the variant that folds, and
    the message list the model call holds. None when there is nothing to do or no safe cut.

    Shared by the sync and async recovery, which differ only in how the summarizer is called.
    """
    compaction = compaction_of(owner)
    if compaction is None or not getattr(compaction, "on_context_overflow", False):
        return None

    messages = getattr(run_messages, "messages", None)
    if not messages:
        return None

    lead = leading_system_count(messages)
    # Keep the configured tail when it works. Only when folding in front of it reclaims too
    # little to be worth retrying - an oversized turn sitting INSIDE the tail, which no cut in
    # front of it can reach - is the tail given up, one run at a time. The request has already
    # been rejected, so a smaller tail beats no answer, but the setting is still the default.
    folder, chosen_keep = None, compaction.uncompacted_runs
    # A token tail is sized, not counted, so there is no run count to give up - only a run-count
    # tail is shrunk. Varying uncompacted_runs alongside uncompacted_tokens is not a valid config.
    if compaction.uncompacted_tokens is not None:
        tails: Sequence[Optional[int]] = [compaction.uncompacted_runs]
    else:
        tails = range(compaction.uncompacted_runs or 1, 0, -1)
    for keep in tails:
        if keep == compaction.uncompacted_runs:
            candidate = compaction
        else:
            candidate = replace(compaction, uncompacted_runs=keep, stats=compaction.stats)
        boundary = candidate.boundary_for(messages, min_index=lead, overhead_tokens=estimate_tokens(messages[:lead]))
        if boundary is None or boundary <= lead:
            continue
        folder, chosen_keep = candidate, keep
        # Stop as soon as the fold is large enough to be worth a summarizer call, rather than
        # shrinking the tail further than the rejection requires.
        if estimate_tokens(messages[lead:boundary]) >= estimate_tokens(messages[boundary:]):
            break
    if folder is not None and chosen_keep != compaction.uncompacted_runs:
        log_info(
            f"Compaction: keeping {chosen_keep} run(s) instead of {compaction.uncompacted_runs} - "
            f"the request was rejected as too long, and the configured tail leaves too little "
            f"in front of it to fold."
        )
    if folder is None:
        log_warning(
            "Compaction: the request exceeded the model's context window and there is no safe "
            "cut left to make - the most recent turn alone is too large to send. Shorten what "
            "it produces, or use a model with a larger context window."
        )
        return None
    return compaction, folder, messages


def _finish_overflow_fold(
    messages: List[Message],
    record: CompactionRecord,
    compacted: List[Message],
    before: int,
    after: int,
    run_response: Optional["CompactionRun"],
) -> bool:
    """Apply a fold made after a rejection to the list the model call holds. True if it shrank."""
    if after >= before:
        # A summary has a floor cost, so a fold that reclaims nothing leaves the request no
        # more sendable than it was. Retrying an identical payload just fails twice.
        log_warning(
            f"Compaction: folding after a context-window rejection did not shrink the request "
            f"({before} -> {after} tokens), so it is not worth retrying."
        )
        return False

    # Mutate the list in place rather than rebinding it. The caller has already passed this
    # exact list object into the model call's kwargs, so a new list would leave the retry
    # sending the payload that was just rejected.
    messages[:] = compacted
    if run_response is not None:
        run_response.compaction = record
    log_info(
        f"Compaction: request exceeded the context window, folded {record.messages_compacted} "
        f"messages ({before} -> {after} tokens) and retrying once."
    )
    return True


def _overflow_fold_kwargs(
    owner: "CompactionOwner",
    session: "CompactionSession",
    run_response: Optional["CompactionRun"],
    before: int,
    messages: List[Message],
    own_message_ids: OwnMessageIds,
) -> Dict[str, Any]:
    return dict(
        session_id=session.session_id,
        db=owner.db,
        user_id=session.user_id,
        previous=_stored_compaction(owner, session, messages=messages, own_message_ids=own_message_ids),
        run_id=run_response.run_id if run_response is not None else None,
        run_metrics=run_response.metrics if run_response is not None else None,
        tokens_before=before,
        # The leading system messages are part of the list being folded; counting them keeps the
        # cut the same as the one the overflow planner chose.
        overhead_tokens=estimate_tokens(messages[: leading_system_count(messages)]),
    )


def recompact_after_overflow(
    owner: "CompactionOwner",
    session: "CompactionSession",
    run_messages: "RunMessages",
    run_response: Optional["CompactionRun"] = None,
    tools: Optional[List[Any]] = None,
    *,
    own_message_ids: OwnMessageIds,
) -> bool:
    """Fold harder after the provider rejected a request as too long. True if the payload shrank.

    Nobody can know a model's context window ahead of time - no provider exposes it, and the
    same model id has different limits across deployments - so a threshold set in advance is
    always a guess. The rejection is the one authoritative signal that the guess was wrong, and
    this is the only path that can act on it.

    Folds against the messages actually sent, so it reaches spans the run-start pass could not:
    the current turn's input, and anything a tool loop appended since. The pair-safe boundary
    still applies - an unsendable payload is no improvement on a too-long one - but the fold
    ratio does not: the request has already failed, so a fold that merely helps beats the run
    dying.
    """
    plan = _plan_overflow_fold(owner, run_messages)
    if plan is None:
        return False
    compaction, folder, messages = plan
    before = _request_tokens(owner, messages, tools)
    # min_fold_ratio is the run-start question - is this fold worth paying for. Here the request
    # has already been rejected, so any fold that shrinks it is worth making.
    record = replace(folder, min_fold_ratio=0, stats=compaction.stats).compact(
        messages, **_overflow_fold_kwargs(owner, session, run_response, before, messages, own_message_ids)
    )
    if record is None:
        return False
    compacted = compaction.apply_record(messages, record)
    after = _request_tokens(owner, compacted, tools)
    return _finish_overflow_fold(messages, record, compacted, before, after, run_response)


async def arecompact_after_overflow(
    owner: "CompactionOwner",
    session: "CompactionSession",
    run_messages: "RunMessages",
    run_response: Optional["CompactionRun"] = None,
    tools: Optional[List[Any]] = None,
    *,
    own_message_ids: OwnMessageIds,
) -> bool:
    """Async variant of :func:`recompact_after_overflow`. The summarizer is awaited, so a recovery
    on the async path does not block the event loop for the length of a model call."""
    plan = _plan_overflow_fold(owner, run_messages)
    if plan is None:
        return False
    compaction, folder, messages = plan
    before = await _arequest_tokens(owner, messages, tools)
    record = await replace(folder, min_fold_ratio=0, stats=compaction.stats).acompact(
        messages, **_overflow_fold_kwargs(owner, session, run_response, before, messages, own_message_ids)
    )
    if record is None:
        return False
    compacted = compaction.apply_record(messages, record)
    after = await _arequest_tokens(owner, compacted, tools)
    return _finish_overflow_fold(messages, record, compacted, before, after, run_response)


def apply_compaction(
    owner: "CompactionOwner",
    session: "CompactionSession",
    history: List[Message],
    record: Optional[CompactionRecord],
    run_response: Optional["CompactionRun"] = None,
    events: Optional[List[Any]] = None,
    context_prefix: Optional[List[Message]] = None,
    tools: Optional[List[Any]] = None,
    replay_ids: Optional[Counter[str]] = None,
) -> List[Message]:
    """Replace the head of ``history`` with a summary once it grows too long.

    Returns the list to send to the model. ``history`` itself is not mutated,
    and what the session persists is never touched: compaction shortens the
    request, not the record.
    """
    compaction = compaction_of(owner)
    if compaction is None or not history:
        return history

    # A stored compaction is replayed rather than recomputed, so the summary is
    # paid for once and the prompt prefix stays stable between runs. The trigger
    # measures this - what is actually sent - not the planner's wider read.
    in_context = _replayed_view(compaction, history, record, replay_ids)

    prefix = context_prefix or []
    # Size is the only automatic trigger. Without a threshold nothing would read a count, so none
    # is taken - whatever does the counting, and the model's own count is a network call.
    if compaction.compact_at_tokens is None:
        return in_context
    inputs = _compaction_inputs(owner, prefix + in_context, tools)
    if not compaction.should_compact(in_context, **inputs):
        return in_context

    # Announce only once the guards have passed. should_compact cannot see the
    # pair-safe boundary or the size floor, so announcing on it alone reports
    # compactions that then never happen.
    # The system prompt and tools share the threshold with whatever the fold keeps.
    overhead = estimate_tokens(prefix, tools) if (prefix or tools) else 0
    if compaction.plan(history, record, overhead) is None:
        return in_context

    log_info("Auto-compacting conversation history")
    if events is not None:
        events.extend(_compaction_events(run_response, None, started=True))

    # Compact against the FULL history, so the boundary the record stores is an
    # absolute index into it. A boundary measured on the already-compacted list
    # would advance by only one message per run, so the context would never
    # actually shrink and every later run would compact again.
    new_record = compaction.compact(
        history,
        session_id=session.session_id,
        db=owner.db,
        user_id=session.user_id,
        previous=record,
        run_metrics=run_response.metrics if run_response is not None else None,
        tokens_before=inputs["context_tokens"],
        run_id=run_response.run_id if run_response is not None else None,
        context_prefix=prefix,
        overhead_tokens=overhead,
        # Once a fold exists the model is sent the summary and the anchor onward, not every turn the
        # planner reads, so that is what "before" measures.
        sent_messages=in_context,
    )
    if new_record is None:
        return in_context

    compacted = compaction.apply_record(history, new_record)
    # Measure before storing, so the persisted record carries the real sizes.
    _log_compaction(new_record)
    # Surface it on the run, so `run.compaction` reports what happened here.
    if run_response is not None:
        run_response.compaction = new_record
    if events is not None:
        events.extend(_compaction_events(run_response, new_record))
    return compacted


async def aapply_compaction(
    owner: "CompactionOwner",
    session: "CompactionSession",
    history: List[Message],
    record: Optional[CompactionRecord],
    run_response: Optional["CompactionRun"] = None,
    events: Optional[List[Any]] = None,
    context_prefix: Optional[List[Message]] = None,
    tools: Optional[List[Any]] = None,
    replay_ids: Optional[Counter[str]] = None,
) -> List[Message]:
    """Async variant of :func:`apply_compaction`."""
    compaction = compaction_of(owner)
    if compaction is None or not history:
        return history

    in_context = _replayed_view(compaction, history, record, replay_ids)

    prefix = context_prefix or []
    # Size is the only automatic trigger. Without a threshold nothing would read a count, so none
    # is taken - whatever does the counting, and the model's own count is a network call.
    if compaction.compact_at_tokens is None:
        return in_context
    inputs = await _acompaction_inputs(owner, prefix + in_context, tools)
    if not compaction.should_compact(in_context, **inputs):
        return in_context

    # Announce only once the guards have passed. should_compact cannot see the
    # pair-safe boundary or the size floor, so announcing on it alone reports
    # compactions that then never happen.
    # The system prompt and tools share the threshold with whatever the fold keeps.
    overhead = estimate_tokens(prefix, tools) if (prefix or tools) else 0
    if compaction.plan(history, record, overhead) is None:
        return in_context

    log_info("Auto-compacting conversation history")
    if events is not None:
        events.extend(_compaction_events(run_response, None, started=True))

    # Compact against the FULL history so the stored boundary is absolute -
    # see the sync path for why a relative boundary never shrinks the context.
    new_record = await compaction.acompact(
        history,
        session_id=session.session_id,
        db=owner.db,
        user_id=session.user_id,
        previous=record,
        run_metrics=run_response.metrics if run_response is not None else None,
        tokens_before=inputs["context_tokens"],
        run_id=run_response.run_id if run_response is not None else None,
        context_prefix=prefix,
        overhead_tokens=overhead,
        # Once a fold exists the model is sent the summary and the anchor onward, not every turn the
        # planner reads, so that is what "before" measures.
        sent_messages=in_context,
    )
    if new_record is None:
        return in_context

    compacted = compaction.apply_record(history, new_record)
    # Measure before storing, so the persisted record carries the real sizes.
    _log_compaction(new_record)
    # Surface it on the run, so `run.compaction` reports what happened here.
    if run_response is not None:
        run_response.compaction = new_record
    if events is not None:
        events.extend(_compaction_events(run_response, new_record))
    return compacted
