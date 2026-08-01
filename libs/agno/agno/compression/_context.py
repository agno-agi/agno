from __future__ import annotations

from typing import TYPE_CHECKING, List, Optional, Tuple

from agno.compression.prompts import CONTEXT_COMPACTION_SUMMARY_PREFIX, DEFAULT_CONTEXT_COMPACTION_PROMPT
from agno.metrics import RunMetrics
from agno.models.base import Model
from agno.models.message import Message
from agno.session.agent import AgentSession
from agno.utils.log import log_error
from agno.utils.message import safe_truncation_index

if TYPE_CHECKING:
    from agno.compression.manager import CompressionManager


def compress_messages(
    manager: CompressionManager,
    messages: List[Message],
    active: List[Message],
    session: Optional[AgentSession],
    run_metrics: Optional[RunMetrics],
) -> List[Message]:
    """Compact context. Returns filtered view for model."""
    user_budget = manager._get_user_budget(len(active))
    keep_recent_messages = manager.keep_recent_messages
    instructions = manager.compress_messages_instructions

    # Separate system messages (never compact)
    system_msgs = [m for m in active if m.role == "system"]
    non_system = [m for m in active if m.role != "system"]

    # Partition
    to_compact, preserved_user, keep_verbatim = _partition_messages(
        non_system, manager.model, user_budget, keep_recent_messages
    )

    if not to_compact:
        stored = _get_stored_summary(session)
        if stored:
            return [_build_summary_message(stored)] + active
        return active

    # Generate summary
    prev_summary = _get_stored_summary(session)
    summary = _generate_summary(manager.model, to_compact, prev_summary, instructions, run_metrics)

    if not summary:
        return active

    # Tag compacted messages
    compacted_ids = {id(m) for m in to_compact}
    for msg in messages:
        if id(msg) in compacted_ids:
            msg.is_compacted = True

    # Store summary
    _store_summary(session, summary, len(to_compact))

    # Build view
    view = system_msgs + [_build_summary_message(summary)] + preserved_user + keep_verbatim

    _track_stat(manager.stats, "compactions", 1)
    _track_stat(manager.stats, "messages_compacted", len(to_compact))

    return view


async def acompress_messages(
    manager: CompressionManager,
    messages: List[Message],
    active: List[Message],
    session: Optional[AgentSession],
    run_metrics: Optional[RunMetrics],
) -> List[Message]:
    """Async version of compress_messages."""
    user_budget = manager._get_user_budget(len(active))
    keep_recent_messages = manager.keep_recent_messages
    instructions = manager.compress_messages_instructions

    system_msgs = [m for m in active if m.role == "system"]
    non_system = [m for m in active if m.role != "system"]

    to_compact, preserved_user, keep_verbatim = _partition_messages(
        non_system, manager.model, user_budget, keep_recent_messages
    )

    if not to_compact:
        stored = _get_stored_summary(session)
        if stored:
            return [_build_summary_message(stored)] + active
        return active

    prev_summary = _get_stored_summary(session)
    summary = await _agenerate_summary(manager.model, to_compact, prev_summary, instructions, run_metrics)

    if not summary:
        return active

    compacted_ids = {id(m) for m in to_compact}
    for msg in messages:
        if id(msg) in compacted_ids:
            msg.is_compacted = True

    _store_summary(session, summary, len(to_compact))

    view = system_msgs + [_build_summary_message(summary)] + preserved_user + keep_verbatim

    _track_stat(manager.stats, "compactions", 1)
    _track_stat(manager.stats, "messages_compacted", len(to_compact))

    return view


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
