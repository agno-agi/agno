"""Context compaction: bounded model input over an unbounded, append-only transcript.

The transcript (stored runs) is never mutated. A compaction pass produces a CompactionRecord —
summary, boundary pointer, elision watermark — and model input is derived per provider call from the
canonical message list plus the active record. Dropping a record undoes its compaction.
"""

from dataclasses import dataclass, field
from math import floor
from time import time
from typing import TYPE_CHECKING, Any, Dict, List, Literal, Optional
from uuid import uuid4

if TYPE_CHECKING:
    from agno.models.base import Model

# Fallback when neither the config nor the agent's model declares a context window.
DEFAULT_CONTEXT_WINDOW = 200_000
DEFAULT_RESERVE_TOKENS = 16_384
DEFAULT_KEEP_RECENT_TOKENS = 20_000
DEFAULT_SUMMARY_BUDGET_TOKENS = 2_000
DEFAULT_TRIGGER_RATIO = 0.85
DEFAULT_BACKGROUND_START_RATIO = 0.70

CompactionReason = Literal["threshold", "overflow", "requested", "manual"]


@dataclass
class CompactionRecord:
    """One compaction pass's outcome. Self-contained: the active record alone determines the view.

    An elision-only record copies its predecessor's summary/boundary fields and advances only the
    elision watermark.
    """

    id: str = ""
    created_at: int = 0  # epoch seconds, matching session-row timestamps
    # Set iff the fold segment includes the creating run's own (non-history) messages; None for
    # build-time, manual, and post-run passes, which cover only completed runs and are always valid.
    created_by_run_id: Optional[str] = None
    reason: CompactionReason = "threshold"
    summary: Optional[str] = None  # None for an elision-only record
    first_kept_run_id: Optional[str] = None  # boundary anchor; None when no cut (elision-only)
    first_kept_run_index: Optional[int] = None
    first_kept_message_id: Optional[str] = None
    # Index into the stored run's message list as persisted (post-scrub shape); the id wins on conflict.
    first_kept_message_index: Optional[int] = None
    # Id of the first message kept un-elided; tool results before it render as placeholders. Monotonic.
    elision_watermark_message_id: Optional[str] = None
    notice: Optional[str] = None  # survival notice text, generated at pass time, pinned here
    previous_id: Optional[str] = None  # fold provenance; chain order is (created_at, id), not this
    stats: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def create(
        cls,
        reason: CompactionReason,
        previous_id: Optional[str] = None,
        created_by_run_id: Optional[str] = None,
    ) -> "CompactionRecord":
        return cls(
            id="cmp_" + str(uuid4()),
            created_at=int(time()),
            created_by_run_id=created_by_run_id,
            reason=reason,
            previous_id=previous_id,
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "created_at": self.created_at,
            "created_by_run_id": self.created_by_run_id,
            "reason": self.reason,
            "summary": self.summary,
            "first_kept_run_id": self.first_kept_run_id,
            "first_kept_run_index": self.first_kept_run_index,
            "first_kept_message_id": self.first_kept_message_id,
            "first_kept_message_index": self.first_kept_message_index,
            "elision_watermark_message_id": self.elision_watermark_message_id,
            "notice": self.notice,
            "previous_id": self.previous_id,
            "stats": self.stats,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CompactionRecord":
        return cls(
            id=data.get("id", ""),
            created_at=data.get("created_at", 0),
            created_by_run_id=data.get("created_by_run_id"),
            reason=data.get("reason", "threshold"),
            summary=data.get("summary"),
            first_kept_run_id=data.get("first_kept_run_id"),
            first_kept_run_index=data.get("first_kept_run_index"),
            first_kept_message_id=data.get("first_kept_message_id"),
            first_kept_message_index=data.get("first_kept_message_index"),
            elision_watermark_message_id=data.get("elision_watermark_message_id"),
            notice=data.get("notice"),
            previous_id=data.get("previous_id"),
            stats=data.get("stats") or {},
        )


def record_sort_key(record: CompactionRecord) -> Any:
    """Chain order: (created_at, id). Concurrent writers can produce sibling records sharing one
    previous_id; list order resolves what a previous_id walk could not."""
    return (record.created_at, record.id)


@dataclass
class EffectiveLimits:
    """Window-relative limits, resolved from a Compaction config and a context window."""

    window: int
    reserve_eff: int
    keep_eff: int
    trigger_tokens: int
    soft_trigger_tokens: Optional[int]  # None when background passes are off

    @property
    def worth_it_floor(self) -> int:
        # threshold/requested passes are skipped below this; overflow/manual are exempt.
        return 2 * self.keep_eff


@dataclass
class Compaction:
    """Context-compaction configuration. Attach with Agent(compaction=True) for defaults, or
    Agent(compaction=Compaction(...)) for the detailed form.

    Knob fields default to None meaning "unset": an unset knob resolves to its documented default and
    clamps silently on small windows, while an explicitly set nonsensical value raises at init.
    """

    # Summariser model; None = the agent's model.
    model: Optional["Model"] = None
    # Context window override; None = the agent model's context_window, else 200_000.
    context_window: Optional[int] = None
    # Headroom that triggers a pass (output + compaction room). Default 16_384.
    reserve_tokens: Optional[int] = None
    # Fraction-of-window ceiling; effective trigger = min of the two. Default 0.85.
    trigger_ratio: Optional[float] = None
    # Raw tail retained after a cut. Default 20_000.
    keep_recent_tokens: Optional[int] = None
    # Summariser output budget. Default 2_000.
    summary_budget_tokens: Optional[int] = None
    # Start threshold passes early and in the background at the soft trigger; the hard trigger stays
    # as the synchronous backstop either way.
    background: bool = True
    # Soft-trigger fraction of the window. Default 0.70.
    background_start_ratio: Optional[float] = None
    # Enable the zero-LLM elision phase.
    clear_tool_results: bool = True
    # Tool names whose results are never elided.
    elide_exclude_tools: Optional[List[str]] = None
    # Persistent steering appended to the summariser prompt. Trusted (config-level).
    instructions: Optional[str] = None
    # Register compact_status() / compact_run() model tools.
    expose_tools: bool = False

    @property
    def summary_budget(self) -> int:
        return self.summary_budget_tokens if self.summary_budget_tokens is not None else DEFAULT_SUMMARY_BUDGET_TOKENS

    def resolve_window(self, model_context_window: Optional[int] = None) -> int:
        if self.context_window is not None:
            return self.context_window
        if model_context_window is not None:
            return model_context_window
        return DEFAULT_CONTEXT_WINDOW

    def resolve_limits(self, model_context_window: Optional[int] = None) -> EffectiveLimits:
        """Resolve window-relative effective limits, validating explicit config.

        Raises ValueError when an explicitly set knob is nonsensical for the resolved window; unset
        knobs clamp silently instead.
        """
        window = self.resolve_window(model_context_window)
        if window <= 0:
            raise ValueError(f"Compaction context window must be positive, got {window}")

        reserve_set = self.reserve_tokens is not None
        keep_set = self.keep_recent_tokens is not None
        reserve = self.reserve_tokens if self.reserve_tokens is not None else DEFAULT_RESERVE_TOKENS
        keep = self.keep_recent_tokens if self.keep_recent_tokens is not None else DEFAULT_KEEP_RECENT_TOKENS
        trigger_ratio = self.trigger_ratio if self.trigger_ratio is not None else DEFAULT_TRIGGER_RATIO

        # An explicitly set value at or above the window is a config error, not something to clamp.
        if keep_set and keep >= window:
            raise ValueError(
                f"Compaction keep_recent_tokens ({keep}) must be smaller than the context window ({window})"
            )
        if reserve_set and reserve >= window:
            raise ValueError(f"Compaction reserve_tokens ({reserve}) must be smaller than the context window ({window})")

        reserve_eff = min(reserve, window // 8)
        keep_eff = min(keep, window // 4)
        trigger_tokens = max(min(window - reserve_eff, floor(window * trigger_ratio)), reserve_eff)

        # The trigger-to-keep gap is the anti-thrash buffer; a config that erases it must fail loudly.
        if trigger_tokens - keep_eff < reserve_eff:
            raise ValueError(
                f"Compaction trigger ({trigger_tokens}) minus keep_recent_tokens ({keep_eff}) must leave at "
                f"least reserve_tokens ({reserve_eff}) of headroom; raise trigger_ratio or lower keep_recent_tokens"
            )

        soft_trigger_tokens: Optional[int] = None
        if self.background:
            ratio_set = self.background_start_ratio is not None
            ratio = self.background_start_ratio if self.background_start_ratio is not None else DEFAULT_BACKGROUND_START_RATIO
            soft = floor(window * ratio)
            lower = keep_eff + reserve_eff
            upper = trigger_tokens - reserve_eff
            clamped = min(max(soft, lower), upper)
            if ratio_set and clamped != soft:
                raise ValueError(
                    f"Compaction background_start_ratio ({ratio}) yields a soft trigger of {soft} tokens, "
                    f"outside the valid band [{lower}, {upper}] for a {window}-token window"
                )
            soft_trigger_tokens = clamped

        return EffectiveLimits(
            window=window,
            reserve_eff=reserve_eff,
            keep_eff=keep_eff,
            trigger_tokens=trigger_tokens,
            soft_trigger_tokens=soft_trigger_tokens,
        )
