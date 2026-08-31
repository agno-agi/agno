"""Conversation compaction: replace old history with a summary over an archive."""

from __future__ import annotations

from dataclasses import dataclass, field
from textwrap import dedent
from time import time
from typing import TYPE_CHECKING, Any, List, Optional
from uuid import uuid4

from agno.compaction.archive import CompactionArchive, namespace_for, render_messages
from agno.compaction.types import CompactionRecord, CompactionStats
from agno.models.base import Model
from agno.models.message import Message
from agno.utils.log import log_debug, log_error, log_info, log_warning
from agno.utils.message import safe_truncation_index

if TYPE_CHECKING:
    from agno.metrics import RunMetrics

DEFAULT_COMPACTION_PROMPT = dedent("""\
    You are compacting the earlier part of a conversation so it can be dropped
    from context while the assistant keeps working without losing the thread.

    Write a summary that lets the assistant continue as if it still remembered
    everything. Preserve:
    - What the user asked for, including constraints and stated preferences
    - Decisions taken, and the reasoning that settled them
    - Facts established: names, numbers, dates, identifiers, file paths, URLs
    - What was tried and failed, and why, so it is not retried
    - Work still outstanding

    Drop: pleasantries, restatements, tool mechanics, and anything already
    superseded by a later decision.

    Write in past tense, as a factual record. Be specific over general: names
    and numbers, not "some files" or "a few options". Do not invent anything
    that is not in the transcript.
    """)

# Summarizing an enormous transcript in one call is unreliable and can itself
# overflow. Trim what the summarizer reads, oldest first, to this budget.
DEFAULT_SUMMARIZE_CHAR_BUDGET = 100_000


