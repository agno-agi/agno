from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple

from agno.compression.prompts import CONTEXT_COMPACTION_SUMMARY_PREFIX, DEFAULT_CONTEXT_COMPACTION_PROMPT
from agno.compression.state import CompactionState
from agno.metrics import RunMetrics
from agno.models.base import Model
from agno.models.message import Message
from agno.session.agent import AgentSession
from agno.utils.log import log_error, log_info
from agno.utils.message import safe_truncation_index

if TYPE_CHECKING:
    from agno.compression.manager import CompressionManager


@dataclass
class CompactionResult:
    """Result of context compaction. Side-effect-free until commit() is called."""

    view: List[Message]
    to_compact: List[Message]
    summary: Optional[str] = None

    def commit(self, session: Optional[AgentSession], stats: Optional[Dict[str, Any]] = None) -> None:
        """Mark messages as compacted and store summary. Call only after model success."""
        if not self.to_compact or not self.summary:
            return

        for msg in self.to_compact:
            msg.is_compacted = True

        if session is not None:
            prev = session.compaction
            session.compaction = CompactionState(
                summary=self.summary,
                compacted_count=(prev.compacted_count if prev else 0) + len(self.to_compact),
                total_compactions=(prev.total_compactions if prev else 0) + 1,
                updated_at=datetime.now(),
            )

        if stats is not None:
            stats["compactions"] = stats.get("compactions", 0) + 1
            stats["messages_compacted"] = stats.get("messages_compacted", 0) + len(self.to_compact)


def compress_context(
    manager: CompressionManager,
    messages: List[Message],
    session: Optional[AgentSession],
    run_metrics: Optional[RunMetrics],
) -> CompactionResult:
    """Compress context. Returns CompactionResult — call commit() after model success."""
    if manager.model is None:
        return CompactionResult(view=messages, to_compact=[])

    active = [m for m in messages if not m.is_compacted]
    stored_summary = session.compaction.summary if session and session.compaction else None

    if not _needs_compaction(manager, active):
        # Below threshold — inject stored summary if exists
        if stored_summary:
            view = _build_view_with_summary(active, stored_summary)
            return CompactionResult(view=view, to_compact=[])
        return CompactionResult(view=active, to_compact=[])

    # Partition messages
    system_msgs = [m for m in active if m.role == "system"]
    non_system = [m for m in active if m.role != "system"]
    to_compact, preserved_user, keep_verbatim = _partition_messages(
        non_system, manager.model, manager.compress_messages_limit or len(active), manager.keep_recent_messages
    )

    if not to_compact:
        if stored_summary:
            view = _build_view_with_summary(active, stored_summary)
            return CompactionResult(view=view, to_compact=[])
        return CompactionResult(view=active, to_compact=[])

    # Generate summary
    summary = _generate_summary(
        manager.model, to_compact, stored_summary, manager.compress_messages_instructions, run_metrics
    )
    if not summary:
        return CompactionResult(view=active, to_compact=[])

    # Build view
    view = system_msgs + [_make_summary_message(summary)] + preserved_user + keep_verbatim
    log_info(f"[COMPACTION] Compacted {len(to_compact)} messages into summary ({len(summary)} chars)")

    return CompactionResult(view=view, to_compact=to_compact, summary=summary)


async def acompress_context(
    manager: CompressionManager,
    messages: List[Message],
    session: Optional[AgentSession],
    run_metrics: Optional[RunMetrics],
) -> CompactionResult:
    """Async version of compress_context."""
    if manager.model is None:
        return CompactionResult(view=messages, to_compact=[])

    active = [m for m in messages if not m.is_compacted]
    stored_summary = session.compaction.summary if session and session.compaction else None

    if not await _aneeds_compaction(manager, active):
        if stored_summary:
            view = _build_view_with_summary(active, stored_summary)
            return CompactionResult(view=view, to_compact=[])
        return CompactionResult(view=active, to_compact=[])

    # Partition messages
    system_msgs = [m for m in active if m.role == "system"]
    non_system = [m for m in active if m.role != "system"]
    to_compact, preserved_user, keep_verbatim = _partition_messages(
        non_system, manager.model, manager.compress_messages_limit or len(active), manager.keep_recent_messages
    )

    if not to_compact:
        if stored_summary:
            view = _build_view_with_summary(active, stored_summary)
            return CompactionResult(view=view, to_compact=[])
        return CompactionResult(view=active, to_compact=[])

    # Generate summary
    summary = await _agenerate_summary(
        manager.model, to_compact, stored_summary, manager.compress_messages_instructions, run_metrics
    )
    if not summary:
        return CompactionResult(view=active, to_compact=[])

    # Build view
    view = system_msgs + [_make_summary_message(summary)] + preserved_user + keep_verbatim
    log_info(f"[COMPACTION] Compacted {len(to_compact)} messages into summary ({len(summary)} chars)")

    return CompactionResult(view=view, to_compact=to_compact, summary=summary)


# --- Private helpers ---


