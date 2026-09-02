"""Conversation compaction: replace old history with a summary over an archive."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, List, Optional
from uuid import uuid4

from agno.compaction._cut import choose_boundary, choose_watermark, is_offload_envelope
from agno.compaction._tokens import estimate_tokens
from agno.compaction._view import build_view
from agno.compaction.archive import CompactionArchive, render_messages, supports_compactions
from agno.compaction.prompts import (
    ARCHIVE_AWARE_PROMPT,
    ARCHIVE_LOOKUP_INSTRUCTION,
    DEFAULT_COMPACTION_PROMPT,
)
from agno.compaction.types import CompactionRecord, CompactionStats
from agno.models.base import Model
from agno.models.message import Message
from agno.utils.log import log_error, log_info, log_warning

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

    def _keep_from_index(self, messages: List[Message]) -> Optional[int]:
        """Index the kept tail starts at, for a request expressed in turns.

        ``keep_last_runs`` / ``keep_last_messages`` name a position, so this returns one. The
        boundary walk then only snaps it earlier for safety - it never moves later, which is what
        makes the setting a floor: you may keep more than asked, never less.
        """
        if self.keep_last_messages is not None:
            return max(0, len(messages) - self.keep_last_messages)

        keep_runs = self.keep_last_runs or 0
        if keep_runs <= 0:
            return len(messages)
        # A user message opens a run.
        user_indexes = [i for i, m in enumerate(messages) if m.role == "user"]
        if len(user_indexes) <= keep_runs:
            return 0
        return user_indexes[-keep_runs]

    def boundary_for(self, messages: List[Message], min_index: int = 0) -> Optional[int]:
        """Index of the first message kept verbatim, or None when no safe cut exists.

        Delegates to ``choose_boundary``, which snaps the requested tail to a boundary that is
        pair-safe (a tool result never starts the tail, and a batch whose head would fall behind
        the cut moves into the tail whole) and *durable* - it never anchors on a message that
        will not survive in storage, since the anchor has to resolve again on the next run.
        """
        return choose_boundary(messages, keep_from_index=self._keep_from_index(messages), min_index=min_index)

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
            prompt += ARCHIVE_AWARE_PROMPT
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
    ) -> Optional[str]:
        if self.model is None:
            log_warning("No compaction model available")
            return None
        try:
            response = self.model.response(messages=self._summary_messages(messages, previous, archived))
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
    ) -> Optional[str]:
        if self.model is None:
            log_warning("No compaction model available")
            return None
        try:
            response = await self.model.aresponse(messages=self._summary_messages(messages, previous, archived))
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

    def archive_for(
        self, session_id: str, db: Optional[Any] = None, user_id: Optional[str] = None
    ) -> Optional[CompactionArchive]:
        """The archive for one session, or None when it is off or unavailable."""
        if not self.archive or not supports_compactions(db):
            return None
        return CompactionArchive(db, session_id, user_id)

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
        if record.archived and self.searchable:
            # State the rule, not a suggestion. A model asked to "search if
            # needed" will usually judge the summary sufficient and answer from
            # it - including for the exact values a summary is least likely to
            # have kept. Naming the file and the trigger condition is what
            # makes the fallback fire on the questions that need it.
            content += (
                " The full text of the folded conversation is stored and searchable.\n"
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
        tokens_before: Optional[int] = None,
        run_id: Optional[str] = None,
    ) -> CompactionRecord:
        from uuid import uuid4

        return CompactionRecord(
            id=uuid4().hex,
            run_id=run_id,
            messages_compacted=messages_compacted,
            summary=summary,
            first_kept_message_id=first_kept_message_id,
            tokens_before=tokens_before,
        )

    def measure(self, record: CompactionRecord, before: List[Message], after: List[Message]) -> None:
        """Record what this fold cost and saved.

        Both sides are counted locally over the two lists this fold turned into each other, so the
        numbers are comparable and the measurement costs nothing. ``Model.count_tokens`` is
        deliberately not used: on some providers it is a network round trip, and OpenAI rejects a
        list with no user message - which is exactly the shape a folded list can have.
        """
        from agno.utils.tokens import count_tokens

        model_id = getattr(self.model, "id", None) or "gpt-4o"
        try:
            record.tokens_before = count_tokens(before, model_id=model_id)
            record.tokens_after = count_tokens(after, model_id=model_id)
        except Exception:  # noqa: BLE001 - a measurement must never fail a run
            pass

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
        if not (self.searchable and record.archived):
            return None
        return ARCHIVE_LOOKUP_INSTRUCTION

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

        Offload envelopes are excluded from the tail. They are pinned there - their result_id is
        the only handle on the stored payload, so the cut must stay ahead of them - which means
        their cost is not something folding could ever reclaim. Counting them would let a single
        envelope make every subsequent fold look worthless and stall compaction entirely.
        """
        if self.min_fold_ratio <= 0:
            return True
        fold_tokens = estimate_tokens([m for m in to_compact if not is_offload_envelope(m)])
        keep_tokens = max(estimate_tokens([m for m in kept if not is_offload_envelope(m)]), 1)
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
        run_id: Optional[str] = None,
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

        summary = self._summarize(
            to_compact,
            previous.summary if previous else None,
            run_metrics,
            archived=archive is not None,
        )
        if not summary:
            return None

        record = self.build_record(
            messages, summary, messages[boundary].id, len(to_compact), tokens_before, run_id=run_id
        )
        record.elision_watermark_message_id = self._watermark(messages, boundary, previous)
        # Size the fold before persisting: the row is written once and never updated, so a
        # measurement taken afterwards would never reach it.
        self.measure(record, messages, self.apply_record(messages, record))
        if archive is not None:
            record.archived = archive.write(record, to_compact)
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
        run_id: Optional[str] = None,
    ) -> Optional[CompactionRecord]:
        # See the sync path: only the span the previous compaction did not
        # already cover is new.
        boundary = self.plan(messages, previous)
        if boundary is None:
            return None

        already = self._resolved_boundary(messages, previous)
        to_compact = messages[already:boundary]
        archive = self.archive_for(session_id, db)

        summary = await self._asummarize(
            to_compact,
            previous.summary if previous else None,
            run_metrics,
            archived=archive is not None,
        )
        if not summary:
            return None

        record = self.build_record(
            messages, summary, messages[boundary].id, len(to_compact), tokens_before, run_id=run_id
        )
        record.elision_watermark_message_id = self._watermark(messages, boundary, previous)
        # Size the fold before persisting: the row is written once and never updated, so a
        # measurement taken afterwards would never reach it.
        self.measure(record, messages, self.apply_record(messages, record))
        if archive is not None:
            record.archived = archive.write(record, to_compact)
        self.stats.record(record)
        return record

    # -- tools ----------------------------------------------------------

    def tools_for(self, session_id: str, db: Optional[Any] = None) -> Optional[List[Any]]:
        """A tool letting the agent read back what this session compacted away.

        Scoped to one session by construction - the session id is bound here, never taken from a
        model argument - so an agent can never search another conversation's history.

        Returns None until something has actually been archived: offering the tool over an empty
        archive only invites a pointless lookup on the first turn.
        """
        if not (self.searchable and self.archive):
            return None
        archive = self.archive_for(session_id, db)
        if archive is None or archive.latest() is None:
            return None

        def search_compacted_history(pattern: str, context_lines: int = 2) -> str:
            """Search the earlier conversation that was compacted out of context.

            Use this when a question needs an exact value - an identifier, figure, name, quote,
            command, or error message - that the summary does not carry.

            Args:
                pattern: A regular expression, matched line by line against the stored
                    transcript. Plain text works as a literal search.
                context_lines: Lines of surrounding context to show around each match.
            """
            rows = archive.search(pattern, limit=5)
            if not rows:
                return f"No compacted history matches {pattern!r}."
            blocks = []
            for row in rows:
                hits = _grep(row.get("archived_messages") or "", pattern, context_lines)
                if hits:
                    blocks.append(hits)
            if not blocks:
                return f"No compacted history matches {pattern!r}."
            return "\n\n---\n\n".join(blocks)

        return [search_compacted_history]


