"""Conversation compaction for a Team.

What is compacted is the team leader's conversation: the messages of the Team's own runs, which
hold the person's messages, the leader's answers and its tool calls and results. A member's answer
is in there as the result of the delegation call. A member's own runs are not compacted here.

The threshold, the cut, the summary, the stored record and the search tool are the ones an Agent
uses, from ``agno.compaction``. This module holds only what differs for a Team: how the leader's
history is read, which stored messages are the leader's, the events a Team raises, the message a
Team adds to a run without storing it, and the session a manual compaction saves its usage to.
"""

from __future__ import annotations

from collections import Counter
from functools import partial
from typing import TYPE_CHECKING, Any, Callable, List, Optional, Set, Tuple, cast

from agno.compaction import _conversation
from agno.metrics import RunMetrics, SessionMetrics, merge_background_metrics
from agno.models.message import Message
from agno.run.base import RunStatus
from agno.run.team import TeamRunOutput
from agno.session import TeamSession
from agno.session._utils import resolve_run_index
from agno.utils.log import log_warning

if TYPE_CHECKING:
    from agno.compaction.types import CompactionResult
    from agno.team.team import Team

__all__ = [
    "aapply_compaction",
    "acompact_session",
    "apply_compaction",
    "arecompact_after_overflow",
    "compact_session",
    "history_for_run",
    "recompact_after_overflow",
    "replayed_history",
    "search_tools",
]


def _skip_role(team: "Team") -> Optional[str]:
    """The system role, when it is not a conversation role: history never replays it."""
    return team.system_message_role if team.system_message_role not in ["user", "assistant", "tool"] else None


def _fetch(team: "Team", session: TeamSession) -> Callable[[Optional[int], Optional[int]], List[Message]]:
    """Reads the team leader's stored messages, the way a run without compaction reads its history."""
    skip_role = _skip_role(team)

    def fetch(last_n_runs: Optional[int], limit: Optional[int]) -> List[Message]:
        return session.get_messages(
            last_n_runs=last_n_runs,
            limit=limit,
            skip_roles=[skip_role] if skip_role else None,
            team_id=team.id if team.parent_team_id is not None else None,
        )

    return fetch


def _own_message_ids(team: "Team", session: TeamSession, messages: Optional[List[Message]] = None) -> Set[str]:
    """The ids of the messages in the leader's conversation.

    A Team and its members run in one session, and compaction records are stored by session. The
    leader reads only the records anchored on its own messages, so it never replays a member's
    fold. ``messages`` adds a live message list, for a fold anchored inside the current run.
    """
    return _conversation.message_ids_of(
        lambda: session.get_messages(team_id=team.id if team.parent_team_id is not None else None), messages
    )


def _compaction_events(run_response: Optional[TeamRunOutput], record: Any, started: bool = False) -> List[Any]:
    """The events one compaction raises, when there is a run to attach them to."""
    from agno.utils.events import create_team_compaction_completed_event, create_team_compaction_started_event

    return _conversation.build_compaction_events(
        run_response, record, started, create_team_compaction_started_event, create_team_compaction_completed_event
    )


def history_for_run(
    team: "Team", session: TeamSession, run_response: Optional[TeamRunOutput]
) -> Tuple[List[Message], Any, Optional[Counter[str]]]:
    """The history a run of the Team works from, the fold in force for it, and the replay window.

    Without compaction this is the history a Team has always read: ``num_history_runs`` and
    ``num_history_messages`` of the leader's messages, with no fold and no window.
    """
    return _conversation.history_from(
        team, session, run_response, _fetch(team, session), own_message_ids=partial(_own_message_ids, team, session)
    )


def apply_compaction(
    team: "Team",
    session: TeamSession,
    history: List[Message],
    record: Any,
    run_response: Optional[TeamRunOutput] = None,
    events: Optional[List[Any]] = None,
    context_prefix: Optional[List[Message]] = None,
    tools: Optional[List[Any]] = None,
    replay_ids: Optional[Counter[str]] = None,
) -> List[Message]:
    """Replace the head of the leader's ``history`` with a summary once it grows too long."""
    return _conversation.apply_compaction(
        team,
        session,
        history,
        record,
        run_response,
        events=events,
        context_prefix=context_prefix,
        tools=tools,
        replay_ids=replay_ids,
        compaction_events=_compaction_events,
    )


async def aapply_compaction(
    team: "Team",
    session: TeamSession,
    history: List[Message],
    record: Any,
    run_response: Optional[TeamRunOutput] = None,
    events: Optional[List[Any]] = None,
    context_prefix: Optional[List[Message]] = None,
    tools: Optional[List[Any]] = None,
    replay_ids: Optional[Counter[str]] = None,
) -> List[Message]:
    """Async variant of :func:`apply_compaction`."""
    return await _conversation.aapply_compaction(
        team,
        session,
        history,
        record,
        run_response,
        events=events,
        context_prefix=context_prefix,
        tools=tools,
        replay_ids=replay_ids,
        compaction_events=_compaction_events,
    )


