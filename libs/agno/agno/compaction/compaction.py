"""Context compaction: bounded model input over an unbounded, append-only transcript.

The transcript (stored runs) is never mutated. A compaction pass produces a CompactionRecord —
summary, boundary pointer, elision watermark — and model input is derived per provider call from the
canonical message list plus the active record. Dropping a record undoes its compaction.
"""

from dataclasses import dataclass, field
from math import floor
from time import time
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Literal, Optional
from uuid import uuid4

if TYPE_CHECKING:
    from agno.compaction._notice import NoticeInputs
    from agno.metrics import RunMetrics
    from agno.models.base import Model
    from agno.models.message import Message

# The session_data key all owner chains live under.
COMPACTION_SESSION_KEY = "compaction"

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
    # Epoch seconds. Sub-second precision matters: successive passes inside one second would
    # otherwise sort by random id and scramble the chain order L1 walks.
    created_at: float = 0.0
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
            created_at=time(),
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
            created_at=float(data.get("created_at") or 0.0),
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


def get_owner_records(session_data: Optional[Dict[str, Any]], owner_id: str) -> List[CompactionRecord]:
    """The owner's committed chain, oldest first. Every read resolves one owner's chain only —
    member agents and co-hosted agents on a shared session must never see each other's summaries."""
    if not session_data:
        return []
    raw = (session_data.get(COMPACTION_SESSION_KEY) or {}).get(owner_id, {}).get("records") or []
    records = [CompactionRecord.from_dict(item) for item in raw if isinstance(item, dict)]
    records.sort(key=record_sort_key)
    return records


def merge_records_into_session_data(
    session_data: Dict[str, Any], owner_id: str, records: List[CompactionRecord]
) -> Dict[str, Any]:
    """Merge records into the session row's compaction key: union by id, ordered (created_at, id).

    The session row is a last-write-wins whole-object upsert, so persistence must merge against
    what the row holds now, never overwrite — concurrent runs each land their records.
    """
    compaction = session_data.setdefault(COMPACTION_SESSION_KEY, {})
    owner_slot = compaction.setdefault(owner_id, {})
    existing = {item.get("id"): item for item in owner_slot.get("records") or [] if isinstance(item, dict)}
    for record in records:
        existing[record.id] = record.to_dict()
    merged = sorted(existing.values(), key=lambda item: (item.get("created_at", 0), item.get("id", "")))
    owner_slot["records"] = merged
    return session_data


def resolve_active_record(
    chain: List[CompactionRecord],
    *,
    record_is_valid: Callable[[CompactionRecord], bool],
) -> Optional[CompactionRecord]:
    """The newest valid record, walking the (created_at, id)-ordered chain backward.

    Validity is the caller's predicate: the creating run (when set) must not carry a skip status,
    and the boundary must resolve against the messages available to this build. An empty walk
    means no record — full history, fail open."""
    for record in reversed(chain):
        try:
            if record_is_valid(record):
                return record
        except Exception:
            continue
    return None


def _elidable_count(messages: List["Message"], watermark_id: Optional[str], exclude_tools: Optional[List[str]]) -> int:
    """How many tool results a watermark actually elides in this list."""
    from agno.compaction._cut import is_offload_envelope

    if watermark_id is None:
        return 0
    exclude = set(exclude_tools or [])
    count = 0
    for message in messages:
        if message.id == watermark_id:
            return count
        if message.role == "tool" and not is_offload_envelope(message) and (message.tool_name or "") not in exclude:
            count += 1
    return 0


@dataclass
class PassPlan:
    """A prepared pass: everything a fold needs, frozen at pass start.

    The rendered segment is flat text over messages that already exist, so executing the plan in
    the background races with nothing — appends after preparation land past the chosen boundary."""

    reason: CompactionReason
    created_by_run_id: Optional[str]
    previous_record: Optional[CompactionRecord]
    elision_only: bool
    watermark_id: Optional[str]
    boundary_index: Optional[int]
    boundary_message_id: Optional[str]
    rendered_segment: Optional[str]
    previous_summary: Optional[str]
    notice: Optional[str]
    tokens_before: int
    call_instructions: Optional[str] = None
    untrusted_instructions: Optional[str] = None
    segment_message_count: int = 0