@dataclass
class Compaction:
    """Keeps a long session inside the context window.

    When the conversation crosses a threshold, the older messages are archived
    verbatim and replaced in context by a generated summary. Nothing is lost:
    the summary stands in for the originals, and the originals stay readable -
    by a developer, or by the agent itself when ``searchable=True``.

    Only the message list sent to the model is rewritten. What the session
    persists is untouched, so compaction can never corrupt the record of what
    actually happened.
    """

    # Unique identifier for this manager. Auto-generated if not provided.
    id: Optional[str] = None
    # Optional human-readable name for this manager.
    name: Optional[str] = None
    # Id of the agent or team that owns this manager (set when registered in the OS).
    owner_id: Optional[str] = None
    # Type of the owner: "agent" or "team" (set when registered in the OS).
    owner_type: Optional[str] = None

    # Model used to write the summary. Defaults to the agent's model.
    model: Optional[Model] = None
    # Custom summarization instructions.
    instructions: Optional[str] = None

    # -- when to compact ------------------------------------------------
    # Compact when the context is at least this many tokens.
    compact_at_tokens: Optional[int] = None
    # Compact when the history holds at least this many runs.
    compact_at_runs: Optional[int] = 20
    # Compact when the history holds at least this many messages.
    compact_at_messages: Optional[int] = None

    # -- what to keep ---------------------------------------------------
    # Recent runs kept verbatim. Ignored when keep_last_messages is set.
    keep_last_runs: Optional[int] = 5
    # Recent messages kept verbatim.
    keep_last_messages: Optional[int] = None

    # -- archive --------------------------------------------------------
    # Write replaced messages to the filesystem so they stay recoverable.
    archive: bool = True
    # Give the agent read-only search over the archive.
    searchable: bool = False
    # Where the archive lives. Defaults to the agent's db (AgentFS).
    fs: Optional[Any] = None

    # Also compact reactively when the provider rejects a request as too long.
    on_context_overflow: bool = True

    # Skip a compaction that would not free at least this many characters of
    # transcript. A summary has a fixed cost, so compacting a handful of short
    # turns can leave the context BIGGER than it started - and it invalidates
    # the prompt-cache prefix to do it. Set to 0 to always compact.
    min_chars_to_reclaim: int = 2_000

    stats: CompactionStats = field(default_factory=CompactionStats)

    def __post_init__(self) -> None:
        if self.id is None:
            self.id = f"compaction_{uuid4().hex[:8]}"
        for name in ("compact_at_tokens", "compact_at_runs", "compact_at_messages"):
            value = getattr(self, name)
            if value is not None and value <= 0:
                raise ValueError(f"{name} must be a positive integer, got {value}")
        for name in ("keep_last_runs", "keep_last_messages"):
            value = getattr(self, name)
            if value is not None and value < 0:
                raise ValueError(f"{name} must be zero or a positive integer, got {value}")
        if self.keep_last_runs is not None and self.keep_last_messages is not None:
            log_warning("keep_last_runs and keep_last_messages cannot both be set. Using keep_last_messages.")
            self.keep_last_runs = None
        if not any(v is not None for v in (self.compact_at_tokens, self.compact_at_runs, self.compact_at_messages)):
            raise ValueError(
                "Compaction needs at least one threshold: compact_at_tokens, compact_at_runs, or compact_at_messages."
            )

    # -- thresholds -----------------------------------------------------

    def _measured_tokens(
        self,
        messages: List[Message],
        last_input_tokens: Optional[int],
        model: Optional[Model],
        tools: Optional[List[Any]] = None,
    ) -> Optional[int]:
        """Context size in tokens, preferring the free signal.

        The previous run's provider-reported input_tokens costs nothing and is
        what the provider actually charged for. ``count_tokens`` is the
        fallback, and on some providers it is a network call, so it is only
        reached when no run has reported yet.
        """
        if last_input_tokens is not None:
            return last_input_tokens
        if model is None:
            return None
        try:
            return model.count_tokens(messages, tools)
        except Exception as e:
            log_warning(f"Could not count tokens for compaction: {e}")
            return None

    def should_compact(
        self,
        messages: List[Message],
        *,
        last_input_tokens: Optional[int] = None,
        model: Optional[Model] = None,
        tools: Optional[List[Any]] = None,
    ) -> bool:
        """Whether the history has grown enough to compact.

        Cheapest signal first: counting runs and messages is free, measuring
        tokens may not be.
        """
        if self.compact_at_runs is not None:
            # Runs *currently in context*, not runs in the session. The session
            # count only ever grows, so comparing against it would leave the
            # threshold tripped forever and recompact on every subsequent run.
            # A user message opens a run, and compaction replaces the earlier
            # ones with a single summary, so this count falls back after a
            # compaction exactly as the context it measures does.
            runs_in_context = sum(1 for m in messages if m.role == "user")
            if runs_in_context >= self.compact_at_runs:
                log_info(f"Compaction: runs in context {runs_in_context} >= {self.compact_at_runs}")
                return True

        if self.compact_at_messages is not None and len(messages) >= self.compact_at_messages:
            log_info(f"Compaction: message count {len(messages)} >= {self.compact_at_messages}")
            return True

        if self.compact_at_tokens is not None:
            tokens = self._measured_tokens(messages, last_input_tokens, model, tools)
            if tokens is not None and tokens >= self.compact_at_tokens:
                log_info(f"Compaction: token count {tokens} >= {self.compact_at_tokens}")
                return True

        return False

    # -- boundary -------------------------------------------------------

    def _requested_boundary(self, messages: List[Message]) -> int:
        """Where the kept tail starts, before pair-safety is applied."""
        if self.keep_last_messages is not None:
            return max(0, len(messages) - self.keep_last_messages)

        keep_runs = self.keep_last_runs if self.keep_last_runs is not None else 0
        if keep_runs <= 0:
            return len(messages)
        # A run begins at a user message; keep the last ``keep_runs`` of them.
        user_indexes = [i for i, m in enumerate(messages) if m.role == "user"]
        if len(user_indexes) <= keep_runs:
            return 0
        return user_indexes[-keep_runs]

    def boundary_for(self, messages: List[Message]) -> int:
        """The index the kept tail starts at, never splitting a tool batch.

        Cutting between an assistant message that owns tool_calls and the tool
        results answering them leaves an unanswered call, which most providers
        reject outright - so the requested boundary is snapped down to a safe
        one.
        """
        return safe_truncation_index(messages, self._requested_boundary(messages))

    # -- summarizing ----------------------------------------------------

    def _trim_for_summary(self, messages: List[Message]) -> List[Message]:
        """Drop the oldest messages that do not fit the summarizer's budget."""
        kept: List[Message] = []
        budget = DEFAULT_SUMMARIZE_CHAR_BUDGET
        for message in reversed(messages):
            size = len(message.get_content_string())
            if budget - size < 0 and kept:
                break
            budget -= size
            kept.append(message)
        return list(reversed(kept))

    def _summary_messages(self, messages: List[Message], previous: Optional[str]) -> List[Message]:
        transcript = render_messages(self._trim_for_summary(messages))
        # Fold the previous summary in rather than summarizing a summary
        # separately, so a session compacted many times keeps one continuous
        # record instead of a chain of lossier and lossier fragments.
        if previous:
            transcript = (
                f"Summary of the conversation before this point:\n{previous}\n\nConversation since then:\n{transcript}"
            )
        return [
            Message(role="system", content=self.instructions or DEFAULT_COMPACTION_PROMPT),
            Message(role="user", content=transcript),
        ]

    def _summarize(
        self,
        messages: List[Message],
        previous: Optional[str],
        run_metrics: Optional["RunMetrics"] = None,
    ) -> Optional[str]:
        if self.model is None:
            log_warning("No compaction model available")
            return None
        try:
            response = self.model.response(messages=self._summary_messages(messages, previous))
        except Exception as e:
            log_error(f"Error compacting conversation: {e}")
            return None
        self._accumulate(response, run_metrics)
        return response.content

    async def _asummarize(
        self,
        messages: List[Message],
        previous: Optional[str],
        run_metrics: Optional["RunMetrics"] = None,
    ) -> Optional[str]:
        if self.model is None:
            log_warning("No compaction model available")
            return None
        try:
            response = await self.model.aresponse(messages=self._summary_messages(messages, previous))
        except Exception as e:
            log_error(f"Error compacting conversation: {e}")
            return None
        self._accumulate(response, run_metrics)
        return response.content

    def _accumulate(self, response: Any, run_metrics: Optional["RunMetrics"]) -> None:
        if run_metrics is None or self.model is None:
            return
        from agno.metrics import ModelType, accumulate_model_metrics

        accumulate_model_metrics(response, self.model, ModelType.COMPACTION_MODEL, run_metrics)

    # -- archive --------------------------------------------------------

    def archive_for(self, session_id: str, db: Optional[Any] = None) -> Optional[CompactionArchive]:
        """The archive for one session, or None when archiving is off or unavailable."""
        if not self.archive:
            return None
        fs = self.resolve_fs(session_id, db)
        return CompactionArchive(fs) if fs is not None else None

    def resolve_fs(self, session_id: str, db: Optional[Any] = None) -> Optional[Any]:
        """The FileSystem this session's archive lives in.

        An explicit ``fs`` is used as given, resolved to this session's
        namespace so two sessions sharing one filesystem never share files.
        Otherwise one is built over the agent's db, which is where AgentFS
        keeps files by default - the ``agno_fs`` table, not the local disk.
        """
        from agno.fs import FileSystem

        namespace = namespace_for(session_id)
        if self.fs is not None:
            backend = self.fs.backend if isinstance(self.fs, FileSystem) else self.fs
            return FileSystem(backend=backend, namespace=namespace)
        if db is None:
            return None
        try:
            return FileSystem(backend=db, namespace=namespace)
        except TypeError as e:
            # A db AgentFS cannot back. The summary still stands; only the
            # archive is lost, and a run must never fail over that.
            log_warning(f"Compaction archive unavailable for this db, keeping the summary only: {e}")
            return None

    # -- applying -------------------------------------------------------

    def _summary_message(self, record: CompactionRecord) -> Message:
        """The message that stands in for everything compacted away.

        Sent to the model but never stored. ``add_to_agent_memory=False`` is
        what keeps it out of the session - the run records only messages that
        carry it - and ``temporary`` additionally drops it from provider
        request state. Both matter: the session already holds the real
        messages, and persisting the summary would mean re-summarizing a
        summary on the next compaction, compounding the loss each time.
        """
        content = (
            "<conversation_summary>\n"
            f"{record.summary}\n"
            "</conversation_summary>\n\n"
            f"The {record.messages_compacted} earlier messages this replaces were removed to save space."
        )
        if record.archive_path is not None:
            content += (
                f" They are stored verbatim at `{record.archive_path}`; "
                "search or read that file if you need a detail this summary omits."
            )
        return Message(role="system", content=content, temporary=True, add_to_agent_memory=False)

    def build_record(
        self,
        messages: List[Message],
        summary: str,
        boundary: int,
        archive_path: Optional[str],
        tokens_before: Optional[int] = None,
    ) -> CompactionRecord:
        return CompactionRecord(
            messages_compacted=boundary,
            summary=summary,
            boundary=boundary,
            archive_path=archive_path,
            tokens_before=tokens_before,
            created_at=int(time()),
        )

    def apply_record(self, messages: List[Message], record: CompactionRecord) -> List[Message]:
        """Rebuild the model-bound list: summary, then the kept tail.

        Applied to a fresh copy of history each run, so a stored record replays
        without paying for the summary again.
        """
        boundary = min(record.boundary, len(messages))
        kept = [self._drop_server_side_state(m) for m in messages[boundary:]]
        return [self._summary_message(record)] + kept

    @staticmethod
    def _drop_server_side_state(message: Message) -> Message:
        """Detach a kept message from any provider-side conversation history.

        Some providers continue a conversation by id rather than from the
        messages sent: OpenAI Responses chains on ``previous_response_id``
        taken from an assistant message's ``provider_data``, and the server
        then replays the WHOLE prior conversation - including the turns
        compaction just removed. The context would look compacted locally
        while the model still saw everything, so the saving is imaginary and
        the summary is contradicted by history the agent should no longer
        have. Dropping the id forces the provider to use the messages we
        actually send.
        """
        existing = message.provider_data or {}
        if "response_id" not in existing:
            return message
        provider_data = {k: v for k, v in existing.items() if k != "response_id"}
        return message.model_copy(update={"provider_data": provider_data or None})

    def _worth_compacting(self, to_compact: List[Message]) -> bool:
        """Whether replacing these messages would actually free anything.

        A summary costs a few hundred characters no matter how little it
        replaces, so compacting a short span can leave the context bigger than
        it started - and it discards the prompt-cache prefix to do it. Below
        the floor, leaving the transcript alone is strictly better.
        """
        if self.min_chars_to_reclaim <= 0:
            return True
        size = sum(len(m.get_content_string()) for m in to_compact)
        if size < self.min_chars_to_reclaim:
            log_debug(f"Compaction: skipping, only {size} chars to reclaim (min {self.min_chars_to_reclaim})")
            return False
        return True

    def plan(self, messages: List[Message], previous: Optional[CompactionRecord] = None) -> Optional[int]:
        """The boundary this compaction would use, or None if it should not run.

        Callers announce a compaction (log line, CompactionStarted) only once
        this returns a boundary. Announcing before the guards run reports
        compactions that never happen - which is what a bare "should_compact"
        does, since it cannot see the pair-safe boundary or the size floor.
        """
        boundary = self.boundary_for(messages)
        already = previous.boundary if previous is not None else 0
        if boundary <= already:
            log_debug("Compaction: nothing new to compact")
            return None
        if not self._worth_compacting(messages[already:boundary]):
            return None
        return boundary

    def compact(
        self,
        messages: List[Message],
        *,
        session_id: str,
        db: Optional[Any] = None,
        previous: Optional[CompactionRecord] = None,
        run_metrics: Optional["RunMetrics"] = None,
        tokens_before: Optional[int] = None,
    ) -> Optional[CompactionRecord]:
        """Archive and summarize the head of ``messages``.

        Returns None when there is nothing worth compacting or the summary
        could not be written - in both cases the caller leaves history alone.
        """
        # Only the span not already covered by the previous compaction is new.
        # Re-archiving and re-summarizing what a previous run handled would
        # duplicate the archive and pay for the same tokens twice.
        boundary = self.plan(messages, previous)
        if boundary is None:
            return None

        already = previous.boundary if previous is not None else 0
        to_compact = messages[already:boundary]
        archive = self.archive_for(session_id, db)
        archive_path = archive.write(to_compact) if archive is not None else None

        summary = self._summarize(to_compact, previous.summary if previous else None, run_metrics)
        if not summary:
            return None

        record = self.build_record(messages, summary, boundary, archive_path, tokens_before)
        self.stats.record(record)
        return record

    async def acompact(
        self,
        messages: List[Message],
        *,
        session_id: str,
        db: Optional[Any] = None,
        previous: Optional[CompactionRecord] = None,
        run_metrics: Optional["RunMetrics"] = None,
        tokens_before: Optional[int] = None,
    ) -> Optional[CompactionRecord]:
        # See the sync path: only the span the previous compaction did not
        # already cover is new.
        boundary = self.plan(messages, previous)
        if boundary is None:
            return None

        already = previous.boundary if previous is not None else 0
        to_compact = messages[already:boundary]
        archive = self.archive_for(session_id, db)
        archive_path = await archive.awrite(to_compact) if archive is not None else None

        summary = await self._asummarize(to_compact, previous.summary if previous else None, run_metrics)
        if not summary:
            return None

        record = self.build_record(messages, summary, boundary, archive_path, tokens_before)
        self.stats.record(record)
        return record

    # -- tools ----------------------------------------------------------

    def tools_for(self, session_id: str, db: Optional[Any] = None) -> Optional[Any]:
        """Read-only search over this session's archive, when ``searchable``.

        The filesystem toolkit already provides exactly the right surface -
        read_file, list_files, search_content - scoped to this session's
        namespace, so one agent can never read another session's history.

        Returns None until this session has actually archived something.
        Offering the tools over an empty archive only invites a pointless
        lookup on the first turn, before there is any history to find.
        """
        if not (self.searchable and self.archive):
            return None
        fs = self.resolve_fs(session_id, db)
        if fs is None:
            return None
        try:
            if not fs.list():
                return None
        except Exception as e:  # noqa: BLE001 - an unreadable archive is not a run failure
            log_debug(f"Compaction: could not list archive, not attaching tools: {e}")
            return None
        return fs.tools(read_only=True)


__all__ = ["Compaction", "DEFAULT_COMPACTION_PROMPT"]