def replayed_history(team: "Team", history: List[Message], record: Any, replay_ids: Optional[Counter[str]]) -> Any:
    """What a continued run sends from ``history``: the stored fold replayed, never a new one.

    The run checked this same history before it paused, and its own messages are never folded.
    """
    compaction = _conversation.compaction_of(team)
    if compaction is None:
        return history
    return _conversation.replayed_view(compaction, history, record, replay_ids)


def search_tools(team: "Team", session: TeamSession) -> List[Any]:
    """The tool that searches what this conversation compacted away.

    Offered before the first fold too: the tools of a run are built before the run folds, and the
    summary it is then sent says to search. Bound to this session and to the leader's own folds:
    a member that compacts in the same session keeps its folds to itself.
    """
    compaction = _conversation.compaction_of(team)
    if compaction is None or not compaction.search_compacted_messages:
        return []
    ids = _own_message_ids(team, session)
    return compaction.tools_for(session.session_id, team.db, message_ids=ids, before_first_fold=True) or []


def _is_unstored_input(message: Message) -> bool:
    """A message the Team added to this run and does not store, such as the work a conversation started.

    It is state for this turn only. Folded, it would be summarized and stored with the
    conversation, and the model would lose the current copy.
    """
    return message.role == "user" and not message.add_to_agent_memory and not message.from_history


def _take_out_unstored_input(messages: Optional[List[Message]]) -> List[Tuple[Message, Optional[str]]]:
    """Remove the unstored input from the live list. Returns each with the id of the message after it."""
    taken: List[Tuple[Message, Optional[str]]] = []
    if not messages:
        return taken
    for index in range(len(messages) - 1, -1, -1):
        if _is_unstored_input(messages[index]):
            following = messages[index + 1].id if index + 1 < len(messages) else None
            taken.append((messages.pop(index), following))
    taken.reverse()
    return taken


def _put_back_unstored_input(messages: Optional[List[Message]], taken: List[Tuple[Message, Optional[str]]]) -> None:
    """Put each message back in front of the one it came before. That one is in the newest exchange,
    which a fold never removes."""
    if messages is None:
        return
    for message, following in taken:
        index = next((i for i, m in enumerate(messages) if following is not None and m.id == following), None)
        messages.insert(len(messages) if index is None else index, message)


def recompact_after_overflow(
    team: "Team",
    session: TeamSession,
    run_messages: Any,
    run_response: Optional[TeamRunOutput] = None,
    tools: Optional[List[Any]] = None,
) -> bool:
    """Fold the leader's live messages after the provider rejected a request as too long. True if it shrank."""
    if _conversation.compaction_of(team) is None:
        return False
    messages = getattr(run_messages, "messages", None)
    taken = _take_out_unstored_input(messages)
    try:
        return _conversation.recompact_after_overflow(
            team, session, run_messages, run_response, tools, own_message_ids=partial(_own_message_ids, team, session)
        )
    finally:
        _put_back_unstored_input(messages, taken)


async def arecompact_after_overflow(
    team: "Team",
    session: TeamSession,
    run_messages: Any,
    run_response: Optional[TeamRunOutput] = None,
    tools: Optional[List[Any]] = None,
) -> bool:
    """Async variant of :func:`recompact_after_overflow`."""
    if _conversation.compaction_of(team) is None:
        return False
    messages = getattr(run_messages, "messages", None)
    taken = _take_out_unstored_input(messages)
    try:
        return await _conversation.arecompact_after_overflow(
            team, session, run_messages, run_response, tools, own_message_ids=partial(_own_message_ids, team, session)
        )
    finally:
        _put_back_unstored_input(messages, taken)


# ---------------------------------------------------------------------------
# Manual compaction
# ---------------------------------------------------------------------------


def _history_for_compaction(team: "Team", session: TeamSession) -> List[Message]:
    """The history a manual compaction folds: all of the leader's, whatever a run would replay."""
    return _fetch(team, session)(None, None)


def _last_sent(team: "Team", session: TeamSession) -> List[Message]:
    """The history the leader was last sent, which is what a fold's "before" size measures."""
    history, record, replay_ids = history_for_run(team, session, None)
    return _conversation.replayed_view(_conversation.compaction_of(team), history, record, replay_ids)


def _not_enabled() -> "CompactionResult":
    from agno.compaction.types import CompactionResult, CompactionStatus

    return CompactionResult(status=CompactionStatus.NOT_ENABLED, message="Compaction is not enabled on this team.")


