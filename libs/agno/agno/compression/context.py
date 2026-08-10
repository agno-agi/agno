from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from textwrap import dedent
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Set, Tuple

from agno.models.base import Model
from agno.models.message import Message
from agno.models.utils import get_model
from agno.utils.log import log_debug, log_error, log_info
from agno.utils.message import safe_truncation_index

if TYPE_CHECKING:
    from agno.metrics import RunMetrics
    from agno.run.agent import RunOutput

from agno.metrics import ModelType, accumulate_model_metrics

DEFAULT_COMPACTION_PROMPT = dedent("""\
    You are summarizing a conversation history to preserve context while reducing token usage.

    ALWAYS PRESERVE:
    - User's original goals and requests
    - Key decisions made and their rationale
    - Important facts, numbers, dates, identifiers discovered
    - Unresolved tasks or pending actions
    - User preferences and corrections stated
    - Critical constraints or requirements mentioned

    SUMMARIZE:
    - Tool call sequences -> outcomes only ("searched X, found Y")
    - Back-and-forth clarifications -> final understanding
    - Exploratory discussions -> conclusions reached

    FORMAT:
    Write a dense, factual summary. Use bullet points for distinct items.
    Do not include meta-commentary like "The conversation covered..." - just state the facts.

    Keep the summary under 2000 tokens while preserving all critical context.
    """)


def create_summary_message(summary: str) -> "Message":
    """Create a summary message from a summary string.

    Used when we only have the summary text (e.g., from run.compaction_summary)
    rather than a full CompactionState object.
    """
    from agno.models.message import Message

    return Message(
        role="user",
        content=SUMMARY_PREFIX + summary,
        from_history=True,
    )


SUMMARY_PREFIX = dedent("""\
    Another language model started this conversation and produced a summary of the work so far. \
    Use this to continue without duplicating work:

    """)


@dataclass
class CompactionState:
    """Tracks context compaction state for a run."""

    summary: str = ""  # cumulative summary of compacted messages
    compacted_message_ids: Set[str] = field(default_factory=set)  # filtered when building model context
    compacted_count: int = 0
    total_compactions: int = 0
    total_tokens_saved: int = 0
    updated_at: Optional[datetime] = None

    def get_summary_message(self) -> Message:
        """Create the summary message to inject into conversation."""
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