def _needs_compaction(manager: CompressionManager, active: List[Message]) -> bool:
    """Threshold check — should we compact?"""
    if manager.compress_messages_token_limit is not None and manager.model is not None:
        if manager.model.count_tokens(active) >= manager.compress_messages_token_limit:
            return True
    if manager.compress_messages_limit is not None:
        if len(active) >= manager.compress_messages_limit:
            return True
    return False


async def _aneeds_compaction(manager: CompressionManager, active: List[Message]) -> bool:
    """Async threshold check."""
    if manager.compress_messages_token_limit is not None and manager.model is not None:
        if await manager.model.acount_tokens(active) >= manager.compress_messages_token_limit:
            return True
    if manager.compress_messages_limit is not None:
        if len(active) >= manager.compress_messages_limit:
            return True
    return False


def _build_view_with_summary(active: List[Message], summary: str) -> List[Message]:
    system_msgs = [m for m in active if m.role == "system"]
    non_system = [m for m in active if m.role != "system"]
    return system_msgs + [_make_summary_message(summary)] + non_system


def _make_summary_message(summary: str) -> Message:
    return Message(
        role="user",
        content=CONTEXT_COMPACTION_SUMMARY_PREFIX + summary,
        from_history=True,
        temporary=True,
    )


def _partition_messages(
    messages: List[Message],
    model: Model,
    limit: int,
    keep_recent: int,
) -> Tuple[List[Message], List[Message], List[Message]]:
    """Split into: to_compact, preserved_user, keep_verbatim."""
    if not messages:
        return [], [], []

    # 1. Keep last N messages verbatim
    keep_count = min(keep_recent, len(messages))
    split_idx = safe_truncation_index(messages, len(messages) - keep_count)
    keep_verbatim = messages[split_idx:]
    remaining = messages[:split_idx]

    if not remaining:
        return [], [], keep_verbatim

    # 2. Preserve recent user messages up to budget (10% of limit)
    user_budget = max(1, limit // 10)
    preserved_user: List[Message] = []
    budget_used = 0
    preserved_indices = set()

    for i in range(len(remaining) - 1, -1, -1):
        msg = remaining[i]
        if msg.role == "user":
            tokens = model.count_tokens([msg])
            if budget_used + tokens <= user_budget:
                preserved_user.insert(0, msg)
                preserved_indices.add(i)
                budget_used += tokens
            else:
                break

    # 3. Everything else gets summarized
    to_compact = [m for i, m in enumerate(remaining) if i not in preserved_indices]

    return to_compact, preserved_user, keep_verbatim


def _generate_summary(
    model: Model,
    to_compact: List[Message],
    prev_summary: Optional[str],
    instructions: Optional[str],
    run_metrics: Optional[RunMetrics],
) -> Optional[str]:
    prompt = instructions or DEFAULT_CONTEXT_COMPACTION_PROMPT
    conversation = _format_messages_for_summary(to_compact, prev_summary)

    try:
        response = model.response(
            messages=[
                Message(role="system", content=prompt),
                Message(role="user", content=conversation),
            ]
        )
        if run_metrics is not None:
            from agno.metrics import ModelType, accumulate_model_metrics

            accumulate_model_metrics(response, model, ModelType.COMPRESSION_MODEL, run_metrics)
        return response.content
    except Exception as e:
        log_error(f"Context compaction failed: {e}")
        return None


async def _agenerate_summary(
    model: Model,
    to_compact: List[Message],
    prev_summary: Optional[str],
    instructions: Optional[str],
    run_metrics: Optional[RunMetrics],
) -> Optional[str]:
    prompt = instructions or DEFAULT_CONTEXT_COMPACTION_PROMPT
    conversation = _format_messages_for_summary(to_compact, prev_summary)

    try:
        response = await model.aresponse(
            messages=[
                Message(role="system", content=prompt),
                Message(role="user", content=conversation),
            ]
        )
        if run_metrics is not None:
            from agno.metrics import ModelType, accumulate_model_metrics

            accumulate_model_metrics(response, model, ModelType.COMPRESSION_MODEL, run_metrics)
        return response.content
    except Exception as e:
        log_error(f"Context compaction failed: {e}")
        return None


def _format_messages_for_summary(to_compact: List[Message], prev_summary: Optional[str]) -> str:
    parts = []
    if prev_summary:
        parts.append(f"[PREVIOUS SUMMARY]\n{prev_summary}\n\n[NEW MESSAGES]")

    for msg in to_compact:
        if msg.is_compacted:
            continue
        content = msg.compressed_content or msg.content or ""
        if isinstance(content, list):
            content = str(content)
        if msg.role == "tool":
            content = content[:500] + "..." if len(content) > 500 else content
            parts.append(f"[TOOL:{msg.tool_name}] {content}")
        else:
            parts.append(f"[{msg.role.upper()}] {content}")

    prefix = "Update the summary with new messages:\n\n" if prev_summary else "Summarize:\n\n"
    return prefix + "\n".join(parts)