def _no_session() -> "CompactionResult":
    from agno.compaction.types import CompactionResult, CompactionStatus

    return CompactionResult(status=CompactionStatus.NO_HISTORY, message="No such session.")


def _add_to_session_and_latest_run(team: "Team", session: TeamSession, metrics: RunMetrics) -> Optional[TeamRunOutput]:
    """Add a manual compaction's usage to the leader's latest finished run, returned for saving, and to
    the session's metrics. With no such run it is kept in the session's compaction metrics."""
    from copy import copy as shallow_copy

    from agno.team._session import update_session_metrics

    if session.session_data is None:
        session.session_data = {}
    runs = session.runs or []
    # A run that can still change would drop the usage when it is saved again
    finished = [
        index
        for index, run in enumerate(runs)
        if isinstance(run, TeamRunOutput)
        and run.parent_run_id is None
        and run.status in (RunStatus.completed, RunStatus.cancelled)
    ]
    latest_run = None
    if finished:
        # Update a copy, never the loaded run: history run objects are shared between reads of the same session
        latest_run = cast(TeamRunOutput, shallow_copy(runs[finished[-1]]))
        latest_run.metrics = RunMetrics.from_dict(latest_run.metrics.to_dict()) if latest_run.metrics else RunMetrics()
        merge_background_metrics(latest_run.metrics, [metrics])
        runs[finished[-1]] = latest_run
    else:
        compaction_metrics = SessionMetrics.from_dict(session.session_data.get("compaction_metrics") or {})
        compaction_metrics.accumulate_from_run(metrics)
        session.session_data["compaction_metrics"] = compaction_metrics.to_dict()

    update_session_metrics(team, session=session)
    return latest_run


def compact_session(
    team: "Team", session_id: Optional[str] = None, user_id: Optional[str] = None
) -> "CompactionResult":
    """Compact the team leader's history in one session now, without waiting for the size trigger."""
    from agno.team import _session

    # compaction=True becomes a Compaction when the team is initialized, which a run does and this must too
    team.initialize_team()
    if _conversation.compaction_of(team) is None:
        return _not_enabled()
    session = _session.get_session(team, session_id=session_id, user_id=user_id)
    if session is None or not isinstance(session, TeamSession):
        return _no_session()
    result = _conversation.compact_history(
        team,
        session,
        _history_for_compaction(team, session),
        last_sent=partial(_last_sent, team, session),
        own_message_ids=partial(_own_message_ids, team, session),
    )
    if result.metrics is not None:
        # Read the session again: a run may have finished while the summarizer ran
        session = _session.get_session(team, session_id=session.session_id, user_id=user_id) or session
        latest_run = _add_to_session_and_latest_run(team, session, result.metrics)
        try:
            _session.save_session(team, session)
            if latest_run is not None:
                _session.save_run(
                    team,
                    run=latest_run,
                    session_id=session.session_id,
                    user_id=session.user_id,
                    run_index=resolve_run_index(session, latest_run),
                )
        except Exception as e:  # noqa: BLE001 - the fold is already stored; only the totals are lost
            log_warning(f"Could not add the compaction's usage to the session metrics: {e}")
    return result


async def acompact_session(
    team: "Team", session_id: Optional[str] = None, user_id: Optional[str] = None
) -> "CompactionResult":
    """Async variant of :func:`compact_session`."""
    from agno.team import _session

    # compaction=True becomes a Compaction when the team is initialized, which a run does and this must too
    team.initialize_team()
    if _conversation.compaction_of(team) is None:
        return _not_enabled()
    session = await _session.aget_session(team, session_id=session_id, user_id=user_id)
    if session is None or not isinstance(session, TeamSession):
        return _no_session()
    result = await _conversation.acompact_history(
        team,
        session,
        _history_for_compaction(team, session),
        last_sent=partial(_last_sent, team, session),
        own_message_ids=partial(_own_message_ids, team, session),
    )
    if result.metrics is not None:
        # Read the session again: a run may have finished while the summarizer ran
        session = await _session.aget_session(team, session_id=session.session_id, user_id=user_id) or session
        latest_run = _add_to_session_and_latest_run(team, session, result.metrics)
        try:
            await _session.asave_session(team, session)
            if latest_run is not None:
                await _session.asave_run(
                    team,
                    run=latest_run,
                    session_id=session.session_id,
                    user_id=session.user_id,
                    run_index=resolve_run_index(session, latest_run),
                )
        except Exception as e:  # noqa: BLE001 - the fold is already stored; only the totals are lost
            log_warning(f"Could not add the compaction's usage to the session metrics: {e}")
    return result
