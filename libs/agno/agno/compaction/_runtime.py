"""Compaction wired into a run, shared by Agent and Team.

Everything here reads only what both expose - ``compaction``, ``db``, ``model``, ``id``, the history
settings and ``system_message_role`` - so one implementation serves both. The few real differences
(which runs of a shared session are theirs, which session module loads it, which run events to
raise) are resolved by the small helpers at the top rather than by a second copy of the logic.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

from agno.compaction.manager import Compaction
from agno.models.message import Message
from agno.utils.log import log_info, log_warning


def _is_team(owner: Any) -> bool:
    from agno.team.team import Team

    return isinstance(owner, Team)


def _kind(owner: Any) -> str:
    return "team" if _is_team(owner) else "agent"


def _history_scope(owner: Any) -> Dict[str, Any]:
    """Which runs of a shared session belong to ``owner``.

    A member agent shares its team's session, and a nested team shares its parent's, so each
    filters to its own runs. A top-level owner reads the whole session.
    """
    if _is_team(owner):
        return {"team_id": owner.id} if owner.parent_team_id is not None else {}
    return {"agent_id": owner.id} if owner.team_id is not None else {}


def _session_api(owner: Any) -> Tuple[Any, type]:
    """The session module that loads ``owner``'s sessions, and the session type it returns."""
    if _is_team(owner):
        from agno.session import TeamSession
        from agno.team import _session as team_session

        return team_session, TeamSession
    from agno.agent import _session as agent_session
    from agno.session import AgentSession

    return agent_session, AgentSession


def resolve_compaction(owner: Any) -> None:
    """Resolve ``owner.compaction`` - an Agent's or a Team's - into the Compaction the run uses.

    ``True`` folds only when the provider rejects a request as too long. A proactive threshold
    is a guess about a number nobody can look up - no provider exposes its context window, and
    the same model id has different limits across deployments - so 150k is wrong for a 32k
    model and pointless for a 1M one. The rejection is the one signal that is always right, at
    the cost of a single failed request before the first fold.

    Pass a ``Compaction`` object to opt into the proactive threshold, which defaults to 150k
    there because someone configuring it has a size in mind.

    The model defaults to the owner's either way, so a bare ``compaction=True`` is still the
    cheapest correct configuration.
    """
    if owner.compaction is True:
        owner.compaction = Compaction(compact_at_tokens=None, on_context_overflow=True)
    elif owner.compaction is False:
        owner.compaction = None

    if isinstance(owner.compaction, Compaction) and owner.compaction.model is None:
        owner.compaction.model = owner.model


def stored_compaction(owner: Any, session: Any, up_to_run_id: Optional[str] = None) -> Optional[Any]:
    """The compaction in force for this run.

    Read from the record table rather than from a value on the session: records are immutable
    facts about single runs, so two containers writing different runs never clobber one another,
    and a resumed run can resolve the fold it actually saw.
    """
    from agno.compaction.types import CompactionRecord

    compaction = getattr(owner, "compaction", None)
    if compaction is None:
        return None
    archive = compaction.archive_for(session.session_id, owner.db)
    if archive is None:
        return None
    row = archive.latest(up_to_run_id)
    if not row:
        return None
    try:
        return CompactionRecord.from_dict(row)
    except Exception as e:  # noqa: BLE001
        log_warning(f"Ignoring unreadable compaction record: {e}")
        return None


def compaction_as_of(run_response: Optional[Any]) -> Optional[str]:
    """The run whose fold this run must inherit, if it is resuming one.

    A fresh run returns None and takes the latest. A fork or regeneration returns the run it
    branched from, so it rebuilds the context that run actually had rather than one summarizing
    its own future.
    """
    if run_response is None:
        return None
    return getattr(run_response, "forked_from_run_id", None) or getattr(run_response, "regenerated_from", None)