def prepare_pass(
    config: Compaction,
    limits: EffectiveLimits,
    messages: List["Message"],
    *,
    reason: CompactionReason,
    previous_record: Optional[CompactionRecord] = None,
    min_boundary_index: int = 0,
    created_by_run_id: Optional[str] = None,
    notice_inputs: Optional["NoticeInputs"] = None,
    call_instructions: Optional[str] = None,
    untrusted_instructions: Optional[str] = None,
    allow_tool_batch_heads: bool = True,
    elision_target_tokens: Optional[int] = None,
) -> Optional[PassPlan]:
    """Decide what a pass does: elide, and fold only if the elided view is still over target.

    The target defaults to the hard trigger; a soft-trigger (background) pass passes the soft
    trigger instead, so an early pass folds rather than declaring victory below the hard line.
    Pure over the given list — no model call, no persistence. Returns None when there is nothing
    to do or no valid cut exists (the pass aborts rather than cutting unsafely)."""
    from agno.compaction._cut import choose_boundary, choose_watermark, keep_tail_start, leading_system_count
    from agno.compaction._notice import build_survival_notice
    from agno.compaction._summarize import render_segment
    from agno.compaction._tokens import estimate_tokens
    from agno.compaction._view import build_view

    lead = leading_system_count(messages)
    floor_index = max(min_boundary_index, lead)

    prev_boundary_index: Optional[int] = None
    if previous_record is not None and previous_record.first_kept_message_id:
        for index in range(lead, len(messages)):
            if messages[index].id == previous_record.first_kept_message_id:
                prev_boundary_index = index
                break
        if prev_boundary_index is None:
            # The previous boundary does not resolve here; treat the record as absent so its
            # summary is never injected over an unapplied cut.
            previous_record = None

    tail_start = keep_tail_start(messages, limits.keep_eff, start=max(floor_index, prev_boundary_index or 0))

    # Elision phase: advance the watermark, monotonically.
    watermark_id: Optional[str] = None
    if config.clear_tool_results:
        watermark_id = choose_watermark(messages, tail_start, min_index=lead)
        if previous_record is not None and previous_record.elision_watermark_message_id and watermark_id:
            previous_index = None
            new_index = None
            for index, message in enumerate(messages):
                if message.id == previous_record.elision_watermark_message_id:
                    previous_index = index
                if message.id == watermark_id:
                    new_index = index
            if previous_index is not None and new_index is not None and new_index < previous_index:
                watermark_id = previous_record.elision_watermark_message_id
        elif watermark_id is None and previous_record is not None:
            watermark_id = previous_record.elision_watermark_message_id
    elif previous_record is not None:
        watermark_id = previous_record.elision_watermark_message_id

    notice = build_survival_notice(notice_inputs) if notice_inputs is not None else None
    tokens_before = estimate_tokens(
        build_view(messages, previous_record, elide_exclude_tools=config.elide_exclude_tools)
    )

    if reason != "manual":
        trial = CompactionRecord.from_dict(previous_record.to_dict()) if previous_record else CompactionRecord()
        trial.elision_watermark_message_id = watermark_id
        elided_estimate = estimate_tokens(build_view(messages, trial, elide_exclude_tools=config.elide_exclude_tools))
        # The watermark advanced only if it newly elides something; a moved pointer with no tool
        # result behind it is not a pass worth a record.
        previous_watermark = previous_record.elision_watermark_message_id if previous_record else None
        watermark_advanced = watermark_id is not None and watermark_id != previous_watermark and _elidable_count(
            messages, watermark_id, config.elide_exclude_tools
        ) > _elidable_count(messages, previous_watermark, config.elide_exclude_tools)
        target = elision_target_tokens if elision_target_tokens is not None else limits.trigger_tokens
        if elided_estimate <= target:
            if not watermark_advanced:
                return None
            return PassPlan(
                reason=reason,
                created_by_run_id=created_by_run_id,
                previous_record=previous_record,
                elision_only=True,
                watermark_id=watermark_id,
                boundary_index=None,
                boundary_message_id=None,
                rendered_segment=None,
                previous_summary=previous_record.summary if previous_record else None,
                notice=notice if notice else (previous_record.notice if previous_record else None),
                tokens_before=tokens_before,
            )

    boundary_index = choose_boundary(
        messages,
        limits.keep_eff,
        min_index=max(floor_index, prev_boundary_index or 0),
        allow_tool_batch_heads=allow_tool_batch_heads,
    )
    if boundary_index is None:
        return None

    segment = messages[(prev_boundary_index if prev_boundary_index is not None else lead) : boundary_index]
    rendered = render_segment(segment)
    if not rendered.strip():
        return None
    return PassPlan(
        reason=reason,
        created_by_run_id=created_by_run_id,
        previous_record=previous_record,
        elision_only=False,
        watermark_id=watermark_id,
        boundary_index=boundary_index,
        boundary_message_id=messages[boundary_index].id,
        rendered_segment=rendered,
        previous_summary=previous_record.summary if previous_record else None,
        notice=notice,
        tokens_before=tokens_before,
        call_instructions=call_instructions,
        untrusted_instructions=untrusted_instructions,
        segment_message_count=len(segment),
    )


