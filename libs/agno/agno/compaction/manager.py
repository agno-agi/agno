"""Conversation compaction: replace old history with a summary over an archive."""

from __future__ import annotations

from dataclasses import dataclass, field
from time import time
from typing import TYPE_CHECKING, Any, List, Optional
from uuid import uuid4

from agno.compaction._cut import choose_boundary, choose_watermark
from agno.compaction._tokens import estimate_tokens
from agno.compaction._view import build_view
from agno.compaction.archive import CompactionArchive, namespace_for, render_messages
from agno.compaction.prompts import (
    ARCHIVE_AWARE_PROMPT,
    ARCHIVE_LOOKUP_INSTRUCTION,
    DEFAULT_COMPACTION_PROMPT,
)
from agno.compaction.types import CompactionRecord, CompactionStats
from agno.models.base import Model
from agno.models.message import Message
from agno.utils.log import log_debug, log_error, log_info, log_warning

if TYPE_CHECKING:
    from agno.metrics import RunMetrics


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
    # Custom summarization instructions. Replaces the default prompt entirely.
    instructions: Optional[str] = None
    # Length budget given to the summarizer. A summary that grows without bound defeats the
    # point; this is a soft target stated in the prompt, not an enforced cap.
    summary_budget_tokens: int = 2_000

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

    # Render tool results older than the cut as a short placeholder in the view. A cheap,
    # no-inference tier: on a tool-heavy transcript this reclaims more than the summary does,
    # and the full results stay in the transcript and the archive.
    elide_tool_results: bool = True

    # Also compact reactively when the provider rejects a request as too long.
    on_context_overflow: bool = True

    # Skip a compaction unless the folded span is at least this many times the kept tail.
    #
    # A summary has a floor cost - the structured sections alone run to hundreds of tokens - so
    # folding a span barely larger than what it replaces leaves the context BIGGER than it
    # started, and discards the prompt-cache prefix to do it. Sizing the guard relative to the
    # tail, rather than as an absolute char count, is what makes it hold at every scale: it is
    # the ratio of folded-to-kept that decides whether a summary can pay for itself.
    # Set to 0 to always compact.
    min_fold_ratio: float = 2.0

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

    def _keep_tokens(self, messages: List[Message]) -> int:
        """Token budget for the tail kept verbatim.

        ``keep_last_runs`` / ``keep_last_messages`` are expressed in turns, but the cut walks
        backward by token cost, so they are converted here by measuring what that many turns
        actually costs in this conversation.
        """
        if self.keep_last_messages is not None:
            tail = messages[-self.keep_last_messages :] if self.keep_last_messages else []
            return estimate_tokens(tail) if tail else 0

        keep_runs = self.keep_last_runs or 0
        if keep_runs <= 0:
            return 0
        user_indexes = [i for i, m in enumerate(messages) if m.role == "user"]
        if len(user_indexes) <= keep_runs:
            return estimate_tokens(messages)
        return estimate_tokens(messages[user_indexes[-keep_runs] :])

    def boundary_for(self, messages: List[Message], min_index: int = 0) -> Optional[int]:
        """Index of the first message kept verbatim, or None when no safe cut exists.

        Delegates to ``choose_boundary``, which snaps the requested tail to a boundary that is
        pair-safe (a tool result never starts the tail, and a batch whose head would fall behind
        the cut moves into the tail whole) and *durable* - it never anchors on a message that
        will not survive in storage, since the anchor has to resolve again on the next run.
        """
        return choose_boundary(messages, self._keep_tokens(messages), min_index=min_index)

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

    def _summary_messages(
        self,
        messages: List[Message],
        previous: Optional[str],
        archived: bool = False,
        archive_path: Optional[str] = None,
    ) -> List[Message]:
        transcript = render_messages(self._trim_for_summary(messages))
        # Fold the previous summary in rather than summarizing a summary
        # separately, so a session compacted many times keeps one continuous
        # record instead of a chain of lossier and lossier fragments.
        if previous:
            transcript = (
                f"Summary of the conversation before this point:\n{previous}\n\nConversation since then:\n{transcript}"
            )
        prompt = self.instructions or DEFAULT_COMPACTION_PROMPT.format(budget_tokens=self.summary_budget_tokens)
        # Only ask the summary to flag its own gaps when there is somewhere to
        # go and read them. Without an archive the line would name detail the
        # assistant has no way to recover, which is worse than not saying it.
        if archived:
            prompt += ARCHIVE_AWARE_PROMPT.format(archive_path=archive_path or "the archive")
        return [
            Message(role="system", content=prompt),
            Message(role="user", content=transcript),
        ]

    def _summarize(
        self,
        messages: List[Message],
        previous: Optional[str],
        run_metrics: Optional["RunMetrics"] = None,
        archived: bool = False,
        archive_path: Optional[str] = None,
    ) -> Optional[str]:
        if self.model is None:
            log_warning("No compaction model available")
            return None
        try:
            response = self.model.response(messages=self._summary_messages(messages, previous, archived, archive_path))
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
        archived: bool = False,
        archive_path: Optional[str] = None,
    ) -> Optional[str]:
        if self.model is None:
            log_warning("No compaction model available")
            return None
        try:
            response = await self.model.aresponse(
                messages=self._summary_messages(messages, previous, archived, archive_path)
            )
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
        # Only promise a lookup the agent can actually perform. Without the
        # search tools the archive exists for a developer, not the model, and
        # telling it to read a file it cannot open invites a refusal or an
        # invented answer.
        if record.archive_path is not None and self.searchable:
            # State the rule, not a suggestion. A model asked to "search if
            # needed" will usually judge the summary sufficient and answer from
            # it - including for the exact values a summary is least likely to
            # have kept. Naming the file and the trigger condition is what
            # makes the fallback fire on the questions that need it.
            content += (
                f" The full text is stored at `{record.archive_path}`.\n"
                "Before answering any question about the earlier conversation that calls for an "
                "exact value - an identifier, figure, name, quote, command, or error message - "
                "read or search that file rather than relying on this summary. Say you do not "
                "know only after looking."
            )
        return Message(role="system", content=content, temporary=True, add_to_agent_memory=False)

    def build_record(
        self,
        messages: List[Message],
        summary: str,
        first_kept_message_id: Optional[str],
        messages_compacted: int,
        archive_path: Optional[str],
        tokens_before: Optional[int] = None,
    ) -> CompactionRecord:
        return CompactionRecord(
            messages_compacted=messages_compacted,
            summary=summary,
            first_kept_message_id=first_kept_message_id,
            archive_path=archive_path,
            tokens_before=tokens_before,
            created_at=int(time()),
        )

    def apply_record(self, messages: List[Message], record: CompactionRecord) -> List[Message]:
        """Derive the model-bound list for this call: summary, then the kept tail.

        A fresh view each call, built from the canonical messages plus the record. Nothing is
        mutated: every transformation lands on a shallow copy. When the record's anchor no longer
        resolves the view fails open to the full list, which is always valid to send.

        ``strip_provider_chaining`` removes only the response-chaining key from assistant copies.
        Some providers continue a conversation by id rather than from the messages sent (OpenAI
        Responses chains on ``previous_response_id``), and the server then replays the whole
        pre-fold history behind the view's back - so the saving would be imaginary. The rest of
        provider_data survives: a function_call without its paired reasoning item is a provider
        error.
        """
        return build_view(
            messages,
            record,
            strip_provider_chaining=True,
            summary_suffix=self._archive_instruction(record),
        )

    def _archive_instruction(self, record: CompactionRecord) -> Optional[str]:
        """The lookup rule appended to the injected summary, when the agent can act on it.

        Promised only when the archive exists *and* the search tools are attached: telling a
        model to read a file it cannot open invites a refusal or an invented answer.
        """
        if not (self.searchable and record.archive_path):
            return None
        return ARCHIVE_LOOKUP_INSTRUCTION.format(archive_path=record.archive_path)

    def _watermark(self, messages: List[Message], boundary: int, previous: Optional[CompactionRecord]) -> Optional[str]:
        """Where tool-result elision stops, when elision is on.

        Elision covers the span between the previous watermark and this cut: results still in
        the kept tail stay whole, older ones render as a placeholder. Monotonic, so a result
        that has been elided once never comes back.
        """
        if not self.elide_tool_results:
            return previous.elision_watermark_message_id if previous else None
        floor = self._resolved_boundary(messages, previous)
        return choose_watermark(messages, boundary, min_index=floor) or (
            previous.elision_watermark_message_id if previous else None
        )

    @staticmethod
    def _resolved_boundary(messages: List[Message], previous: Optional[CompactionRecord]) -> int:
        """Where the previous compaction cut, as an index into this message list.

        An anchor that no longer resolves means the previous cut does not apply here, so the
        floor is 0 - the same fail-open the view takes.
        """
        if previous is None or not previous.first_kept_message_id:
            return 0
        for index, message in enumerate(messages):
            if message.id == previous.first_kept_message_id:
                return index
        return 0

    def _worth_compacting(self, to_compact: List[Message], kept: List[Message]) -> bool:
        """Whether folding this span can pay for the summary that replaces it.

        Measured as a ratio against the kept tail rather than an absolute size: a summary's
        floor cost is roughly fixed, so what decides whether it pays for itself is how much
        more it is replacing than it is keeping. Below the ratio, leaving the transcript alone
        is strictly better.
        """
        if self.min_fold_ratio <= 0:
            return True
        fold_tokens = estimate_tokens(to_compact)
        keep_tokens = max(estimate_tokens(kept), 1)
        ratio = fold_tokens / keep_tokens
        if ratio < self.min_fold_ratio:
            # log_info, not debug: a threshold was crossed and the user was told so. Going
            # quiet after that reads as a bug. Say what was declined and why.
            log_info(
                f"Compaction: threshold reached but skipping this fold - it would replace "
                f"{fold_tokens} tokens with a summary while keeping a {keep_tokens}-token tail "
                f"(ratio {ratio:.2f} < min_fold_ratio {self.min_fold_ratio}), which would not "
                f"shrink the context. Lower min_fold_ratio or keep_last_runs to fold sooner."
            )
            return False
        return True

    def plan(self, messages: List[Message], previous: Optional[CompactionRecord] = None) -> Optional[int]:
        """The boundary this compaction would use, or None if it should not run.

        Callers announce a compaction (log line, CompactionStarted) only once
        this returns a boundary. Announcing before the guards run reports
        compactions that never happen - which is what a bare "should_compact"
        does, since it cannot see the pair-safe boundary or the size floor.
        """
        already = self._resolved_boundary(messages, previous)
        boundary = self.boundary_for(messages, min_index=already)
        if boundary is None or boundary <= already:
            kept = "keep_last_messages" if self.keep_last_messages is not None else "keep_last_runs"
            size = self.keep_last_messages if self.keep_last_messages is not None else self.keep_last_runs
            if previous is None:
                log_info(
                    f"Compaction: threshold reached but nothing to fold yet - {kept}={size} covers the "
                    f"whole conversation, so there is no history before the kept tail. Lower {kept} to "
                    "fold sooner."
                )
            else:
                log_info(
                    "Compaction: threshold reached but no safe cut past the previous fold yet - the "
                    "conversation has not grown enough since then."
                )
            return None
        if not self._worth_compacting(messages[already:boundary], messages[boundary:]):
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

        already = self._resolved_boundary(messages, previous)
        to_compact = messages[already:boundary]
        archive = self.archive_for(session_id, db)
        archive_path = archive.write(to_compact) if archive is not None else None

        summary = self._summarize(
            to_compact,
            previous.summary if previous else None,
            run_metrics,
            archived=archive_path is not None,
            archive_path=archive_path,
        )
        if not summary:
            return None

        record = self.build_record(
            messages, summary, messages[boundary].id, len(to_compact), archive_path, tokens_before
        )
        record.elision_watermark_message_id = self._watermark(messages, boundary, previous)
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

        already = self._resolved_boundary(messages, previous)
        to_compact = messages[already:boundary]
        archive = self.archive_for(session_id, db)
        archive_path = await archive.awrite(to_compact) if archive is not None else None

        summary = await self._asummarize(
            to_compact,
            previous.summary if previous else None,
            run_metrics,
            archived=archive_path is not None,
            archive_path=archive_path,
        )
        if not summary:
            return None

        record = self.build_record(
            messages, summary, messages[boundary].id, len(to_compact), archive_path, tokens_before
        )
        record.elision_watermark_message_id = self._watermark(messages, boundary, previous)
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
