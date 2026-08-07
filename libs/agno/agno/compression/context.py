from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from textwrap import dedent
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Set, Tuple
from uuid import uuid4

from agno.models.base import Model
from agno.models.message import Message
from agno.models.utils import get_model
from agno.utils.log import log_error, log_info
from agno.utils.message import safe_truncation_index

if TYPE_CHECKING:
    from agno.metrics import RunMetrics
    from agno.session.agent import AgentSession


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
    """Tracks context compaction state for a session."""

    summary: str = ""
    summary_message_id: str = field(default_factory=lambda: str(uuid4()))
    compacted_message_ids: Set[str] = field(default_factory=set)
    compacted_count: int = 0
    total_compactions: int = 0
    updated_at: Optional[datetime] = None

    def get_summary_message(self) -> Message:
        """Create the summary message to inject into conversation.

        Uses a consistent ID so old summaries can be filtered out when loading history.
        """
        return Message(
            id=self.summary_message_id,
            role="user",
            content=SUMMARY_PREFIX + self.summary,
            from_history=True,
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "summary": self.summary,
            "summary_message_id": self.summary_message_id,
            "compacted_message_ids": list(self.compacted_message_ids),
            "compacted_count": self.compacted_count,
            "total_compactions": self.total_compactions,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CompactionState":
        updated_at = data.get("updated_at")
        if updated_at and isinstance(updated_at, str):
            updated_at = datetime.fromisoformat(updated_at)
        return cls(
            summary=data.get("summary", ""),
            summary_message_id=data.get("summary_message_id") or str(uuid4()),
            compacted_message_ids=set(data.get("compacted_message_ids", [])),
            compacted_count=data.get("compacted_count", 0),
            total_compactions=data.get("total_compactions", 0),
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

    model: Optional[Model] = None
    message_limit: Optional[int] = None
    token_limit: Optional[int] = None
    keep_recent: int = 10
    instructions: Optional[str] = None

    def __post_init__(self) -> None:
        if self.model is not None:
            self.model = get_model(self.model)
        if self.message_limit is None and self.token_limit is None:
            self.message_limit = 50

    def should_compact(self, messages: List[Message]) -> bool:
        """Check if messages exceed compaction threshold."""
        if self.token_limit is not None and self.model is not None:
            if self.model.count_tokens(messages) >= self.token_limit:
                return True
        if self.message_limit is not None:
            if len(messages) >= self.message_limit:
                return True
        return False

    def compact(
        self,
        messages: List[Message],
        session: Optional["AgentSession"] = None,
        run_metrics: Optional["RunMetrics"] = None,
    ) -> CompactionResult:
        """Compact messages if threshold exceeded.

        Returns:
            CompactionResult with compacted_messages and summary (if compaction occurred).
        """
        # 1. Check if compaction needed
        if self.model is None or not self.should_compact(messages):
            return CompactionResult(compacted_messages=messages)

        # 2. Split messages into groups
        system_msgs = [m for m in messages if m.role == "system"]
        non_system = [m for m in messages if m.role != "system"]
        old_messages, preserved_user, recent_messages = self._split_messages(non_system)

        if not old_messages:
            return CompactionResult(compacted_messages=messages)

        # 3. Summarize old messages (merges with existing summary if available)
        existing_summary = session.compaction.summary if session and session.compaction else None
        new_summary = self._summarize(old_messages, existing_summary, run_metrics)

        if not new_summary:
            return CompactionResult(compacted_messages=messages)

        # 4. Build compacted compacted_messages: system + new summary + preserved user + recent
        summary_msg = Message(role="user", content=SUMMARY_PREFIX + new_summary, from_history=True)
        compacted_messages = system_msgs + [summary_msg] + preserved_user + recent_messages
        log_info(f"[COMPACTION] Compacted {len(old_messages)} messages ({len(new_summary)} chars)")

        # 5. Compress large tool results if still over token limit
        if self.token_limit and self.model.count_tokens(compacted_messages) > self.token_limit:
            self._compress_tool_results(recent_messages, run_metrics)
            compacted_messages = system_msgs + [summary_msg] + preserved_user + recent_messages
            log_info(f"[COMPACTION] Compressed tool results, now {self.model.count_tokens(compacted_messages)} tokens")

        # 6. Update session state
        self._update_session_state(session, old_messages, new_summary)

        return CompactionResult(compacted_messages=compacted_messages, summary=new_summary)

    def _split_messages(self, messages: List[Message]) -> Tuple[List[Message], List[Message], List[Message]]:
        """Split messages into: old_messages (to summarize), preserved_user, recent_messages."""
        if not messages:
            return [], [], []

        # Keep last N messages as recent (tool-pair safe)
        keep_count = min(self.keep_recent, len(messages))
        split_idx = safe_truncation_index(messages, len(messages) - keep_count)
        recent_messages = messages[split_idx:]
        older = messages[:split_idx]

        if not older:
            return [], [], recent_messages

        # Extract recent user messages from older portion (preserve intent)
        preserved_user, preserved_indices = self._extract_user_messages(older)
        old_messages = [m for i, m in enumerate(older) if i not in preserved_indices]

        return old_messages, preserved_user, recent_messages

    def _extract_user_messages(self, messages: List[Message]) -> Tuple[List[Message], Set[int]]:
        """Extract recent user messages up to token budget."""
        budget = max(100, (self.message_limit or 50) * 20)
        preserved: List[Message] = []
        indices: Set[int] = set()
        used = 0

        for i in range(len(messages) - 1, -1, -1):
            msg = messages[i]
            if msg.role == "user":
                tokens = self.model.count_tokens([msg]) if self.model else len(str(msg.content or "")) // 4
                if used + tokens <= budget:
                    preserved.insert(0, msg)
                    indices.add(i)
                    used += tokens
                else:
                    break

        return preserved, indices

    def _summarize(
        self,
        old_messages: List[Message],
        existing_summary: Optional[str],
        run_metrics: Optional["RunMetrics"],
    ) -> Optional[str]:
        """Generate summary of old messages via LLM."""
        if self.model is None:
            return None

        system_prompt = self.instructions or DEFAULT_COMPACTION_PROMPT

        # Build prompt: system + existing summary (if any) + old messages + instruction
        prompt_messages: List[Message] = [Message(role="system", content=system_prompt)]
        if existing_summary:
            prompt_messages.append(Message(role="user", content=f"Previous summary to update:\n{existing_summary}"))
        prompt_messages.extend(old_messages)
        prompt_messages.append(Message(role="user", content="Now provide a concise summary of the conversation above."))

        try:
            response = self.model.response(messages=prompt_messages)

            if run_metrics is not None:
                from agno.metrics import ModelType, accumulate_model_metrics

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

    def _update_session_state(
        self,
        session: Optional["AgentSession"],
        old_messages: List[Message],
        new_summary: str,
    ) -> None:
        """Update session.compaction with new state."""
        if session is None:
            return

        prev = session.compaction
        # Reuse existing summary_message_id or generate new one
        summary_id = prev.summary_message_id if prev else str(uuid4())

        # Collect IDs of compacted messages + the summary message ID
        # (so old summaries get filtered when loading history)
        new_ids = {msg.id for msg in old_messages if msg.id}
        new_ids.add(summary_id)
        all_ids = new_ids.union(prev.compacted_message_ids if prev else set())

        session.compaction = CompactionState(
            summary=new_summary,
            summary_message_id=summary_id,
            compacted_message_ids=all_ids,
            compacted_count=(prev.compacted_count if prev else 0) + len(old_messages),
            total_compactions=(prev.total_compactions if prev else 0) + 1,
            updated_at=datetime.now(),
        )

    async def ashould_compact(self, messages: List[Message]) -> bool:
        """Async version of should_compact()."""
        if self.token_limit is not None and self.model is not None:
            if await self.model.acount_tokens(messages) >= self.token_limit:
                return True
        if self.message_limit is not None:
            if len(messages) >= self.message_limit:
                return True
        return False

    async def acompact(
        self,
        messages: List[Message],
        session: Optional["AgentSession"] = None,
        run_metrics: Optional["RunMetrics"] = None,
    ) -> CompactionResult:
        """Async version of compact()."""
        # 1. Check if compaction needed
        if self.model is None or not await self.ashould_compact(messages):
            return CompactionResult(compacted_messages=messages)

        # 2. Split messages into groups
        system_msgs = [m for m in messages if m.role == "system"]
        non_system = [m for m in messages if m.role != "system"]
        old_messages, preserved_user, recent_messages = self._split_messages(non_system)

        if not old_messages:
            return CompactionResult(compacted_messages=messages)

        # 3. Summarize old messages (merges with existing summary if available)
        existing_summary = session.compaction.summary if session and session.compaction else None
        new_summary = await self._asummarize(old_messages, existing_summary, run_metrics)

        if not new_summary:
            return CompactionResult(compacted_messages=messages)

        # 4. Build compacted compacted_messages: system + new summary + preserved user + recent
        summary_msg = Message(role="user", content=SUMMARY_PREFIX + new_summary, from_history=True)
        compacted_messages = system_msgs + [summary_msg] + preserved_user + recent_messages
        log_info(f"[COMPACTION] Compacted {len(old_messages)} messages ({len(new_summary)} chars)")

        # 5. Compress large tool results if still over token limit
        if self.token_limit and await self.model.acount_tokens(compacted_messages) > self.token_limit:
            await self._acompress_tool_results(recent_messages, run_metrics)
            compacted_messages = system_msgs + [summary_msg] + preserved_user + recent_messages
            log_info(
                f"[COMPACTION] Compressed tool results, now {await self.model.acount_tokens(compacted_messages)} tokens"
            )

        # 6. Update session state
        self._update_session_state(session, old_messages, new_summary)

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

        system_prompt = self.instructions or DEFAULT_COMPACTION_PROMPT

        # Build prompt: system + existing summary (if any) + old messages + instruction
        prompt_messages: List[Message] = [Message(role="system", content=system_prompt)]
        if existing_summary:
            prompt_messages.append(Message(role="user", content=f"Previous summary to update:\n{existing_summary}"))
        prompt_messages.extend(old_messages)
        prompt_messages.append(Message(role="user", content="Now provide a concise summary of the conversation above."))

        try:
            response = await self.model.aresponse(messages=prompt_messages)

            if run_metrics is not None:
                from agno.metrics import ModelType, accumulate_model_metrics

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
