"""Internal context compaction functions."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from textwrap import dedent
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Set, Tuple, Union

from agno.compression._tool import acompact_tools, compact_tools
from agno.models.base import Model
from agno.models.message import Message
from agno.utils.log import log_debug, log_error, log_info
from agno.utils.message import safe_truncation_index

if TYPE_CHECKING:
    from agno.metrics import RunMetrics
    from agno.run.agent import RunOutput
    from agno.run.team import TeamRunOutput

from agno.metrics import ModelType, accumulate_model_metrics

DEFAULT_COMPACTION_PROMPT = dedent("""\
    You are creating a context checkpoint for an AI agent to continue work seamlessly.

    OUTPUT STRUCTURE (use these exact headings):

    ## Active Task
    Copy the user's most recent request or goal verbatim.

    ## Completed Actions
    Format each as: N. ACTION target - outcome [tool: name]
    Example: "1. READ agent.py - Agent dataclass, 40+ config fields, delegates to _run.py [read_file]"

    ## Key Findings
    - Concrete facts: file paths, function names, class structures, values discovered
    - Decisions made and their rationale
    - User preferences or corrections stated
    - Architecture/patterns identified

    ## Pending / Blocked
    - Unresolved tasks or next steps
    - Exact error messages if any (quote verbatim)

    ## Critical Context
    - Identifiers: IDs, versions, timestamps, URLs
    - Constraints or requirements mentioned
    - Configuration values (no secrets)

    RULES:
    - No narrative preamble ("The conversation covered...", "We discussed...")
    - Preserve exact identifiers, paths, numbers, error strings
    - Use terse bullets, verbs first
    - Maximum 2000 tokens
    """)


SUMMARY_PREFIX = dedent("""\
    Another language model started this conversation and produced a summary of the work so far. \
    Use this to continue without duplicating work:

    """)


def create_summary_message(summary: str) -> Message:
    """Create a summary message from a summary string."""
    return Message(
        role="user",
        content=SUMMARY_PREFIX + summary,
        from_history=True,
    )


@dataclass
class CompactionState:
    """Tracks context compaction state for a run."""

    summary: str = ""
    compacted_message_ids: Set[str] = field(default_factory=set)
    compacted_count: int = 0
    total_compactions: int = 0
    total_tokens_saved: int = 0
    updated_at: Optional[datetime] = None

    def get_summary_message(self) -> Message:
        return Message(
            role="user",
            content=SUMMARY_PREFIX + self.summary,
            from_history=True,
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "summary": self.summary,
            "compacted_message_ids": list(self.compacted_message_ids),
            "compacted_count": self.compacted_count,
            "total_compactions": self.total_compactions,
            "total_tokens_saved": self.total_tokens_saved,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CompactionState":
        updated_at = data.get("updated_at")
        if updated_at and isinstance(updated_at, str):
            updated_at = datetime.fromisoformat(updated_at)
        return cls(
            summary=data.get("summary", ""),
            compacted_message_ids=set(data.get("compacted_message_ids", [])),
            compacted_count=data.get("compacted_count", 0),
            total_compactions=data.get("total_compactions", 0),
            total_tokens_saved=data.get("total_tokens_saved", 0),
            updated_at=updated_at,
        )


@dataclass
class CompactionResult:
    """Result of a compaction operation."""

    compacted_messages: List[Message]
    summary: Optional[str] = None
    stats: Dict[str, Any] = field(default_factory=dict)


# --- Pure functions ---


def should_compact_context(
    messages: List[Message],
    model: Optional[Model],
    message_limit: Optional[int],
    token_limit: Optional[int],
) -> bool:
    """Check if messages exceed compaction threshold."""
    if token_limit is not None and model is not None:
        token_count = model.count_tokens(messages)
        if token_count >= token_limit:
            return True

    if message_limit is not None and len(messages) >= message_limit:
        return True

    return False


async def ashould_compact_context(
    messages: List[Message],
    model: Optional[Model],
    message_limit: Optional[int],
    token_limit: Optional[int],
) -> bool:
    """Async check if messages exceed compaction threshold."""
    if token_limit is not None and model is not None:
        token_count = await model.acount_tokens(messages)
        if token_count >= token_limit:
            return True

    if message_limit is not None and len(messages) >= message_limit:
        return True

    return False


def compact_context(
    messages: List[Message],
    model: Optional[Model],
    keep_recent: int = 10,
    preserve_user_budget: int = 20_000,
    token_limit: Optional[int] = None,
    instructions: Optional[str] = None,
    run_response: Optional[Union["RunOutput", "TeamRunOutput"]] = None,
    run_metrics: Optional["RunMetrics"] = None,
) -> CompactionResult:
    """Compact messages by summarizing old ones."""
    log_debug(f"[COMPACTION] compact_context() with {len(messages)} messages")

    if model is None:
        return CompactionResult(compacted_messages=messages)

    # Split messages
    system_msgs = [m for m in messages if m.role == "system"]
    non_system = [m for m in messages if m.role != "system"]
    old_messages, preserved_user, recent_messages = _split_messages(
        non_system, model, keep_recent, preserve_user_budget
    )

    if not old_messages:
        return CompactionResult(compacted_messages=messages)

    # Get existing summary if any
    existing_summary = run_response.compaction_state.summary if run_response and run_response.compaction_state else None

    # Summarize
    new_summary = _summarize(old_messages, existing_summary, model, instructions, run_metrics)
    if not new_summary:
        return CompactionResult(compacted_messages=messages)

    # Build compacted messages
    summary_msg = Message(role="user", content=SUMMARY_PREFIX + new_summary, from_history=True)
    compacted_messages = system_msgs + [summary_msg] + preserved_user + recent_messages

    # Log metrics
    tokens_before = model.count_tokens(messages)
    tokens_after = model.count_tokens(compacted_messages)
    tokens_saved = tokens_before - tokens_after
    ratio = tokens_after / tokens_before if tokens_before > 0 else 1.0
    summary_tokens = model.count_tokens([summary_msg])

    log_info(
        f"[COMPACTION] {len(messages)} -> {len(compacted_messages)} msgs | "
        f"{tokens_before} -> {tokens_after} tokens | ratio={ratio:.2f} | "
        f"saved={tokens_saved} | summary={summary_tokens} tok"
    )

    # Compress tool results if still over limit
    if token_limit and model.count_tokens(compacted_messages) > token_limit:
        compact_tools(recent_messages, model=model, run_metrics=run_metrics)
        compacted_messages = system_msgs + [summary_msg] + preserved_user + recent_messages
        log_info(f"[COMPACTION] Compressed tool results, now {model.count_tokens(compacted_messages)} tokens")

    # Update state
    _update_compaction_state(run_response, old_messages, new_summary, tokens_saved)

    return CompactionResult(compacted_messages=compacted_messages, summary=new_summary)


async def acompact_context(
    messages: List[Message],
    model: Optional[Model],
    keep_recent: int = 10,
    preserve_user_budget: int = 20_000,
    token_limit: Optional[int] = None,
    instructions: Optional[str] = None,
    run_response: Optional[Union["RunOutput", "TeamRunOutput"]] = None,
    run_metrics: Optional["RunMetrics"] = None,
) -> CompactionResult:
    """Async compact messages by summarizing old ones."""
    log_debug(f"[COMPACTION] acompact_context() with {len(messages)} messages")

    if model is None:
        return CompactionResult(compacted_messages=messages)

    # Split messages
    system_msgs = [m for m in messages if m.role == "system"]
    non_system = [m for m in messages if m.role != "system"]
    old_messages, preserved_user, recent_messages = _split_messages(
        non_system, model, keep_recent, preserve_user_budget
    )

    if not old_messages:
        return CompactionResult(compacted_messages=messages)

    # Get existing summary if any
    existing_summary = run_response.compaction_state.summary if run_response and run_response.compaction_state else None

    # Summarize
    new_summary = await _asummarize(old_messages, existing_summary, model, instructions, run_metrics)
    if not new_summary:
        return CompactionResult(compacted_messages=messages)

    # Build compacted messages
    summary_msg = Message(role="user", content=SUMMARY_PREFIX + new_summary, from_history=True)
    compacted_messages = system_msgs + [summary_msg] + preserved_user + recent_messages

    # Log metrics
    tokens_before = await model.acount_tokens(messages)
    tokens_after = await model.acount_tokens(compacted_messages)
    tokens_saved = tokens_before - tokens_after
    ratio = tokens_after / tokens_before if tokens_before > 0 else 1.0
    summary_tokens = await model.acount_tokens([summary_msg])

    log_info(
        f"[COMPACTION] {len(messages)} -> {len(compacted_messages)} msgs | "
        f"{tokens_before} -> {tokens_after} tokens | ratio={ratio:.2f} | "
        f"saved={tokens_saved} | summary={summary_tokens} tok"
    )

    # Compress tool results if still over limit
    if token_limit and await model.acount_tokens(compacted_messages) > token_limit:
        await acompact_tools(recent_messages, model=model, run_metrics=run_metrics)
        compacted_messages = system_msgs + [summary_msg] + preserved_user + recent_messages
        log_info(f"[COMPACTION] Compressed tool results, now {await model.acount_tokens(compacted_messages)} tokens")

    # Update state
    _update_compaction_state(run_response, old_messages, new_summary, tokens_saved)

    return CompactionResult(compacted_messages=compacted_messages, summary=new_summary)


# --- Internal helpers ---


def _split_messages(
    messages: List[Message],
    model: Optional[Model],
    keep_recent: int,
    preserve_user_budget: int,
) -> Tuple[List[Message], List[Message], List[Message]]:
    """Split messages into: old (to summarize), preserved_user, recent."""
    if not messages:
        return [], [], []

    keep_count = min(keep_recent, len(messages))
    split_idx = safe_truncation_index(messages, len(messages) - keep_count)
    recent_messages = messages[split_idx:]
    older = messages[:split_idx]

    if not older:
        return [], [], recent_messages

    preserved_user, preserved_indices = _extract_user_messages(older, model, preserve_user_budget)
    old_messages = [m for i, m in enumerate(older) if i not in preserved_indices]

    return old_messages, preserved_user, recent_messages


def _extract_user_messages(
    messages: List[Message],
    model: Optional[Model],
    budget: int,
) -> Tuple[List[Message], Set[int]]:
    """Extract recent user messages up to token budget."""
    preserved: List[Message] = []
    indices: Set[int] = set()
    used = 0

    for i in range(len(messages) - 1, -1, -1):
        msg = messages[i]
        if msg.role == "user" and not msg.from_history:
            tokens = model.count_tokens([msg]) if model else 0
            if used + tokens <= budget:
                preserved.insert(0, msg)
                indices.add(i)
                used += tokens
            else:
                break

    return preserved, indices


def _build_summarization_prompt(
    old_messages: List[Message],
    existing_summary: Optional[str],
    instructions: Optional[str],
) -> List[Message]:
    """Build prompt for summarization."""
    system_prompt = instructions or DEFAULT_COMPACTION_PROMPT
    prompt: List[Message] = [Message(role="system", content=system_prompt)]

    if existing_summary:
        prompt.append(Message(role="user", content=f"Previous summary to update:\n{existing_summary}"))

    prompt.extend(old_messages)
    prompt.append(Message(role="user", content="Now provide a concise summary of the conversation above."))
    return prompt


def _summarize(
    old_messages: List[Message],
    existing_summary: Optional[str],
    model: Model,
    instructions: Optional[str],
    run_metrics: Optional["RunMetrics"],
) -> Optional[str]:
    """Generate summary via LLM."""
    prompt = _build_summarization_prompt(old_messages, existing_summary, instructions)
    try:
        response = model.response(messages=prompt)
        if run_metrics is not None:
            accumulate_model_metrics(response, model, ModelType.COMPRESSION_MODEL, run_metrics)
        return response.content
    except Exception as e:
        log_error(f"Compaction LLM call failed: {e}")
        return None


async def _asummarize(
    old_messages: List[Message],
    existing_summary: Optional[str],
    model: Model,
    instructions: Optional[str],
    run_metrics: Optional["RunMetrics"],
) -> Optional[str]:
    """Async generate summary via LLM."""
    prompt = _build_summarization_prompt(old_messages, existing_summary, instructions)
    try:
        response = await model.aresponse(messages=prompt)
        if run_metrics is not None:
            accumulate_model_metrics(response, model, ModelType.COMPRESSION_MODEL, run_metrics)
        return response.content
    except Exception as e:
        log_error(f"Compaction LLM call failed: {e}")
        return None


def _update_compaction_state(
    run_response: Optional[Union["RunOutput", "TeamRunOutput"]],
    old_messages: List[Message],
    new_summary: str,
    tokens_saved: int = 0,
) -> None:
    """Update run_response.compaction_state."""
    if run_response is None:
        return

    prev = run_response.compaction_state
    new_ids = {msg.id for msg in old_messages if msg.id}
    all_ids = new_ids.union(prev.compacted_message_ids if prev else set())

    run_response.compaction_state = CompactionState(
        summary=new_summary,
        compacted_message_ids=all_ids,
        compacted_count=(prev.compacted_count if prev else 0) + len(old_messages),
        total_compactions=(prev.total_compactions if prev else 0) + 1,
        total_tokens_saved=(prev.total_tokens_saved if prev else 0) + tokens_saved,
        updated_at=datetime.now(),
    )