def _grep(text: str, pattern: str, context_lines: int = 2, max_matches: int = 20) -> str:
    """Matching lines with surrounding context, numbered - the shape `grep -n -C` returns.

    The regex is compiled here rather than pushed into SQL: databases disagree on regex support,
    and a line-oriented result is what makes a transcript readable. SQL still prefilters which
    rows are worth scanning, so this only ever runs over candidates.

    A pattern that fails to compile is treated as a literal string, since the caller is a model
    that may well send plain text containing regex metacharacters.
    """
    import re

    try:
        compiled = re.compile(pattern, re.IGNORECASE)
    except re.error:
        compiled = re.compile(re.escape(pattern), re.IGNORECASE)

    lines = text.split("\n")
    hit_indexes = [i for i, line in enumerate(lines) if compiled.search(line)]
    if not hit_indexes:
        return ""

    truncated = len(hit_indexes) > max_matches
    hit_indexes = hit_indexes[:max_matches]

    # Merge overlapping context windows so a dense run of matches reads as one block.
    spans: List[List[int]] = []
    for index in hit_indexes:
        start, end = max(0, index - context_lines), min(len(lines), index + context_lines + 1)
        if spans and start <= spans[-1][1]:
            spans[-1][1] = max(spans[-1][1], end)
        else:
            spans.append([start, end])

    blocks = []
    for start, end in spans:
        blocks.append("\n".join(f"{i + 1}: {lines[i]}" for i in range(start, end)))
    rendered = "\n--\n".join(blocks)
    if truncated:
        rendered += f"\n... more than {max_matches} matches; narrow the pattern."
    return rendered


__all__ = ["Compaction", "DEFAULT_COMPACTION_PROMPT"]