@dataclass
class ContextCompactionManager:
    """Compacts conversation history to fit within context limits."""

    model: Optional[Model] = None  # model used for summarization
    message_limit: Optional[int] = None  # trigger compaction at N messages
    token_limit: Optional[int] = None  # trigger compaction at N tokens
    keep_recent: int = 10  # messages to keep intact (not summarized)
    preserve_user_budget: int = 20_000  # token budget for preserving user messages from older section
    instructions: Optional[str] = None  # custom summarization prompt
    stats: Dict[str, Any] = field(default_factory=dict)  # runtime stats for display

    def __post_init__(self) -> None:
        if self.model is not None:
            self.model = get_model(self.model)
        # Default to message-based limit if neither specified
        if self.message_limit is None and self.token_limit is None:
            self.message_limit = 50

    def should_compact(self, messages: List[Message]) -> bool:
        """Check if messages exceed compaction threshold."""
        log_debug(
            f"[COMPACTION] should_compact check: {len(messages)} messages, limit={self.message_limit}, token_limit={self.token_limit}"
        )
        if self.token_limit is not None and self.model is not None:
            token_count = self.model.count_tokens(messages)
            log_debug(f"[COMPACTION] Token count: {token_count}, limit: {self.token_limit}")
            if token_count >= self.token_limit:
                log_debug("[COMPACTION] Threshold exceeded (tokens)")
                return True
        if self.message_limit is not None:
            if len(messages) >= self.message_limit:
                log_debug(f"[COMPACTION] Threshold exceeded (messages): {len(messages)} >= {self.message_limit}")
                return True
        log_debug("[COMPACTION] No compaction needed")
        return False

    def compact(
        self,
        messages: List[Message],
        run_response: Optional["RunOutput"] = None,
        run_metrics: Optional["RunMetrics"] = None,
    ) -> CompactionResult:
        """Compact messages if threshold exceeded.

        Returns:
            CompactionResult with compacted_messages and summary (if compaction occurred).
        """
        log_debug(f"[COMPACTION] compact() called with {len(messages)} messages")
        log_debug(f"[COMPACTION] Message roles: {[m.role for m in messages]}")

        # 1. Check if compaction needed
        if self.model is None:
            log_debug("[COMPACTION] No model configured, skipping compaction")
            return CompactionResult(compacted_messages=messages)
        if not self.should_compact(messages):
            log_debug("[COMPACTION] Below threshold, returning original messages")
            return CompactionResult(compacted_messages=messages)

        # 2. Split messages into groups
        log_debug("[COMPACTION] Splitting messages...")
        system_msgs = [m for m in messages if m.role == "system"]
        non_system = [m for m in messages if m.role != "system"]
        old_messages, preserved_user, recent_messages = self._split_messages(non_system)

        log_debug(
            f"[COMPACTION] Split result: system={len(system_msgs)}, old={len(old_messages)}, preserved_user={len(preserved_user)}, recent={len(recent_messages)}"
        )

        if not old_messages:
            log_debug("[COMPACTION] No old messages to compact")
            return CompactionResult(compacted_messages=messages)

        # 3. Summarize old messages (merges with existing summary if available)
        existing_summary = run_response.compaction_state.summary if run_response and run_response.compaction_state else None
        log_debug(f"[COMPACTION] Existing summary ({len(existing_summary) if existing_summary else 0} chars)")
        if existing_summary:
            log_debug(
                f"[COMPACTION] --- EXISTING SUMMARY START ---\n{existing_summary}\n[COMPACTION] --- EXISTING SUMMARY END ---"
            )
        log_debug(f"[COMPACTION] Summarizing {len(old_messages)} old messages...")
        new_summary = self._summarize(old_messages, existing_summary, run_metrics)

        if not new_summary:
            log_debug("[COMPACTION] Summarization failed, returning original messages")
            return CompactionResult(compacted_messages=messages)

        log_debug(f"[COMPACTION] New summary ({len(new_summary)} chars)")
        log_debug(f"[COMPACTION] --- NEW SUMMARY START ---\n{new_summary}\n[COMPACTION] --- NEW SUMMARY END ---")

        # 4. Build compacted compacted_messages: system + new summary + preserved user + recent
        summary_msg = Message(role="user", content=SUMMARY_PREFIX + new_summary, from_history=True)
        compacted_messages = system_msgs + [summary_msg] + preserved_user + recent_messages

        # Calculate token metrics
        tokens_before = self.model.count_tokens(messages) if self.model else 0
        tokens_after = self.model.count_tokens(compacted_messages) if self.model else 0
        tokens_saved = tokens_before - tokens_after
        ratio = tokens_after / tokens_before if tokens_before > 0 else 1.0
        summary_tokens = self.model.count_tokens([summary_msg]) if self.model else 0

        log_info(
            f"[COMPACTION] {len(messages)} -> {len(compacted_messages)} msgs | {tokens_before} -> {tokens_after} tokens | ratio={ratio:.2f} | saved={tokens_saved} | summary={summary_tokens} tok"
        )

        # 5. Compress large tool results if still over token limit
        if self.token_limit and self.model.count_tokens(compacted_messages) > self.token_limit:
            self._compress_tool_results(recent_messages, run_metrics)
            compacted_messages = system_msgs + [summary_msg] + preserved_user + recent_messages
            log_info(f"[COMPACTION] Compressed tool results, now {self.model.count_tokens(compacted_messages)} tokens")

        # 6. Update run compaction state
        log_debug("[COMPACTION] Updating run compaction state (sync)...")
        self._update_compaction_state(run_response, old_messages, new_summary, tokens_saved)
        if run_response and run_response.compaction_state:
            log_debug(
                f"[COMPACTION] run_response.compaction_state updated: total={run_response.compaction_state.total_compactions}, ids={len(run_response.compaction_state.compacted_message_ids)}"
            )

        # Update stats for display
        self.stats["messages_compacted"] = self.stats.get("messages_compacted", 0) + len(old_messages)
        self.stats["tokens_saved"] = self.stats.get("tokens_saved", 0) + tokens_saved

        log_debug(f"[COMPACTION] Returning {len(compacted_messages)} compacted messages (sync)")
        return CompactionResult(compacted_messages=compacted_messages, summary=new_summary)

    def _split_messages(self, messages: List[Message]) -> Tuple[List[Message], List[Message], List[Message]]:
        """Split messages into: old_messages (to summarize), preserved_user, recent_messages."""
        if not messages:
            return [], [], []

        # 1. Compute split point: keep last N messages as "recent" (sent to model as-is)
        # 2. Snap DOWN to avoid breaking tool-call pairs (assistant + tool result must stay together)
        keep_count = min(self.keep_recent, len(messages))
        split_idx = safe_truncation_index(messages, len(messages) - keep_count)
        recent_messages = messages[split_idx:]  # kept intact
        older = messages[:split_idx]  # candidates for summarization

        if not older:
            return [], [], recent_messages

        # Extract recent user messages from older portion (preserve intent)
        preserved_user, preserved_indices = self._extract_user_messages(older)
        old_messages = [m for i, m in enumerate(older) if i not in preserved_indices]

        return old_messages, preserved_user, recent_messages

    def _extract_user_messages(self, messages: List[Message]) -> Tuple[List[Message], Set[int]]:
        """Extract recent user messages up to token budget.

        Preserves user intent by keeping recent user messages verbatim (not summarized).
        When budget exceeded, oldest user messages get summarized instead.
        """
        preserved: List[Message] = []
        indices: Set[int] = set()
        used = 0

        # Walk backward (newest first), keep user messages until budget exhausted
        for i in range(len(messages) - 1, -1, -1):
            msg = messages[i]
            # Skip summary messages (from_history=True) — they get replaced, not preserved
            if msg.role == "user" and not msg.from_history:
                tokens = self.model.count_tokens([msg])
                if used + tokens <= self.preserve_user_budget:
                    preserved.insert(0, msg)
                    indices.add(i)
                    used += tokens
                else:
                    break

        return preserved, indices

    def _build_summarization_prompt(
        self, old_messages: List[Message], existing_summary: Optional[str]
    ) -> List[Message]:
        """Build the prompt messages for the summarization LLM call.

        Structure: [system] + [existing summary if any] + [old messages] + [instruction]

        When existing_summary is provided (incremental compaction), the LLM merges
        the previous summary with new messages rather than starting fresh.
        """
        # 1. System prompt with summarization instructions
        system_prompt = self.instructions or DEFAULT_COMPACTION_PROMPT
        prompt: List[Message] = [Message(role="system", content=system_prompt)]

        # 2. Include previous summary for incremental compaction
        if existing_summary:
            prompt.append(Message(role="user", content=f"Previous summary to update:\n{existing_summary}"))

        # 3. Messages to summarize
        prompt.extend(old_messages)

        # 4. Final instruction to trigger summary generation
        prompt.append(Message(role="user", content="Now provide a concise summary of the conversation above."))
        return prompt

    def _summarize(
        self,
        old_messages: List[Message],
        existing_summary: Optional[str],
        run_metrics: Optional["RunMetrics"],
    ) -> Optional[str]:
        """Generate summary of old messages via LLM."""
        if self.model is None:
            return None

        prompt = self._build_summarization_prompt(old_messages, existing_summary)
        try:
            response = self.model.response(messages=prompt)
            if run_metrics is not None:
                accumulate_model_metrics(response, self.model, ModelType.COMPRESSION_MODEL, run_metrics)
            return response.content
        except Exception as e:
            log_error(f"Compaction LLM call failed: {e}")
            return None

    def _compress_tool_results(self, messages: List[Message], run_metrics: Optional["RunMetrics"]) -> None:
        """Compress large tool results using CompressionManager."""
        from agno.compression.manager import CompressionManager

        cm = CompressionManager(model=self.model)
        cm.compress(messages, run_metrics)

    def _update_compaction_state(
        self,
        run_response: Optional["RunOutput"],
        old_messages: List[Message],
        new_summary: str,
        tokens_saved: int = 0,
    ) -> None:
        """Update run_response.compaction_state with new state."""
        if run_response is None:
            return

        prev = run_response.compaction_state

        # Collect IDs of compacted messages (so they get filtered when loading history)
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

    async def ashould_compact(self, messages: List[Message]) -> bool:
        """Async version of should_compact()."""
        if self.token_limit is not None and self.model is not None:
            token_count = await self.model.acount_tokens(messages)
            if token_count >= self.token_limit:
                return True
        if self.message_limit is not None and len(messages) >= self.message_limit:
            return True
        return False

    async def acompact(
        self,
        messages: List[Message],
        run_response: Optional["RunOutput"] = None,
        run_metrics: Optional["RunMetrics"] = None,
    ) -> CompactionResult:
        """Async version of compact()."""
        log_debug(f"[COMPACTION] acompact() called with {len(messages)} messages")

        # 1. Check if compaction needed
        if self.model is None:
            log_debug("[COMPACTION] No model configured (async), skipping")
            return CompactionResult(compacted_messages=messages)
        if not await self.ashould_compact(messages):
            log_debug("[COMPACTION] Below threshold (async), returning original")
            return CompactionResult(compacted_messages=messages)

        # 2. Split messages into groups
        log_debug("[COMPACTION] Splitting messages (async)...")
        system_msgs = [m for m in messages if m.role == "system"]
        non_system = [m for m in messages if m.role != "system"]
        old_messages, preserved_user, recent_messages = self._split_messages(non_system)

        log_debug(
            f"[COMPACTION] Async split: old={len(old_messages)}, preserved={len(preserved_user)}, recent={len(recent_messages)}"
        )

        if not old_messages:
            log_debug("[COMPACTION] No old messages to compact (async)")
            return CompactionResult(compacted_messages=messages)

        # 3. Summarize old messages (merges with existing summary if available)
        existing_summary = run_response.compaction_state.summary if run_response and run_response.compaction_state else None
        log_debug(f"[COMPACTION] Existing summary ({len(existing_summary) if existing_summary else 0} chars)")
        if existing_summary:
            log_debug(
                f"[COMPACTION] --- EXISTING SUMMARY START ---\n{existing_summary}\n[COMPACTION] --- EXISTING SUMMARY END ---"
            )
        log_debug(f"[COMPACTION] Async summarizing {len(old_messages)} messages...")
        new_summary = await self._asummarize(old_messages, existing_summary, run_metrics)

        if not new_summary:
            log_debug("[COMPACTION] Async summarization failed")
            return CompactionResult(compacted_messages=messages)

        log_debug(f"[COMPACTION] New summary ({len(new_summary)} chars)")
        log_debug(f"[COMPACTION] --- NEW SUMMARY START ---\n{new_summary}\n[COMPACTION] --- NEW SUMMARY END ---")

        # 4. Build compacted compacted_messages: system + new summary + preserved user + recent
        summary_msg = Message(role="user", content=SUMMARY_PREFIX + new_summary, from_history=True)
        compacted_messages = system_msgs + [summary_msg] + preserved_user + recent_messages

        # Calculate token metrics
        tokens_before = await self.model.acount_tokens(messages) if self.model else 0
        tokens_after = await self.model.acount_tokens(compacted_messages) if self.model else 0
        tokens_saved = tokens_before - tokens_after
        ratio = tokens_after / tokens_before if tokens_before > 0 else 1.0
        summary_tokens = await self.model.acount_tokens([summary_msg]) if self.model else 0

        log_info(
            f"[COMPACTION] {len(messages)} -> {len(compacted_messages)} msgs | {tokens_before} -> {tokens_after} tokens | ratio={ratio:.2f} | saved={tokens_saved} | summary={summary_tokens} tok"
        )

        # 5. Compress large tool results if still over token limit
        if self.token_limit and await self.model.acount_tokens(compacted_messages) > self.token_limit:
            await self._acompress_tool_results(recent_messages, run_metrics)
            compacted_messages = system_msgs + [summary_msg] + preserved_user + recent_messages
            log_info(
                f"[COMPACTION] Compressed tool results, now {await self.model.acount_tokens(compacted_messages)} tokens"
            )

        # 6. Update run compaction state
        log_debug("[COMPACTION] Updating run compaction state (async)...")
        self._update_compaction_state(run_response, old_messages, new_summary, tokens_saved)
        if run_response and run_response.compaction_state:
            log_debug(
                f"[COMPACTION] Async compaction updated: total={run_response.compaction_state.total_compactions}, ids={len(run_response.compaction_state.compacted_message_ids)}"
            )

        # Update stats for display
        self.stats["messages_compacted"] = self.stats.get("messages_compacted", 0) + len(old_messages)
        self.stats["tokens_saved"] = self.stats.get("tokens_saved", 0) + tokens_saved

        log_debug(f"[COMPACTION] Returning {len(compacted_messages)} compacted messages (async)")
        return CompactionResult(compacted_messages=compacted_messages, summary=new_summary)

    async def _asummarize(
        self,
        old_messages: List[Message],
        existing_summary: Optional[str],
        run_metrics: Optional["RunMetrics"],
    ) -> Optional[str]:
        """Async version of _summarize()."""
        if self.model is None:
            return None

        prompt = self._build_summarization_prompt(old_messages, existing_summary)
        try:
            response = await self.model.aresponse(messages=prompt)
            if run_metrics is not None:
                accumulate_model_metrics(response, self.model, ModelType.COMPRESSION_MODEL, run_metrics)
            return response.content
        except Exception as e:
            log_error(f"Compaction LLM call failed: {e}")
            return None

    async def _acompress_tool_results(self, messages: List[Message], run_metrics: Optional["RunMetrics"]) -> None:
        """Async version of _compress_tool_results()."""
        from agno.compression.manager import CompressionManager

        cm = CompressionManager(model=self.model)
        await cm.acompress(messages, run_metrics)
