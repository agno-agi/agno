"""Conversation compaction: replace old history with a summary over an archive."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Callable, List, Optional, Tuple, Union, cast
from uuid import uuid4

from agno.compaction._cut import choose_boundary, is_offload_envelope
from agno.compaction._tokens import TokenCounter, count_request, estimate_tokens, is_async_callable
from agno.compaction._view import build_view
from agno.compaction.archive import CompactionArchive, render_message, render_messages, search_terms
from agno.compaction.prompts import (
    ARCHIVE_AWARE_PROMPT,
    ARCHIVE_LOOKUP_INSTRUCTION,
    DEFAULT_COMPACTION_PROMPT,
    LENGTH_RULE_BUDGET,
    LENGTH_RULE_COMPACT,
    SUMMARY_CUT_NOTE,
    SUMMARY_CUT_NOTE_SEARCHABLE,
)
from agno.compaction.types import CompactionRecord, CompactionStats, CompactionStatus
from agno.models.base import Model
from agno.models.message import Message
from agno.models.utils import get_model
from agno.utils.log import log_debug, log_error, log_info, log_warning

if TYPE_CHECKING:
    from agno.metrics import RunMetrics


# Model id the local token counts fall back to when no model carries one. It is the Agent and
# Team default, so compaction has no second opinion about which model is current.
DEFAULT_TOKENIZER_MODEL_ID = "gpt-5.4"

# Summarizing an enormous transcript in one call is unreliable and can itself
# overflow. Trim what the summarizer reads, oldest first, to this budget - about
# 100k tokens, so a fold at the default compact_at_tokens fits in one call.
DEFAULT_SUMMARIZE_CHAR_BUDGET = 400_000

# Bounds on what one archive search can return. The result lands in the context window, so an
# unbounded one could overflow it on its own - and on a small model, sink the retry after an
# overflow fold as well.
_SEARCH_MAX_CONTEXT_LINES = 10
_SEARCH_LINE_CHARS = 500
_SEARCH_OUTPUT_CHARS = 8_000
# Folds one search scans. Generous, so a term common in recent folds cannot crowd out an older
# fold that holds another term; the output cap bounds what comes back either way.
_SEARCH_MAX_FOLDS = 20


# The default kept tail, and a sentinel standing in for "nobody set this". Comparing against
# the value alone cannot tell uncompacted_runs=5 written by hand from the default, so an explicit
# 5 alongside uncompacted_tokens would be silently discarded - the exact surprise the mutual
# exclusion exists to prevent.
_COMPACT_AT_TOKENS_DEFAULT = 150_000


class _UnsetTokens(int):
    """The default compact_at_tokens, so an explicit 150_000 is still distinguishable."""


_COMPACT_AT_TOKENS_UNSET = _UnsetTokens(_COMPACT_AT_TOKENS_DEFAULT)

_UNCOMPACTED_RUNS_DEFAULT = 5


class _Unset(int):
    """The default uncompacted_runs, indistinguishable from 5 in use but not by identity."""


_UNCOMPACTED_RUNS_UNSET = _Unset(_UNCOMPACTED_RUNS_DEFAULT)


@dataclass
class Compaction:
    """Keeps a long session inside the context window.

    When the conversation crosses a threshold, the older messages are stored
    verbatim and replaced in context by a generated summary. Nothing is lost:
    the summary stands in for the originals, and the originals stay readable -
    by a developer reading the row, and by the agent itself, which gets a
    read-only search over them unless ``search_compacted_messages`` is turned off.

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

    # Model that writes the summary: a Model, or a "provider:model_id" string. Defaults to the
    # agent's model.
    model: Optional[Union[Model, str]] = None
    # Extra guidance for the summarizer, added to the default prompt - e.g. "Keep every ticket id".
    instructions: Optional[str] = None
    # Length budget for the summary, stated in the prompt in tokens, words and characters. None
    # asks the model for a compact summary without naming a size and never cuts it: a model cannot
    # count the tokens it writes, so any fixed number is a target it will miss, and a reasoning
    # model spends part of any output cap on thinking before the summary starts.
    compacted_token_budget: Optional[int] = None
    # Hold the summary to compacted_token_budget when one is set. A summary that runs over is cut
    # from the end, at a line break. The prompt orders the summary most important first, so the
    # cut drops finished history before what the agent needs to carry on. False keeps the budget a
    # target the model is asked to meet. Has no effect without a budget.
    enforce_token_budget: bool = True

    # -- when to compact ------------------------------------------------
    # Fold when the context reaches this many tokens. None folds only on agent.compact() or overflow.
    compact_at_tokens: Optional[int] = _COMPACT_AT_TOKENS_UNSET
    # How a request's tokens are counted, for compact_at_tokens and overflow recovery. Unset, a local
    # tiktoken estimate. Set one of these two to count differently:
    # - use_model_token_count: the model the request goes to counts it - count_tokens in sync runs,
    #   acount_tokens in async ones. Exact, but a network call on each check for most providers.
    use_model_token_count: bool = False
    # - token_counter: your own function taking (messages, tools) and returning an int, such as a
    #   Hugging Face tokenizer for an open-weight model. An async one is awaited in async runs and
    #   fails a sync run, which has nothing to await it with.
    token_counter: Optional[TokenCounter] = None

    # -- what to keep ---------------------------------------------------
    # Recent runs kept verbatim.
    uncompacted_runs: Optional[int] = _UNCOMPACTED_RUNS_UNSET
    # Recent history kept verbatim, by size instead of runs. Mutually exclusive with uncompacted_runs.
    uncompacted_tokens: Optional[int] = None

    # -- stored history -------------------------------------------------
    # Store the folded messages in the database so they stay recoverable. The fold and its summary
    # are stored either way; this keeps the original messages too.
    store_compacted_messages: bool = True
    # Give the agent a tool to search the stored messages for detail the summary dropped. Unset, it
    # follows store_compacted_messages.
    search_compacted_messages: Optional[bool] = None

    # Also fold and retry when the provider rejects a request as too long. compaction=True turns it on.
    on_context_overflow: bool = False
    # Skip a fold that would not shrink the context. A summary costs a few hundred tokens whatever it
    # replaces, so folding a span not much bigger than the tail it keeps can leave the context larger.
    # Off by default: every fold the threshold asks for happens.
    enforce_min_fold_ratio: bool = False
    # With enforce_min_fold_ratio, the folded span must be at least this many times the kept tail.
    min_fold_ratio: float = 2.0

    stats: CompactionStats = field(default_factory=CompactionStats)

    def __post_init__(self) -> None:
        if self.id is None:
            self.id = f"compaction_{uuid4().hex[:8]}"
        # Resolve a "provider:model_id" string once, as the other managers do, so every summary
        # call has a Model to call. Anything else is used as given.
        if isinstance(self.model, str):
            self.model = get_model(self.model)
        # Search reads the stored messages, so unset it follows storing them. Asking for search
        # while turning storage off is a contradiction - raise rather than drop it silently.
        if self.search_compacted_messages is None:
            self.search_compacted_messages = self.store_compacted_messages
        elif self.search_compacted_messages and not self.store_compacted_messages:
            raise ValueError(
                "search_compacted_messages=True needs store_compacted_messages=True: the search tool "
                "reads the stored messages, which store_compacted_messages=False does not keep. Turn "
                "storing on, or leave search_compacted_messages unset."
            )
        # Asking for overflow recovery is asking to fold when the provider says so. A default
        # threshold would pre-empt that on any model with a window above it - which is every
        # large model - leaving the flag dead code. An explicit threshold still wins: naming
        # both is a real, if unusual, request for two triggers.
        if self.on_context_overflow and isinstance(self.compact_at_tokens, _UnsetTokens):
            self.compact_at_tokens = None

        if self.token_counter is not None and not callable(self.token_counter):
            raise TypeError(
                f"token_counter must be a function taking (messages, tools) and returning an int, "
                f"got {type(self.token_counter).__name__}"
            )
        if self.use_model_token_count and self.token_counter is not None:
            raise ValueError(
                "use_model_token_count and token_counter cannot both be set - each chooses how tokens are "
                "counted. Use use_model_token_count=True for the model's own count, or token_counter for "
                "a function of your own."
            )
        if self.compact_at_tokens is not None and self.compact_at_tokens <= 0:
            raise ValueError(f"compact_at_tokens must be a positive integer, got {self.compact_at_tokens}")
        if self.uncompacted_runs is not None and self.uncompacted_runs < 0:
            raise ValueError(f"uncompacted_runs must be zero or a positive integer, got {self.uncompacted_runs}")
        if self.uncompacted_tokens is not None and self.uncompacted_tokens <= 0:
            raise ValueError(f"uncompacted_tokens must be a positive integer, got {self.uncompacted_tokens}")
        if self.compacted_token_budget is not None and self.compacted_token_budget <= 0:
            raise ValueError(f"compacted_token_budget must be a positive integer, got {self.compacted_token_budget}")
        # The tail limit divides by 1 + min_fold_ratio, so a negative ratio would divide by zero or
        # flip the limit's sign.
        if self.min_fold_ratio < 0:
            raise ValueError(
                f"min_fold_ratio must be zero or a positive number, got {self.min_fold_ratio}. "
                "Use 0 to fold regardless of size."
            )
        # Raise rather than pick a winner: silently honouring one of two settings the user
        # deliberately set is the kind of surprise that costs an afternoon to track down.
        # None is "not set", which is also what validation leaves behind below - so a config that
        # already passed here passes again when dataclasses.replace() re-runs this.
        runs_chosen = self.uncompacted_runs is not None and not isinstance(self.uncompacted_runs, _Unset)
        if self.uncompacted_tokens is not None and runs_chosen:
            raise ValueError(
                "uncompacted_runs and uncompacted_tokens cannot both be set - they describe the same "
                "kept tail in different units. Use uncompacted_runs to keep whole turns, or "
                "uncompacted_tokens to bound the tail's size."
            )
        if self.uncompacted_tokens is not None:
            # The token budget is authoritative from here on; the run count would otherwise be
            # consulted by every helper that reads it.
            self.uncompacted_runs = None
            self._check_token_tail()
        # compact_at_tokens=None is legal: it disables the automatic trigger and leaves
        # agent.compact() as the only way to fold, which is a coherent way to run this.

    # -- thresholds -----------------------------------------------------

    def _measured_tokens(
        self,
        messages: List[Message],
        context_tokens: Optional[int],
        model: Optional[Model],
        tools: Optional[List[Any]] = None,
    ) -> Optional[int]:
        """Context size in tokens for the current model-bound message view.

        ``context_tokens`` is computed locally by the caller from the messages being considered
        for this request.
        """
        if context_tokens is not None:
            return context_tokens
        counter = model.count_tokens if self.use_model_token_count and model is not None else self.token_counter
        # Reached only when the caller did not count. An async counter cannot be awaited here, so it
        # is left out rather than raising; the local estimate below stands in.
        if not is_async_callable(counter):
            counted = count_request(counter, messages, tools)
            if counted is not None:
                return counted
        try:
            from agno.utils.tokens import count_tokens

            return count_tokens(messages, tools=tools, model_id=self._tokenizer_model_id(model))
        except Exception as e:
            log_warning(f"Could not estimate tokens for compaction: {e}")
            return None

    def should_compact(
        self,
        messages: List[Message],
        *,
        context_tokens: Optional[int] = None,
        model: Optional[Model] = None,
        tools: Optional[List[Any]] = None,
    ) -> bool:
        """Whether the history has grown enough to compact.

        Size is the only automatic trigger, so this is one measurement. Whether the fold is
        worth doing is a separate question, decided by the ratio guard once a boundary exists.
        """
        if self.compact_at_tokens is not None:
            tokens = self._measured_tokens(messages, context_tokens, model, tools)
            if tokens is not None and tokens >= self.compact_at_tokens:
                log_info(f"Compaction: token count {tokens} >= {self.compact_at_tokens}")
                return True

        return False

    # -- boundary -------------------------------------------------------

    def _tail_advice_for(self, kept: List[Message]) -> str:
        """The tail setting, suggested only when changing it could still move the boundary.

        The cut is pair-safe, so it never lands inside a turn. Once the tail holds a single
        turn no smaller budget can shrink it further, and naming the setting sends the reader
        to a knob that cannot help.
        """
        turns = sum(1 for m in kept if m.role == "user")
        if turns <= 1:
            return ""
        return f" or {self._tail_setting}"

    @property
    def _tail_setting(self) -> str:
        """The tail setting actually in force, named for a message the user has to act on.

        Telling someone to lower uncompacted_runs when they configured uncompacted_tokens sends
        them to a setting that is None.
        """
        if self.uncompacted_tokens is not None:
            return f"uncompacted_tokens={self.uncompacted_tokens}"
        return f"uncompacted_runs={self.uncompacted_runs}"

    def _keep_from_index(self, messages: List[Message]) -> Optional[int]:
        """Index the kept tail starts at, for a request expressed in turns.

        ``uncompacted_runs`` names a position, so this returns one. The boundary walk then only
        snaps it earlier for safety - it never moves later, so the cut itself never keeps fewer
        runs than asked. The tail limit can still keep fewer: when the requested runs exceed it, the
        tail is cut to that size (never inside the newest exchange), since a tail that large would
        leave too little in front of it to fold.
        """
        keep_runs = self.uncompacted_runs or 0
        if keep_runs <= 0:
            return len(messages)
        # A user message opens a run.
        user_indexes = [i for i, m in enumerate(messages) if m.role == "user"]
        if len(user_indexes) <= keep_runs:
            # The tail already covers everything, so there is no history in front of it to
            # fold. Returning 0 here would name a boundary at the start of the list, which
            # reads downstream as "fold nothing but measure anyway" - and on a run whose
            # answers keep growing that produces a tail that grows without bound and a ratio
            # that collapses toward zero, reported as if min_fold_ratio had declined a real
            # fold. None says plainly that this pass has nothing to do.
            return None
        return user_indexes[-keep_runs]

    @property
    def _fold_ratio(self) -> float:
        """The ratio a fold must pass: min_fold_ratio when it is enforced, else none."""
        return self.min_fold_ratio if self.enforce_min_fold_ratio else 0.0

    @property
    def _tail_limit(self) -> Optional[int]:
        """The largest tail a fold can keep at the threshold.

        When compact_at_tokens is reached, the history is about that size. A tail of at most
        compact_at_tokens / (1 + ratio) leaves at least ratio times as much in front of it, so the
        fold the threshold asks for is one the ratio accepts. Without an enforced ratio the limit
        is compact_at_tokens itself: a tail that size would leave nothing to fold.
        """
        if self.compact_at_tokens is None:
            return None
        return int(self.compact_at_tokens / (1 + self._fold_ratio))

    def _check_token_tail(self) -> None:
        """An explicit token tail has to leave room to fold at the threshold."""
        limit = self._tail_limit
        if limit is None or self.uncompacted_tokens is None or self.compact_at_tokens is None:
            return
        if self.uncompacted_tokens >= self.compact_at_tokens:
            raise ValueError(
                f"uncompacted_tokens={self.uncompacted_tokens} must be smaller than compact_at_tokens="
                f"{self.compact_at_tokens}: a tail that large holds the whole context, so nothing could fold."
            )
        if self.uncompacted_tokens > limit:
            log_warning(
                f"Compaction: uncompacted_tokens={self.uncompacted_tokens} is too large to fold at "
                f"compact_at_tokens={self.compact_at_tokens} with min_fold_ratio={self.min_fold_ratio} - "
                f"the tail can be at most {limit}. Nothing will fold until the context reaches about "
                f"{int(self.uncompacted_tokens * (1 + self._fold_ratio))} tokens."
            )

    def boundary_for(self, messages: List[Message], min_index: int = 0) -> Optional[int]:
        """Index of the first message kept verbatim, or None when no safe cut exists.

        Delegates to ``choose_boundary``, which snaps the requested tail to a boundary that is
        pair-safe (a tool result never starts the tail, and a batch whose head would fall behind
        the cut moves into the tail whole) and *durable* - it never anchors on a message that
        will not survive in storage, since the anchor has to resolve again on the next run.
        """
        if self.uncompacted_tokens is not None:
            # A size budget names no position, so the walk finds one: it accumulates backward
            # from the newest message and stops once the budget is spent, then snaps to a
            # pair-safe turn boundary like any other cut.
            cut = choose_boundary(messages, keep_tokens=self.uncompacted_tokens, min_index=min_index)
            return self._outside_newest_exchange(messages, cut, min_index)
        return self._run_tail_boundary(messages, min_index)[0]

    @staticmethod
    def _outside_newest_exchange(messages: List[Message], cut: Optional[int], min_index: int) -> Optional[int]:
        """``cut``, moved back to the newest user message when it would fold inside that exchange.

        Folding the question the model is answering would leave it replying to a summary of what
        it was just asked. On overflow recovery it is worse: the list being folded is the current
        run's own, so its question and tool results would be dropped from the stored run too.
        """
        newest = max((i for i, m in enumerate(messages) if m.role == "user"), default=None)
        if cut is not None and newest is not None and cut > newest:
            return choose_boundary(messages, keep_from_index=newest, min_index=min_index)
        return cut

    def _run_tail_boundary(self, messages: List[Message], min_index: int = 0) -> Tuple[Optional[int], bool]:
        """The cut for a run-count tail, and whether the tail limit had to shorten it.

        A run count says how many turns survive, not how large they are, so a few long turns can
        make a tail no fold in front of it can outweigh - the threshold fires and the ratio declines,
        run after run. Past the tail limit the tail is cut by tokens instead. Never inside the newest
        exchange, though: folding the question the model is answering would leave it replying to a
        summary of what it was just asked.
        """
        keep_from = self._keep_from_index(messages)
        boundary = (
            None if keep_from is None else choose_boundary(messages, keep_from_index=keep_from, min_index=min_index)
        )
        limit = self._tail_limit
        if limit is None:
            return boundary, False
        tail_start = min_index if boundary is None else boundary
        if estimate_tokens(messages[tail_start:]) <= limit:
            return boundary, False
        cut = self._outside_newest_exchange(
            messages, choose_boundary(messages, keep_tokens=limit, min_index=min_index), min_index
        )
        if cut is None or cut <= tail_start:
            return boundary, False
        return cut, True

    def _log_tail_limit(self, messages: List[Message], min_index: int) -> None:
        """Say when the tail limit kept fewer runs than uncompacted_runs asks for.

        At info level when the run count was chosen, since that setting is then being overridden;
        at debug level for the default, which nobody picked.
        """
        if self.uncompacted_tokens is not None or not self._run_tail_boundary(messages, min_index)[1]:
            return
        message = (
            f"Compaction: the last {self.uncompacted_runs} runs exceed the {self._tail_limit}-token tail "
            f"limit, so the kept tail was cut to that size."
        )
        if isinstance(self.uncompacted_runs, _Unset):
            log_debug(message)
        else:
            log_info(message)

    def _warn_if_still_over(self, record: CompactionRecord) -> None:
        """A fold that leaves the context at or over the threshold will fold again next run."""
        if self.compact_at_tokens is None or not record.tokens_after:
            return
        if record.tokens_after >= self.compact_at_tokens:
            log_warning(
                f"Compaction: after folding, the context is still {record.tokens_after} tokens, at or over "
                f"compact_at_tokens={self.compact_at_tokens}, so the next run will fold again. The system "
                f"prompt, tools, and kept tail leave too little room - raise compact_at_tokens or keep a "
                f"smaller tail."
            )

    # -- summarizing ----------------------------------------------------

    def _trim_for_summary(self, messages: List[Message]) -> List[Message]:
        """Drop the oldest messages that do not fit the summarizer's budget.

        Each message is measured as it is rendered for the summarizer, so a large tool result
        counts at its clipped size - the text actually sent - rather than spending budget on
        characters the summarizer never receives.
        """
        kept: List[Message] = []
        budget = DEFAULT_SUMMARIZE_CHAR_BUDGET
        for message in reversed(messages):
            size = len(render_message(message)) + 2  # + the block separator
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
        budget = self.compacted_token_budget
        if budget is None:
            length_rule = LENGTH_RULE_COMPACT
        else:
            # The model cannot count tokens, but words and characters it can estimate - stating
            # all three gives it more than one way to land near the budget.
            length_rule = LENGTH_RULE_BUDGET.format(
                budget_tokens=budget, budget_words=round(budget * 0.75), budget_characters=budget * 4
            )
        prompt = DEFAULT_COMPACTION_PROMPT.format(length_rule=length_rule)
        if self.instructions:
            # Added to, not instead of, the prompt: guidance like "keep ticket ids" must not cost
            # the structure that carries earlier summaries forward.
            prompt += f"\n\nAdditional instructions:\n{self.instructions}"
        # Only ask the summary to flag its own gaps when there is somewhere to
        # go and read them. Without an archive the line would name detail the
        # assistant has no way to recover, which is worse than not saying it.
        if archived:
            prompt += ARCHIVE_AWARE_PROMPT
        return [
            Message(role="system", content=prompt),
            Message(role="user", content=transcript),
        ]

    def _fit_to_budget(self, summary: str, searchable: bool) -> str:
        """The summary, cut from the end to compacted_token_budget when one is set and enforced.

        Without a budget the summary is returned as written. The cut keeps whole lines - never
        half an identifier that would read as real data - and drops a heading left with nothing
        under it. A note replaces what was cut, so the agent knows the summary is incomplete
        rather than trusting it.
        """
        budget = self.compacted_token_budget
        if budget is None or not self.enforce_token_budget:
            return summary

        from agno.utils.tokens import count_text_tokens

        model_id = self._tokenizer_model_id()
        before = count_text_tokens(summary, model_id)
        if before <= budget:
            return summary

        note = SUMMARY_CUT_NOTE_SEARCHABLE if searchable else SUMMARY_CUT_NOTE

        def with_note(kept: List[str]) -> str:
            # A heading with nothing under it says nothing; drop it with what was cut.
            while kept and (not kept[-1].strip() or kept[-1].lstrip().startswith("#")):
                kept = kept[:-1]
            return "\n".join(kept + ["", note]) if kept else note

        def fits(text: str) -> bool:
            return count_text_tokens(text, model_id) <= budget

        def longest(count: int, fits_with: "Callable[[int], bool]") -> int:
            # The most leading items that fit. Longer prefixes only grow, so search for it.
            low, high = 0, count
            while low < high:
                middle = (low + high + 1) // 2
                if fits_with(middle):
                    low = middle
                else:
                    high = middle - 1
            return low

        lines = summary.splitlines()
        kept = longest(len(lines), lambda n: fits(with_note(lines[:n])))
        fitted = with_note(lines[:kept])
        # Fill the room left with whole words of the next line, so one long line - a paragraph-style
        # section - does not waste the rest of the budget. Words stay whole, so no identifier is cut.
        if kept < len(lines) and lines[kept].strip() and not lines[kept].lstrip().startswith("#"):
            words = lines[kept].split(" ")
            taken = longest(len(words), lambda n: fits(with_note(lines[:kept] + [" ".join(words[:n]) + " ..."])))
            if taken:
                fitted = with_note(lines[:kept] + [" ".join(words[:taken]) + " ..."])
        if not fits(fitted):
            # A budget smaller than the note itself: no room to say what was cut, so keep as many
            # leading words as fit and nothing else.
            words = summary.split()
            fitted = " ".join(words[: longest(len(words), lambda n: fits(" ".join(words[:n])))])
        log_info(
            f"Compaction: the summary was {before} tokens against a {budget}-token budget, so it was cut to "
            f"{count_text_tokens(fitted, model_id)} tokens."
        )
        return fitted

    def _summarize(
        self,
        messages: List[Message],
        previous: Optional[str],
        run_metrics: Optional["RunMetrics"] = None,
        archived: bool = False,
    ) -> Optional[str]:
        model = self._summary_model()
        if model is None:
            log_warning("No compaction model available")
            return None
        try:
            response = model.response(messages=self._summary_messages(messages, previous, archived))
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
        model = self._summary_model()
        if model is None:
            log_warning("No compaction model available")
            return None
        try:
            response = await model.aresponse(messages=self._summary_messages(messages, previous, archived))
        except Exception as e:
            log_error(f"Error compacting conversation: {e}")
            return None
        self._accumulate(response, run_metrics)
        return response.content

    def _summary_model(self) -> Optional[Model]:
        # __post_init__ resolved any string, so this is a Model or None.
        return cast(Optional[Model], self.model)

    def _tokenizer_model_id(self, model: Optional[Any] = None) -> str:
        """The model id the local token count is keyed on: the given model's, then the summarizer's.

        Only an encoding is chosen by it. Ids the tokenizer does not know map to the encoding
        current OpenAI models use, so the fallback is the framework's default model id rather
        than any particular one it recognises.
        """
        for candidate in (model, self.model):
            model_id = getattr(candidate, "id", None)
            if model_id:
                return cast(str, model_id)
        return DEFAULT_TOKENIZER_MODEL_ID

    def _accumulate(self, response: Any, run_metrics: Optional["RunMetrics"]) -> None:
        model = self._summary_model()
        if run_metrics is None or model is None:
            return
        from agno.metrics import ModelType, accumulate_model_metrics

        accumulate_model_metrics(response, model, ModelType.COMPACTION_MODEL, run_metrics)

    # -- archive --------------------------------------------------------

    def archive_for(
        self, session_id: str, db: Optional[Any] = None, user_id: Optional[str] = None
    ) -> Optional[CompactionArchive]:
        """The record store for one session, or None without a database.

        Fold records are kept whatever ``store_compacted_messages`` says - they are what makes a fold
        outlast the run that made it. It decides only whether the folded messages go in with them.
        """
        if db is None:
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
        if record.archived and self.search_compacted_messages:
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

        model_id = self._tokenizer_model_id()
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

        ``strip_provider_chaining`` removes only the chaining keys from assistant copies. Some
        providers continue a conversation by id rather than from the messages sent (OpenAI
        Responses on ``previous_response_id``, GeminiInteractions on ``previous_interaction_id``),
        and the server then replays the whole
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
        if not (self.search_compacted_messages and record.archived):
            return None
        return ARCHIVE_LOOKUP_INSTRUCTION

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
        if self._fold_ratio <= 0:
            return True
        fold_tokens = estimate_tokens([m for m in to_compact if not is_offload_envelope(m)])
        keep_tokens = max(estimate_tokens([m for m in kept if not is_offload_envelope(m)]), 1)
        ratio = fold_tokens / keep_tokens
        if ratio < self._fold_ratio:
            # log_info, not debug: a threshold was crossed and the user was told so. Going
            # quiet after that reads as a bug. Say what was declined and why.
            #
            # Continuing is named first because it is usually the real answer: the fold grows
            # with every turn while the tail stays roughly fixed, so the ratio climbs on its
            # own. Shrinking the tail only helps while it still holds more than one turn - the
            # cut is pair-safe, so no setting can cut inside a turn, and advice to lower it is
            # a dead end once the tail is already a single turn.
            log_info(
                f"Compaction: threshold reached but skipping this fold - it would replace "
                f"{fold_tokens} tokens with a summary while keeping a {keep_tokens}-token tail "
                f"(ratio {ratio:.2f} < min_fold_ratio {self.min_fold_ratio}), which would not "
                f"shrink the context. Continue the conversation - the fold grows while the tail "
                f"does not - or lower min_fold_ratio{self._tail_advice_for(kept)}, or set "
                f"enforce_min_fold_ratio=False, to fold sooner."
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
        boundary, _, _ = self.plan_with_reason(messages, previous)
        return boundary

    def plan_with_reason(
        self, messages: List[Message], previous: Optional[CompactionRecord] = None
    ) -> Tuple[Optional[int], "CompactionStatus", str]:
        """``plan``, plus why it decided that.

        An explicit caller - an API route, a UI - has to tell a decline apart from a failure and
        show the reason. Deriving that from the log line would mean two descriptions of one
        decision, free to drift; this is the single source both use.
        """
        from agno.compaction.types import CompactionStatus

        already = self._resolved_boundary(messages, previous)
        boundary = self.boundary_for(messages, min_index=already)
        if boundary is None or boundary <= already:
            if previous is None:
                reason = (
                    f"Nothing to fold yet - {self._tail_setting} covers the whole "
                    f"conversation, so there is no history before the kept tail. Lower it to fold sooner."
                )
                log_info(f"Compaction: threshold reached but {reason[0].lower()}{reason[1:]}")
                return None, CompactionStatus.NOTHING_TO_FOLD, reason
            reason = "No safe cut past the previous fold yet - the conversation has not grown enough since then."
            log_info(f"Compaction: threshold reached but {reason[0].lower()}{reason[1:]}")
            return None, CompactionStatus.ALREADY_COMPACTED, reason
        if not self._worth_compacting(messages[already:boundary], messages[boundary:]):
            # Carry the numbers, not just the verdict: "not worth it" with no figures leaves a
            # caller unable to tell a fold that missed by a hair from one that was never close,
            # and the ratio is the one thing that says which lever to reach for.
            fold_tokens = estimate_tokens([m for m in messages[already:boundary] if not is_offload_envelope(m)])
            keep_tokens = max(estimate_tokens([m for m in messages[boundary:] if not is_offload_envelope(m)]), 1)
            return (
                None,
                CompactionStatus.NOT_WORTH_IT,
                f"This fold would replace {fold_tokens} tokens against a {keep_tokens}-token tail "
                f"(ratio {fold_tokens / keep_tokens:.2f}, needs {self.min_fold_ratio}), so the "
                f"context would not shrink. Continue the conversation, or lower "
                f"{self._tail_setting} or "
                f"min_fold_ratio, or set enforce_min_fold_ratio=False, to fold sooner.",
            )
        return boundary, CompactionStatus.COMPACTED, "Ready to compact."

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
        context_prefix: Optional[List[Message]] = None,
        user_id: Optional[str] = None,
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
        archive = self.archive_for(session_id, db, user_id)

        summary = self._summarize(
            to_compact,
            previous.summary if previous else None,
            run_metrics,
            archived=self.store_compacted_messages and archive is not None,
        )
        if not summary:
            return None
        summary = self._fit_to_budget(summary, searchable=bool(self.search_compacted_messages and archive is not None))

        record = self.build_record(
            messages, summary, messages[boundary].id, len(to_compact), tokens_before, run_id=run_id
        )
        # Size the fold before persisting: the row is written once and never updated, so a
        # measurement taken afterwards would never reach it.
        prefix = context_prefix or []
        self.measure(record, prefix + messages, prefix + self.apply_record(messages, record))
        self._log_tail_limit(messages, already)
        self._warn_if_still_over(record)
        if archive is not None:
            # The record is stored either way; the transcript only when archiving is on.
            stored = archive.write(record, to_compact if self.store_compacted_messages else [])
            record.archived = stored and self.store_compacted_messages
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
        context_prefix: Optional[List[Message]] = None,
        user_id: Optional[str] = None,
    ) -> Optional[CompactionRecord]:
        # See the sync path: only the span the previous compaction did not
        # already cover is new.
        boundary = self.plan(messages, previous)
        if boundary is None:
            return None

        already = self._resolved_boundary(messages, previous)
        to_compact = messages[already:boundary]
        archive = self.archive_for(session_id, db, user_id)

        summary = await self._asummarize(
            to_compact,
            previous.summary if previous else None,
            run_metrics,
            archived=self.store_compacted_messages and archive is not None,
        )
        if not summary:
            return None
        summary = self._fit_to_budget(summary, searchable=bool(self.search_compacted_messages and archive is not None))

        record = self.build_record(
            messages, summary, messages[boundary].id, len(to_compact), tokens_before, run_id=run_id
        )
        # Size the fold before persisting: the row is written once and never updated, so a
        # measurement taken afterwards would never reach it.
        prefix = context_prefix or []
        self.measure(record, prefix + messages, prefix + self.apply_record(messages, record))
        self._log_tail_limit(messages, already)
        self._warn_if_still_over(record)
        if archive is not None:
            # The record is stored either way; the transcript only when archiving is on.
            stored = archive.write(record, to_compact if self.store_compacted_messages else [])
            record.archived = stored and self.store_compacted_messages
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
        if not (self.search_compacted_messages and self.store_compacted_messages):
            return None
        archive = self.archive_for(session_id, db)
        if archive is None or archive.latest() is None:
            return None

        def search_compacted_history(pattern: str, context_lines: int = 2) -> str:
            """Search the earlier conversation that was compacted out of context.

            Use this when a question needs an exact value - an identifier, figure, name, quote,
            command, or error message - that the summary does not carry.

            Args:
                pattern: Text to find, matched case-insensitively line by line against the
                    stored transcript. Separate alternatives with "|" to find any of them,
                    e.g. "build hash|rotation window".
                context_lines: Lines of surrounding context to show around each match (at most 10).
            """
            rows = archive.search(pattern, limit=_SEARCH_MAX_FOLDS)
            if not rows:
                return f"No compacted history matches {pattern[:200]!r}."
            blocks: List[str] = []
            used = 0
            for row in rows:
                hits = _grep(row.get("archived_messages") or "", pattern, context_lines)
                if not hits:
                    continue
                # The cap holds across folds too, not just within each one.
                if blocks and used + len(hits) > _SEARCH_OUTPUT_CHARS:
                    blocks.append("... more matches in older folds; narrow the search.")
                    break
                blocks.append(hits)
                used += len(hits)
            if not blocks:
                return f"No compacted history matches {pattern[:200]!r}."
            return "\n\n---\n\n".join(blocks)

        return [search_compacted_history]


