from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple

from agno.compression.prompts import CONTEXT_COMPACTION_SUMMARY_PREFIX, DEFAULT_CONTEXT_COMPACTION_PROMPT
from agno.metrics import RunMetrics
from agno.models.base import Model
from agno.models.message import Message
from agno.session.agent import AgentSession
from agno.utils.log import log_debug, log_error, log_info
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
            log_debug("CompactionResult.commit(): nothing to commit")
            return

        log_info(f"[COMPACTION] COMMIT: marking {len(self.to_compact)} messages as compacted")
        for msg in self.to_compact:
            msg.is_compacted = True
            log_debug(f"[COMPACTION]   marked: {msg.role} | {str(msg.content)[:50]}...")

        _store_summary(session, self.summary, len(self.to_compact))
        log_info(f"[COMPACTION] STORED SUMMARY ({len(self.summary)} chars): {self.summary[:100]}...")

        if stats is not None:
            _track_stat(stats, "compactions", 1)
            _track_stat(stats, "messages_compacted", len(self.to_compact))


def compress_messages(
    manager: CompressionManager,
    messages: List[Message],
    active: List[Message],
    session: Optional[AgentSession],
    run_metrics: Optional[RunMetrics],
) -> CompactionResult:
    """Compact context. Returns CompactionResult — call commit() after model success."""
    log_info(f"[COMPACTION] compress_messages: {len(messages)} total, {len(active)} active")

    # Model required for compaction
    if manager.model is None:
        log_debug("[COMPACTION] no model configured, skipping compaction")
        return CompactionResult(view=active, to_compact=[])

    user_budget = manager._get_user_budget(len(active))
    keep_recent_messages = manager.keep_recent_messages
    instructions = manager.compress_messages_instructions

    # Separate system messages (never compact)
    system_msgs = [m for m in active if m.role == "system"]
    non_system = [m for m in active if m.role != "system"]
    log_debug(f"[COMPACTION]   system_msgs={len(system_msgs)}, non_system={len(non_system)}")

    # Partition
    to_compact, preserved_user, keep_verbatim = _partition_messages(
        non_system, manager.model, user_budget, keep_recent_messages
    )
    log_info(
        f"[COMPACTION] PARTITION: to_compact={len(to_compact)}, preserved_user={len(preserved_user)}, keep_verbatim={len(keep_verbatim)}"
    )

    # Log what we're compacting
    for i, msg in enumerate(to_compact):
        log_debug(f"[COMPACTION]   to_compact[{i}]: {msg.role} | {str(msg.content)[:60]}...")
    for i, msg in enumerate(keep_verbatim):
        log_debug(f"[COMPACTION]   keep_verbatim[{i}]: {msg.role} | {str(msg.content)[:60]}...")

    if not to_compact:
        # No compaction needed — inject stored summary if exists
        stored = _get_stored_summary(session)
        if stored:
            log_debug(f"[COMPACTION] no compaction needed, injecting stored summary ({len(stored)} chars)")
            view = system_msgs + [_build_summary_message(stored)] + [m for m in active if m.role != "system"]
            return CompactionResult(view=view, to_compact=[])
        log_debug("[COMPACTION] no compaction needed, no stored summary")
        return CompactionResult(view=active, to_compact=[])

    # Generate summary
    prev_summary = _get_stored_summary(session)
    if prev_summary:
        log_debug(f"[COMPACTION] Previous summary exists ({len(prev_summary)} chars)")

    log_info(f"[COMPACTION] Generating summary from {len(to_compact)} messages...")
    summary = _generate_summary(manager.model, to_compact, prev_summary, instructions, run_metrics)

    if not summary:
        log_error("[COMPACTION] Summary generation FAILED, returning original messages")
        return CompactionResult(view=active, to_compact=[])

    log_info(f"[COMPACTION] GENERATED SUMMARY ({len(summary)} chars): {summary[:150]}...")

    # Build view (summary injected)
    view = system_msgs + [_build_summary_message(summary)] + preserved_user + keep_verbatim

    log_info(
        f"[COMPACTION] VIEW for model: {len(view)} messages (system={len(system_msgs)}, summary=1, preserved={len(preserved_user)}, verbatim={len(keep_verbatim)})"
    )
    for i, msg in enumerate(view):
        content_preview = str(msg.content)[:80].replace("\n", " ") if msg.content else "(empty)"
        log_debug(f"[COMPACTION]   view[{i}]: {msg.role} | {content_preview}...")

    # Return result — caller calls commit() after model success
    return CompactionResult(view=view, to_compact=to_compact, summary=summary)


async def acompress_messages(
    manager: CompressionManager,
    messages: List[Message],
    active: List[Message],
    session: Optional[AgentSession],
    run_metrics: Optional[RunMetrics],
) -> CompactionResult:
    """Async version of compress_messages. Returns CompactionResult — call commit() after model success."""

    # Model required for compaction
    if manager.model is None:
        log_debug("[COMPACTION] no model configured, skipping compaction")
        return CompactionResult(view=active, to_compact=[])

    user_budget = manager._get_user_budget(len(active))
    keep_recent_messages = manager.keep_recent_messages
    instructions = manager.compress_messages_instructions

    system_msgs = [m for m in active if m.role == "system"]
    non_system = [m for m in active if m.role != "system"]

    to_compact, preserved_user, keep_verbatim = _partition_messages(
        non_system, manager.model, user_budget, keep_recent_messages
    )

    if not to_compact:
        # No compaction needed — inject stored summary if exists
        stored = _get_stored_summary(session)
        if stored:
            view = system_msgs + [_build_summary_message(stored)] + [m for m in active if m.role != "system"]
            return CompactionResult(view=view, to_compact=[])
        return CompactionResult(view=active, to_compact=[])

    prev_summary = _get_stored_summary(session)
    summary = await _agenerate_summary(manager.model, to_compact, prev_summary, instructions, run_metrics)

    if not summary:
        # Summary generation failed — return original
        return CompactionResult(view=active, to_compact=[])

    # Build view (summary injected)
    view = system_msgs + [_build_summary_message(summary)] + preserved_user + keep_verbatim

    # Return result — caller calls commit() after model success
    return CompactionResult(view=view, to_compact=to_compact, summary=summary)