def _record_from_plan(plan: PassPlan, summary: Optional[str], duration_ms: int, model_id: Optional[str]) -> CompactionRecord:
    record = CompactionRecord.create(
        plan.reason,
        previous_id=plan.previous_record.id if plan.previous_record else None,
        created_by_run_id=plan.created_by_run_id,
    )
    record.elision_watermark_message_id = plan.watermark_id
    record.notice = plan.notice or None
    if plan.elision_only:
        previous = plan.previous_record
        record.summary = previous.summary if previous else None
        record.first_kept_run_id = previous.first_kept_run_id if previous else None
        record.first_kept_run_index = previous.first_kept_run_index if previous else None
        record.first_kept_message_id = previous.first_kept_message_id if previous else None
        record.first_kept_message_index = previous.first_kept_message_index if previous else None
    else:
        record.summary = summary
        record.first_kept_message_id = plan.boundary_message_id
    record.stats = {
        "tokens_before": plan.tokens_before,
        "messages_folded": plan.segment_message_count,
        "summarizer_model_id": model_id,
        "duration_ms": duration_ms,
    }
    return record


def complete_pass(
    plan: PassPlan,
    *,
    config: Compaction,
    model: Optional["Model"],
    summarizer_window: Optional[int] = None,
    run_metrics: Optional["RunMetrics"] = None,
) -> CompactionRecord:
    """Execute a prepared pass: the fold call for a folding plan, nothing for an elision-only one.

    Summariser exceptions propagate; the caller owns fail-open (no record, no state change)."""
    from agno.compaction._summarize import fold

    started = time()
    summary: Optional[str] = None
    model_id: Optional[str] = None
    if not plan.elision_only:
        if model is None:
            raise ValueError("Compaction fold requires a summariser model")
        model_id = model.id
        summary = fold(
            model,
            plan.previous_summary,
            plan.rendered_segment or "",
            budget_tokens=config.summary_budget,
            summarizer_window=summarizer_window,
            config_instructions=config.instructions,
            call_instructions=plan.call_instructions,
            untrusted_instructions=plan.untrusted_instructions,
            run_metrics=run_metrics,
        )
    return _record_from_plan(plan, summary, int((time() - started) * 1000), model_id)


async def acomplete_pass(
    plan: PassPlan,
    *,
    config: Compaction,
    model: Optional["Model"],
    summarizer_window: Optional[int] = None,
    run_metrics: Optional["RunMetrics"] = None,
) -> CompactionRecord:
    """Async twin of complete_pass."""
    from agno.compaction._summarize import afold

    started = time()
    summary: Optional[str] = None
    model_id: Optional[str] = None
    if not plan.elision_only:
        if model is None:
            raise ValueError("Compaction fold requires a summariser model")
        model_id = model.id
        summary = await afold(
            model,
            plan.previous_summary,
            plan.rendered_segment or "",
            budget_tokens=config.summary_budget,
            summarizer_window=summarizer_window,
            config_instructions=config.instructions,
            call_instructions=plan.call_instructions,
            untrusted_instructions=plan.untrusted_instructions,
            run_metrics=run_metrics,
        )
    return _record_from_plan(plan, summary, int((time() - started) * 1000), model_id)
