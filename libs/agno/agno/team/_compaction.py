"""Conversation compaction for a Team.

What is compacted is the team leader's conversation: the messages of the Team's own runs, which
hold the person's messages, the leader's answers and its tool calls and results. A member's answer
is in there as the result of the delegation call. A member's own runs are not compacted here.

The threshold, the cut, the summary, the stored record and the search tool are the ones an Agent
uses, from ``agno.compaction``. This module holds what differs for a Team: how the leader's history
is read, which stored messages are the leader's, the message a Team adds to a run without storing
it, and how a manual compaction is run and its usage saved.
"""

from __future__ import annotations

from collections import Counter
from functools import partial
from typing import TYPE_CHECKING, Any, List, Optional, Set, Tuple, cast

from agno.compaction import _conversation
from agno.compaction._conversation import aapply_compaction, apply_compaction, replayed_history
from agno.compaction.types import CompactionRecord, CompactionResult, CompactionStatus
from agno.metrics import RunMetrics
from agno.models.message import Message
from agno.run.team import TeamRunOutput
from agno.session import TeamSession
from agno.session._utils import resolve_run_index
from agno.team.mode import TeamMode
from agno.utils.log import log_warning

if TYPE_CHECKING:
    from agno.run.messages import RunMessages
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


def _fetch(team: "Team", session: TeamSession) -> _conversation.Fetch:
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


def _stored_message_ids(team: "Team", session: TeamSession) -> Set[str]:
    """The ids of the messages the leader has stored in this session.

    A nested team's runs are stored in the top team's session, which its own run does not load: the
    session a nested team runs with holds no runs. So that session is read from the database.
    """
    if team.parent_team_id is None:
        return _own_message_ids(team, session)

    def read() -> List[Message]:
        from agno.team._storage import _read_session

        stored = _read_session(team, session_id=session.session_id, user_id=session.user_id)
        return stored.get_messages(team_id=team.id) if isinstance(stored, TeamSession) else []

    return _conversation.message_ids_of(read)


def history_for_run(
    team: "Team", session: TeamSession, run_response: Optional[TeamRunOutput]
) -> Tuple[List[Message], Optional[CompactionRecord], Optional[Counter[str]]]:
    """The history a run of the Team works from, the fold in force for it, and the replay window.

    Without compaction this is the history a Team has always read: ``num_history_runs`` and
    ``num_history_messages`` of the leader's messages, with no fold and no window.
    """
    return _conversation.history_for_run(
        team, session, run_response, _fetch(team, session), own_message_ids=partial(_own_message_ids, team, session)
    )


def search_tools(team: "Team", session: TeamSession, run_response: TeamRunOutput) -> List[Any]:
    """The tool that searches what this conversation compacted away.

    Offered before the first fold too: the tools of a run are built before the run folds, and the
    summary it is then sent says to search. Bound to this session and to the leader's own folds:
    those anchored on the messages it has stored, read when the model searches, and those this run
    makes. A member that compacts in the same session keeps its folds to itself.
    """
    compaction = _conversation.compaction_of(team)
    if compaction is None:
        return []
    return (
        compaction.tools_for(
            session.session_id,
            team.db,
            message_ids=partial(_stored_message_ids, team, session),
            run_id=run_response.run_id,
            offer_before_first_fold=True,
        )
        or []
    )


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


def _recovers_from_overflow(team: "Team") -> bool:
    """Whether a request the provider rejected as too long is folded and sent again."""
    compaction = _conversation.compaction_of(team)
    if compaction is None or not compaction.on_context_overflow:
        return False
    if team.mode == TeamMode.tasks:
        # A tasks run adds a user message holding the task state on every iteration. A fold takes
        # the newest user message for the start of the current exchange, so here it would fold the
        # person's question and the run's own tool calls out of the request and the stored run.
        log_warning(
            "Compaction: a request was rejected as too long, and folding after a rejection is not "
            "supported in TeamMode.tasks, so it is not retried. Set compact_at_tokens to fold earlier."
        )
        return False
    return True


def recompact_after_overflow(
    team: "Team",
    session: TeamSession,
    run_messages: "RunMessages",
    run_response: Optional[TeamRunOutput] = None,
    tools: Optional[List[Any]] = None,
) -> bool:
    """Fold the leader's live messages after the provider rejected a request as too long. True if it shrank."""
    if not _recovers_from_overflow(team):
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
    run_messages: "RunMessages",
    run_response: Optional[TeamRunOutput] = None,
    tools: Optional[List[Any]] = None,
) -> bool:
    """Async variant of :func:`recompact_after_overflow`."""
    if not _recovers_from_overflow(team):
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


def _not_enabled() -> CompactionResult:
    return CompactionResult(status=CompactionStatus.NOT_ENABLED, message="Compaction is not enabled on this team.")


def _no_session() -> CompactionResult:
    return CompactionResult(status=CompactionStatus.NO_HISTORY, message="No such session.")


def _add_to_session_and_latest_run(team: "Team", session: TeamSession, metrics: RunMetrics) -> Optional[TeamRunOutput]:
    """Add a manual compaction's usage to the leader's latest finished run, returned for saving, and to
    the session's metrics. A member's run in the same session is never the one."""
    from agno.team._session import update_session_metrics

    latest_run = _conversation.add_usage_to_latest_run(
        session, metrics, is_own_run=lambda run: isinstance(run, TeamRunOutput) and run.parent_run_id is None
    )
    update_session_metrics(team, session=session)
    return cast(Optional[TeamRunOutput], latest_run)


def compact_session(team: "Team", session_id: Optional[str] = None, user_id: Optional[str] = None) -> CompactionResult:
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
        fetch=_fetch(team, session),
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
) -> CompactionResult:
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
        fetch=_fetch(team, session),
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