def _partition_messages(
    messages: List[Message],
    model: Model,
    user_budget: int,
    keep_recent_messages: int,
) -> Tuple[List[Message], List[Message], List[Message]]:
    """Split messages into: to_compact, preserved_user, keep_verbatim."""
    if not messages:
        return [], [], []

    # 1. Keep last N messages verbatim (respects tool-call pairs)
    keep_count = min(keep_recent_messages, len(messages))
    split_idx = safe_truncation_index(messages, len(messages) - keep_count)
    keep_verbatim = messages[split_idx:]
    remaining = messages[:split_idx]

    if not remaining:
        return [], [], keep_verbatim

    # 2. Preserve user messages newest-first up to budget
    preserved_user: List[Message] = []
    budget_used = 0

    user_msgs_with_idx = [(i, m) for i, m in enumerate(remaining) if m.role == "user"]
    user_msgs_with_idx.reverse()

    preserved_indices = set()
    for idx, msg in user_msgs_with_idx:
        msg_tokens = model.count_tokens([msg])
        if budget_used + msg_tokens <= user_budget:
            preserved_user.insert(0, msg)
            preserved_indices.add(idx)
            budget_used += msg_tokens
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
    """Generate summary from messages."""
    conversation_text = _build_conversation_text(to_compact, prev_summary)
    prompt = instructions or DEFAULT_CONTEXT_COMPACTION_PROMPT

    if prev_summary:
        user_content = (
            "Update and combine the previous summary with the new messages. "
            f"Produce one unified summary:\n\n{conversation_text}"
        )
    else:
        user_content = f"Summarize this conversation:\n\n{conversation_text}"

    try:
        response = model.response(
            messages=[
                Message(role="system", content=prompt),
                Message(role="user", content=user_content),
            ]
        )
        if run_metrics is not None:
            from agno.metrics import ModelType, accumulate_model_metrics

            accumulate_model_metrics(response, model, ModelType.COMPRESSION_MODEL, run_metrics)
        return response.content
    except Exception as e:
        log_error(f"Context compaction LLM call failed: {e}")
        return None


async def _agenerate_summary(
    model: Model,
    to_compact: List[Message],
    prev_summary: Optional[str],
    instructions: Optional[str],
    run_metrics: Optional[RunMetrics],
) -> Optional[str]:
    """Async version of _generate_summary."""
    conversation_text = _build_conversation_text(to_compact, prev_summary)
    prompt = instructions or DEFAULT_CONTEXT_COMPACTION_PROMPT

    if prev_summary:
        user_content = (
            "Update and combine the previous summary with the new messages. "
            f"Produce one unified summary:\n\n{conversation_text}"
        )
    else:
        user_content = f"Summarize this conversation:\n\n{conversation_text}"

    try:
        response = await model.aresponse(
            messages=[
                Message(role="system", content=prompt),
                Message(role="user", content=user_content),
            ]
        )
        if run_metrics is not None:
            from agno.metrics import ModelType, accumulate_model_metrics

            accumulate_model_metrics(response, model, ModelType.COMPRESSION_MODEL, run_metrics)
        return response.content
    except Exception as e:
        log_error(f"Context compaction LLM call failed: {e}")
        return None


def _build_conversation_text(to_compact: List[Message], prev_summary: Optional[str]) -> str:
    """Build conversation text for summarization."""
    parts = []
    if prev_summary:
        parts.append(f"[PREVIOUS SUMMARY]\n{prev_summary}\n")
        parts.append("[NEW MESSAGES TO INCORPORATE]")

    for msg in to_compact:
        if msg.is_compacted:
            continue
        role = msg.role.upper()
        content = msg.compressed_content or msg.content or ""
        if isinstance(content, list):
            content = str(content)
        if msg.role == "tool":
            content_preview = content[:500] + "..." if len(content) > 500 else content
            parts.append(f"[TOOL:{msg.tool_name}] {content_preview}")
        else:
            parts.append(f"[{role}] {content}")

    return "\n".join(parts)


def _get_stored_summary(session: Optional[AgentSession]) -> Optional[str]:
    """Get stored compaction summary from session."""
    if session is None or session.session_data is None:
        return None
    state = session.session_data.get("compaction_state")
    if state and isinstance(state, dict):
        return state.get("summary")
    return None


def _store_summary(session: Optional[AgentSession], summary: str, compacted_count: int) -> None:
    """Store compaction summary in session."""
    if session is None:
        return
    if session.session_data is None:
        session.session_data = {}

    prev_state = session.session_data.get("compaction_state", {})
    session.session_data["compaction_state"] = {
        "summary": summary,
        "compacted_count": prev_state.get("compacted_count", 0) + compacted_count,
        "total_compactions": prev_state.get("total_compactions", 0) + 1,
    }


def _build_summary_message(summary: str) -> Message:
    """Build a summary message to inject into context."""
    return Message(
        role="user",
        content=CONTEXT_COMPACTION_SUMMARY_PREFIX + summary,
        from_history=True,
        temporary=True,
    )


def _track_stat(stats: dict, key: str, value: int) -> None:
    stats[key] = stats.get(key, 0) + value