def estimated_context_tokens(owner: Any, messages: List[Message], tools: Optional[List[Any]] = None) -> Optional[int]:
    """Local estimate for the model-bound context this compaction decision is about.

    RunMetrics.input_tokens is billing telemetry. It accumulates every model call in a tool loop,
    plus background and compaction model calls, so it can be much larger than any single request
    the provider had to fit. ``compact_at_tokens`` is a context-size threshold, so use the current
    message view instead.
    """
    from agno.utils.tokens import count_tokens

    model_id = getattr(owner.model, "id", None) or "gpt-4o"
    try:
        return count_tokens(messages, tools=tools, model_id=model_id)
    except Exception as e:  # noqa: BLE001 - token estimation must never fail a run
        log_warning(f"Could not estimate tokens for compaction: {e}")
        return None


def compaction_inputs(
    owner: Any, messages: Optional[List[Message]] = None, tools: Optional[List[Any]] = None
) -> Dict[str, Any]:
    return {
        "context_tokens": estimated_context_tokens(owner, messages, tools) if messages is not None else None,
        "model": owner.model,
    }


def log_compaction(record: Any, inputs: Dict[str, Any]) -> None:
    """Report what one fold achieved. Sizes were measured when the record was built."""
    detail = f"Compacted {record.messages_compacted} messages"
    if record.tokens_before and record.tokens_after:
        saved = record.tokens_before - record.tokens_after
        detail += f" ({record.tokens_before} -> {record.tokens_after} tokens, saved {saved})"
    if record.archived:
        detail += ", originals archived"
    log_info(detail)


