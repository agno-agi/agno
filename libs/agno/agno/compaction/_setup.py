"""Resolving the ``compaction`` setting on whoever holds the conversation: an Agent or a Team."""

from __future__ import annotations

from typing import TYPE_CHECKING, Union

from agno.utils.log import log_warning

if TYPE_CHECKING:
    from agno.agent.agent import Agent
    from agno.team.team import Team

    CompactionOwner = Union[Agent, Team]


def disable_compaction_without_records(owner: CompactionOwner) -> None:
    """Turn compaction off, with a warning, when the db cannot store compaction records.

    A fold lasts only as long as its record: without one, every run starts from the full history
    and pays for another summary of all of it. Only SqliteDb and PostgresDb store records. Checked
    when the agent or team is built, and again at run start for a db assigned afterwards.
    """
    if not owner.compaction or owner.db is None:
        return
    from agno.compaction.archive import stores_compaction_records

    if not stores_compaction_records(owner.db):
        log_warning(
            f"Compaction is only supported with SqliteDb and PostgresDb; {type(owner.db).__name__} cannot "
            "store compaction records, so compaction is turned off. Use SqliteDb or PostgresDb to enable it."
        )
        owner.compaction = None


def set_compaction(owner: CompactionOwner) -> None:
    """Resolve ``owner.compaction`` into the Compaction the run uses.

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
    from agno.compaction.compaction import Compaction

    if owner.compaction is True:
        owner.compaction = Compaction(compact_at_tokens=None, on_context_overflow=True)
    elif owner.compaction is False:
        owner.compaction = None

    disable_compaction_without_records(owner)

    if isinstance(owner.compaction, Compaction) and owner.compaction.model is None:
        owner.compaction.model = owner.model

    if isinstance(owner.compaction, Compaction):
        # Compaction folds the history a run replays. Without replayed history a size threshold
        # has nothing to measure and a fold is never sent. Overflow recovery still acts within a
        # run, so a bare compaction=True - which has no threshold - is not a mistake here.
        if not owner.add_history_to_context and owner.compaction.compact_at_tokens is not None:
            log_warning(
                "compaction is set but add_history_to_context is False, so no history is replayed: "
                "compact_at_tokens never fires and a fold is never sent. Set add_history_to_context=True."
            )
        # Both put a summary of the same history into the context, so the model reads it twice.
        if owner.add_session_summary_to_context:
            log_warning(
                "compaction and session summaries are both enabled, so the context carries two summaries "
                "of the same history. Compaction already replaces old turns with its own summary; "
                "consider add_session_summary_to_context=False."
            )
