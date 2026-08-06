from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from textwrap import dedent
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Set, Tuple

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

SUMMARY_PREFIX = dedent("""\
    Another language model started this conversation and produced a summary of the work so far. \
    Use this to continue without duplicating work:

    """)


@dataclass
class CompactionState:
    """Tracks context compaction state for a session."""

    summary: str = ""
    compacted_message_ids: Set[str] = field(default_factory=set)
    compacted_count: int = 0
    total_compactions: int = 0
    updated_at: Optional[datetime] = None

    def get_summary_message(self) -> Message:
        """Create the summary message to inject into conversation."""
        return Message(role="user", content=SUMMARY_PREFIX + self.summary, from_history=True)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "summary": self.summary,
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
            compacted_message_ids=set(data.get("compacted_message_ids", [])),
            compacted_count=data.get("compacted_count", 0),
            total_compactions=data.get("total_compactions", 0),
            updated_at=updated_at,
        )


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
    ) -> Tuple[List[Message], Optional[str]]:
        """Compact messages if threshold exceeded.

        Returns:
            Tuple of (compacted_view, summary). If no compaction needed,
            returns (original_messages, None).
        """
        # 1. Check if compaction needed
        if self.model is None or not self.should_compact(messages):
            return messages, None

        # 2. Separate system messages and partition the rest
        system_msgs = [m for m in messages if m.role == "system"]
        non_system = [m for m in messages if m.role != "system"]
        to_summarize, preserved_user, keep_verbatim = self._partition(non_system)

        if not to_summarize:
            return messages, None

        # 3. Generate summary via LLM
        prev_summary = session.compaction.summary if session and session.compaction else None
        summary = self._generate_summary(to_summarize, prev_summary, run_metrics)

        if not summary:
            return messages, None

        # 4. Build compacted view
        summary_msg = Message(role="user", content=SUMMARY_PREFIX + summary, from_history=True)
        view = system_msgs + [summary_msg] + preserved_user + keep_verbatim
        log_info(f"[COMPACTION] Compacted {len(to_summarize)} messages ({len(summary)} chars)")

        # 5. Phase 2: Compress large tool results if still over limit
        if self.token_limit and self.model.count_tokens(view) > self.token_limit:
            self._compress_large_tool_results(keep_verbatim, run_metrics)
            view = system_msgs + [summary_msg] + preserved_user + keep_verbatim
            log_info(f"[COMPACTION] Compressed tool results, now {self.model.count_tokens(view)} tokens")

        # 6. Update session state
        self._update_session_state(session, to_summarize, summary)

        return view, summary

    def _partition(self, messages: List[Message]) -> Tuple[List[Message], List[Message], List[Message]]:
        """Split messages into: to_summarize, preserved_user, keep_verbatim."""
        if not messages:
            return [], [], []

        # Keep last N messages verbatim (tool-pair safe)
        keep_count = min(self.keep_recent, len(messages))
        split_idx = safe_truncation_index(messages, len(messages) - keep_count)
        keep_verbatim = messages[split_idx:]
        older = messages[:split_idx]

        if not older:
            return [], [], keep_verbatim

        # Extract recent user messages from older portion
        preserved_user, preserved_indices = self._extract_recent_user_messages(older)
        to_summarize = [m for i, m in enumerate(older) if i not in preserved_indices]

        return to_summarize, preserved_user, keep_verbatim

    def _extract_recent_user_messages(self, messages: List[Message]) -> Tuple[List[Message], Set[int]]:
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

    def _generate_summary(
        self,
        messages: List[Message],
        prev_summary: Optional[str],
        run_metrics: Optional["RunMetrics"],
    ) -> Optional[str]:
        """Generate summary of messages via LLM."""
        if self.model is None:
            return None

        prompt_text = self._format_messages_for_llm(messages, prev_summary)
        system_prompt = self.instructions or DEFAULT_COMPACTION_PROMPT

        try:
            response = self.model.response(
                messages=[
                    Message(role="system", content=system_prompt),
                    Message(role="user", content=prompt_text),
                ]
            )

            if run_metrics is not None:
                from agno.metrics import ModelType, accumulate_model_metrics

                accumulate_model_metrics(response, self.model, ModelType.COMPRESSION_MODEL, run_metrics)

            return response.content
        except Exception as e:
            log_error(f"Compaction LLM call failed: {e}")
            return None

    def _format_messages_for_llm(self, messages: List[Message], prev_summary: Optional[str]) -> str:
        """Format messages as text for summarization LLM."""
        parts = []

        if prev_summary:
            parts.append(f"[PREVIOUS SUMMARY]\n{prev_summary}\n\n[NEW MESSAGES]")

        for msg in messages:
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

    def _compress_large_tool_results(
        self, messages: List[Message], run_metrics: Optional["RunMetrics"]
    ) -> None:
        """Compress large tool results using CompressionManager."""
        from agno.compression.manager import CompressionManager

        cm = CompressionManager(model=self.model)
        cm.compress(messages, run_metrics)

    def _update_session_state(
        self,
        session: Optional["AgentSession"],
        summarized_messages: List[Message],
        summary: str,
    ) -> None:
        """Update session.compaction with new state."""
        if session is None:
            return

        prev = session.compaction
        new_ids = {msg.id for msg in summarized_messages if msg.id}
        all_ids = new_ids.union(prev.compacted_message_ids if prev else set())

        session.compaction = CompactionState(
            summary=summary,
            compacted_message_ids=all_ids,
            compacted_count=(prev.compacted_count if prev else 0) + len(summarized_messages),
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
    ) -> Tuple[List[Message], Optional[str]]:
        """Async version of compact()."""
        # 1. Check if compaction needed
        if self.model is None or not await self.ashould_compact(messages):
            return messages, None

        # 2. Separate system messages and partition the rest
        system_msgs = [m for m in messages if m.role == "system"]
        non_system = [m for m in messages if m.role != "system"]
        to_summarize, preserved_user, keep_verbatim = self._partition(non_system)

        if not to_summarize:
            return messages, None

        # 3. Generate summary via LLM
        prev_summary = session.compaction.summary if session and session.compaction else None
        summary = await self._agenerate_summary(to_summarize, prev_summary, run_metrics)

        if not summary:
            return messages, None

        # 4. Build compacted view
        summary_msg = Message(role="user", content=SUMMARY_PREFIX + summary, from_history=True)
        view = system_msgs + [summary_msg] + preserved_user + keep_verbatim
        log_info(f"[COMPACTION] Compacted {len(to_summarize)} messages ({len(summary)} chars)")

        # 5. Phase 2: Compress large tool results if still over limit
        if self.token_limit and await self.model.acount_tokens(view) > self.token_limit:
            await self._acompress_large_tool_results(keep_verbatim, run_metrics)
            view = system_msgs + [summary_msg] + preserved_user + keep_verbatim
            log_info(f"[COMPACTION] Compressed tool results, now {await self.model.acount_tokens(view)} tokens")

        # 6. Update session state
        self._update_session_state(session, to_summarize, summary)

        return view, summary

    async def _agenerate_summary(
        self,
        messages: List[Message],
        prev_summary: Optional[str],
        run_metrics: Optional["RunMetrics"],
    ) -> Optional[str]:
        """Async version of _generate_summary()."""
        if self.model is None:
            return None

        prompt_text = self._format_messages_for_llm(messages, prev_summary)
        system_prompt = self.instructions or DEFAULT_COMPACTION_PROMPT

        try:
            response = await self.model.aresponse(
                messages=[
                    Message(role="system", content=system_prompt),
                    Message(role="user", content=prompt_text),
                ]
            )

            if run_metrics is not None:
                from agno.metrics import ModelType, accumulate_model_metrics

                accumulate_model_metrics(response, self.model, ModelType.COMPRESSION_MODEL, run_metrics)

            return response.content
        except Exception as e:
            log_error(f"Compaction LLM call failed: {e}")
            return None

    async def _acompress_large_tool_results(
        self, messages: List[Message], run_metrics: Optional["RunMetrics"]
    ) -> None:
        """Async version of _compress_large_tool_results()."""
        from agno.compression.manager import CompressionManager

        cm = CompressionManager(model=self.model)
        await cm.acompress(messages, run_metrics)