def _clip_line(line: str, match_start: Optional[int]) -> str:
    """A line cut to _SEARCH_LINE_CHARS, kept around the match so the hit itself survives."""
    if len(line) <= _SEARCH_LINE_CHARS:
        return line
    center = match_start if match_start is not None else 0
    start = max(0, min(center - _SEARCH_LINE_CHARS // 2, len(line) - _SEARCH_LINE_CHARS))
    end = start + _SEARCH_LINE_CHARS
    return ("..." if start > 0 else "") + line[start:end] + ("..." if end < len(line) else "")


def _grep(text: str, pattern: str, context_lines: int = 2, max_matches: int = 20) -> str:
    """Matching lines with surrounding context, numbered - the shape `grep -n -C` returns.

    The pattern is literal text, with "|" separating alternatives - never a regular expression. It
    comes from a model, and a regex like "(a+)+$" backtracks for hours on a 40-character line,
    which Python cannot interrupt. Literal alternatives match in linear time and cover what the
    tool is for: recovering an exact value.

    SQL prefilters which rows are worth scanning, so this only ever runs over candidates. Output is
    bounded - context lines, line length, and total size - since it goes into the context window.
    """
    import re

    terms = search_terms(pattern)
    if not terms:
        return ""
    compiled = re.compile("|".join(re.escape(term) for term in terms), re.IGNORECASE)
    context_lines = max(0, min(context_lines, _SEARCH_MAX_CONTEXT_LINES))

    lines = text.split("\n")
    hits = {}
    for i, line in enumerate(lines):
        found = compiled.search(line)
        if found:
            hits[i] = found.start()
    if not hits:
        return ""

    hit_indexes = sorted(hits)
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

    rendered = ""
    for span_start, span_end in spans:
        block = "\n".join(f"{i + 1}: {_clip_line(lines[i], hits.get(i))}" for i in range(span_start, span_end))
        candidate = block if not rendered else f"{rendered}\n--\n{block}"
        if len(candidate) > _SEARCH_OUTPUT_CHARS:
            truncated = True
            break
        rendered = candidate
    if not rendered:
        # Even the first block is over the limit; return its start rather than nothing.
        rendered = candidate[:_SEARCH_OUTPUT_CHARS]
    if truncated:
        rendered += "\n... more matches than fit; narrow the search."
    return rendered


__all__ = ["Compaction", "DEFAULT_COMPACTION_PROMPT"]