def compaction_events(run_response: Optional[Any], record: Any, started: bool = False) -> List[Any]:
    """The events one compaction raises, when there is a run to attach them to."""
    if run_response is None:
        return []
    from agno.run.team import TeamRunOutput
    from agno.utils.events import (
        create_compaction_completed_event,
        create_compaction_started_event,
        create_team_compaction_completed_event,
        create_team_compaction_started_event,
    )

    team = isinstance(run_response, TeamRunOutput)
    if started:
        start = create_team_compaction_started_event if team else create_compaction_started_event
        return [start(from_run_response=run_response)]
    complete = create_team_compaction_completed_event if team else create_compaction_completed_event
    return [
        complete(
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
PLANNER_WINDOW_MAX_RUNS = 500


def compaction_history_runs(owner: Any) -> Optional[int]:
    """How many runs the compaction planner may read, or None for no extra limit.

    num_history_runs governs how much history a RUN replays and defaults to 3. Compaction folds
    what sits in FRONT of the kept tail, so a 3-run window leaves it nothing to fold and it never
    fires - and worse, an anchor outside that window cannot resolve, which drops the summary
    silently along with the turns it replaced.

    So the planner reads its own window. Bounded, not unlimited: capped so a long session costs
    no more than a short one. Never narrower than num_history_runs, though - what a run sends is
    selected from what the planner reads. Reading wider changes nothing the model is sent, so a
    window the user chose needs no special case.
    """
    if getattr(owner, "compaction", None) is None:
        return owner.num_history_runs
    return max(owner.num_history_runs or 0, PLANNER_WINDOW_MAX_RUNS)


def history_for_run(
    owner: Any, session: Any, run_response: Optional[Any], skip_role: Optional[str]
) -> Tuple[List[Message], Any, Optional[Set[str]]]:
    """The history a run works from, the fold in force for it, and the ids of the messages
    num_history_runs and num_history_messages replay.

    Both of those are replay settings: they bound what a run sends before the first fold, not
    what compaction may read. The planner reads a wider window, and once a fold exists its anchor
    has to be in what is read, however old it is - the view replays the summary and everything
    from the anchor onward, and an anchor that is not found drops the summary along with the
    turns it replaced. Only the part from the anchor onward is kept - what sits in front of it is
    already folded.
    """

    def fetch(last_n_runs: Optional[int], limit: Optional[int]) -> List[Message]:
        return session.get_messages(
            last_n_runs=last_n_runs,
            limit=limit,
            skip_roles=[skip_role] if skip_role else None,
            **_history_scope(owner),
        )

    if getattr(owner, "compaction", None) is None:
        return fetch(owner.num_history_runs, owner.num_history_messages), None, None

    history = fetch(compaction_history_runs(owner), None)
    record = stored_compaction(owner, session, compaction_as_of(run_response))
    anchor = record.first_kept_message_id if record is not None and record.summary else None
    if anchor is not None and not any(m.id == anchor for m in history):
        everything = fetch(None, None)
        start = next((i for i, m in enumerate(everything) if m.id == anchor), None)
        if start is not None:
            history = everything[start:]

    replay = fetch(owner.num_history_runs, owner.num_history_messages)
    return history, record, {m.id for m in replay if m.id is not None}


def replayed_view(
    compaction: Any, history: List[Message], record: Any, replay_ids: Optional[Set[str]]
) -> List[Message]:
    """What a run sends from ``history``.

    Once a fold exists, the summary and everything from its anchor onward - the anchor has to be
    replayed, or the summary is dropped along with the turns it replaced. Before that, the
    num_history_runs window, exactly as without compaction.
    """
    if record is not None and record.summary and record.first_kept_message_id:
        if any(m.id == record.first_kept_message_id for m in history):
            return compaction.apply_record(history, record)
    if replay_ids is None:
        return history
    return [m for m in history if m.id in replay_ids]


def history_for_compaction(owner: Any, session: Any) -> List[Message]:
    """The history a manual compaction folds.

    Deliberately not limited by ``num_history_runs`` or ``num_history_messages``: those govern how
    much history a RUN replays, and applying them here would let them silently cap what compaction
    can ever see - the same starvation the automatic path guards against.
    """
    skip_role = owner.system_message_role if owner.system_message_role not in ["user", "assistant", "tool"] else None
    return session.get_messages(skip_roles=[skip_role] if skip_role else None, **_history_scope(owner))


def compaction_result(new_record: Any) -> Any:
    from agno.compaction.types import CompactionResult, CompactionStatus

    return CompactionResult(
        status=CompactionStatus.COMPACTED,
        message=(
            f"Compacted {new_record.messages_compacted} messages "
            f"({new_record.tokens_before} -> {new_record.tokens_after} tokens)."
        ),
        record=new_record,
    )


def compact_now(owner: Any, session: Any, history: List[Message]) -> Any:
    """Fold ``history`` now, without waiting for the size trigger.

    The explicit counterpart to the automatic path: same boundary, same guards, same archive.
    Only ``compact_at_tokens`` is bypassed - a caller asking to compact has supplied the
    judgement that threshold exists to make.

    Every other guard still applies, and a decline is reported rather than raised. The ratio
    guard in particular is not a preference: a summary costs a few hundred tokens whatever it
    replaces, so folding a smaller span leaves the context BIGGER while spending a model call
    and discarding the prompt-cache prefix. Declining is the correct outcome, and the returned
    status says so in terms a UI can show.
    """
    from agno.compaction.types import CompactionResult, CompactionStatus

    compaction = getattr(owner, "compaction", None)
    if compaction is None:
        return CompactionResult(
            status=CompactionStatus.NOT_ENABLED, message=f"Compaction is not enabled on this {_kind(owner)}."
        )
    if not history:
        return CompactionResult(status=CompactionStatus.NO_HISTORY, message="This session has no stored history yet.")

    record = stored_compaction(owner, session)
    boundary, status, reason = compaction.plan_with_reason(history, record)
    if boundary is None:
        return CompactionResult(status=status, message=reason)

    log_info("Compacting conversation history")
    inputs = compaction_inputs(owner, history)
    new_record = compaction.compact(
        history,
        session_id=session.session_id,
        db=owner.db,
        previous=record,
        tokens_before=inputs["context_tokens"],
    )
    if new_record is None:
        return CompactionResult(
            status=CompactionStatus.SUMMARY_FAILED,
            message="The summarizer returned nothing, so history was left unchanged.",
        )
    log_compaction(new_record, inputs)
    return compaction_result(new_record)


async def acompact_now(owner: Any, session: Any, history: List[Message]) -> Any:
    from agno.compaction.types import CompactionResult, CompactionStatus

    compaction = getattr(owner, "compaction", None)
    if compaction is None:
        return CompactionResult(
            status=CompactionStatus.NOT_ENABLED, message=f"Compaction is not enabled on this {_kind(owner)}."
        )
    if not history:
        return CompactionResult(status=CompactionStatus.NO_HISTORY, message="This session has no stored history yet.")

    record = stored_compaction(owner, session)
    boundary, status, reason = compaction.plan_with_reason(history, record)
    if boundary is None:
        return CompactionResult(status=status, message=reason)

    log_info("Compacting conversation history")
    inputs = compaction_inputs(owner, history)
    new_record = await compaction.acompact(
        history,
        session_id=session.session_id,
        db=owner.db,
        previous=record,
        tokens_before=inputs["context_tokens"],
    )
    if new_record is None:
        return CompactionResult(
            status=CompactionStatus.SUMMARY_FAILED,
            message="The summarizer returned nothing, so history was left unchanged.",
        )
    log_compaction(new_record, inputs)
    return compaction_result(new_record)


def compact_session(owner: Any, session_id: Optional[str] = None, user_id: Optional[str] = None) -> Any:
    from agno.compaction.types import CompactionResult, CompactionStatus

    if getattr(owner, "compaction", None) is None:
        # Answered before the session is loaded: it is true of every session, including one that
        # does not exist.
        return CompactionResult(
            status=CompactionStatus.NOT_ENABLED, message=f"Compaction is not enabled on this {_kind(owner)}."
        )
    session_module, session_type = _session_api(owner)
    session = session_module.get_session(owner, session_id=session_id, user_id=user_id)
    if session is None or not isinstance(session, session_type):
        return CompactionResult(status=CompactionStatus.NO_HISTORY, message="No such session.")
    return compact_now(owner, session, history_for_compaction(owner, session))


async def acompact_session(owner: Any, session_id: Optional[str] = None, user_id: Optional[str] = None) -> Any:
    from agno.compaction.types import CompactionResult, CompactionStatus

    if getattr(owner, "compaction", None) is None:
        # Answered before the session is loaded: it is true of every session, including one that
        # does not exist.
        return CompactionResult(
            status=CompactionStatus.NOT_ENABLED, message=f"Compaction is not enabled on this {_kind(owner)}."
        )
    session_module, session_type = _session_api(owner)
    session = await session_module.aget_session(owner, session_id=session_id, user_id=user_id)
    if session is None or not isinstance(session, session_type):
        return CompactionResult(status=CompactionStatus.NO_HISTORY, message="No such session.")
    return await acompact_now(owner, session, history_for_compaction(owner, session))


def recompact_after_overflow(
    owner: Any,
    session: Any,
    messages: Optional[List[Message]],
    run_response: Optional[Any] = None,
    tools: Optional[List[Any]] = None,
) -> bool:
    """Fold harder after the provider rejected a request as too long. True if the payload shrank.

    Nobody can know a model's context window ahead of time - no provider exposes it, and the
    same model id has different limits across deployments - so a threshold set in advance is
    always a guess. The rejection is the one authoritative signal that the guess was wrong, and
    this is the only path that can act on it.

    ``messages`` is the list the model call already holds, and is shrunk in place so the retry
    sends the folded payload.

    Folds against the messages actually sent, so it reaches spans the run-start pass could not:
    the current turn's input, and anything a tool loop appended since. The pair-safe boundary
    still applies - an unsendable payload is no improvement on a too-long one - but the fold
    ratio does not: the request has already failed, so a fold that merely helps beats the run
    dying.
    """
    from dataclasses import replace

    from agno.compaction._cut import leading_system_count
    from agno.compaction._tokens import estimate_tokens

    compaction = getattr(owner, "compaction", None)
    if compaction is None or not getattr(compaction, "on_context_overflow", False):
        return False

    if not messages:
        return False

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
        boundary = candidate.boundary_for(messages, min_index=lead)
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
        return False

    before = estimate_tokens(messages, tools)
    # min_fold_ratio is the run-start question - is this fold worth paying for. Here the request
    # has already been rejected, so any fold that shrinks it is worth making.
    record = replace(folder, min_fold_ratio=0, stats=compaction.stats).compact(
        messages,
        session_id=session.session_id,
        db=owner.db,
        previous=stored_compaction(owner, session),
        run_id=run_response.run_id if run_response is not None else None,
        tokens_before=before,
    )
    if record is None:
        return False

    compacted = compaction.apply_record(messages, record)
    after = estimate_tokens(compacted, tools)
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


def apply_compaction(
    owner: Any,
    session: Any,
    history: List[Message],
    record: Any,
    run_response: Optional[Any] = None,
    events: Optional[List[Any]] = None,
    context_prefix: Optional[List[Message]] = None,
    tools: Optional[List[Any]] = None,
    replay_ids: Optional[Set[str]] = None,
) -> List[Message]:
    """Replace the head of ``history`` with a summary once it grows too long.

    Returns the list to send to the model. ``history`` itself is not mutated,
    and what the session persists is never touched: compaction shortens the
    request, not the record.
    """
    compaction = getattr(owner, "compaction", None)
    if compaction is None or not history:
        return history

    # A stored compaction is replayed rather than recomputed, so the summary is
    # paid for once and the prompt prefix stays stable between runs. The trigger
    # measures this - what is actually sent - not the planner's wider read.
    in_context = replayed_view(compaction, history, record, replay_ids)

    prefix = context_prefix or []
    inputs = compaction_inputs(owner, prefix + in_context, tools)
    if not compaction.should_compact(in_context, **inputs):
        return in_context

    # Announce only once the guards have passed. should_compact cannot see the
    # pair-safe boundary or the size floor, so announcing on it alone reports
    # compactions that then never happen.
    if compaction.plan(history, record) is None:
        return in_context

    log_info("Auto-compacting conversation history")
    if events is not None:
        events.extend(compaction_events(run_response, None, started=True))

    # Compact against the FULL history, so the boundary the record stores is an
    # absolute index into it. A boundary measured on the already-compacted list
    # would advance by only one message per run, so the context would never
    # actually shrink and every later run would compact again.
    new_record = compaction.compact(
        history,
        session_id=session.session_id,
        db=owner.db,
        previous=record,
        run_metrics=run_response.metrics if run_response is not None else None,
        tokens_before=inputs["context_tokens"],
        run_id=run_response.run_id if run_response is not None else None,
        context_prefix=prefix,
    )
    if new_record is None:
        return in_context

    compacted = compaction.apply_record(history, new_record)
    # Measure before storing, so the persisted record carries the real sizes.
    log_compaction(new_record, inputs)
    # Surface it on the run, so `run.compaction` reports what happened here.
    if run_response is not None:
        run_response.compaction = new_record
    if events is not None:
        events.extend(compaction_events(run_response, new_record))
    return compacted


async def aapply_compaction(
    owner: Any,
    session: Any,
    history: List[Message],
    record: Any,
    run_response: Optional[Any] = None,
    events: Optional[List[Any]] = None,
    context_prefix: Optional[List[Message]] = None,
    tools: Optional[List[Any]] = None,
    replay_ids: Optional[Set[str]] = None,
) -> List[Message]:
    compaction = getattr(owner, "compaction", None)
    if compaction is None or not history:
        return history

    in_context = replayed_view(compaction, history, record, replay_ids)

    prefix = context_prefix or []
    inputs = compaction_inputs(owner, prefix + in_context, tools)
    if not compaction.should_compact(in_context, **inputs):
        return in_context

    # Announce only once the guards have passed. should_compact cannot see the
    # pair-safe boundary or the size floor, so announcing on it alone reports
    # compactions that then never happen.
    if compaction.plan(history, record) is None:
        return in_context

    log_info("Auto-compacting conversation history")
    if events is not None:
        events.extend(compaction_events(run_response, None, started=True))

    # Compact against the FULL history so the stored boundary is absolute -
    # see the sync path for why a relative boundary never shrinks the context.
    new_record = await compaction.acompact(
        history,
        session_id=session.session_id,
        db=owner.db,
        previous=record,
        run_metrics=run_response.metrics if run_response is not None else None,
        tokens_before=inputs["context_tokens"],
        run_id=run_response.run_id if run_response is not None else None,
        context_prefix=prefix,
    )
    if new_record is None:
        return in_context

    compacted = compaction.apply_record(history, new_record)
    # Measure before storing, so the persisted record carries the real sizes.
    log_compaction(new_record, inputs)
    # Surface it on the run, so `run.compaction` reports what happened here.
    if run_response is not None:
        run_response.compaction = new_record
    if events is not None:
        events.extend(compaction_events(run_response, new_record))
    return compacted
