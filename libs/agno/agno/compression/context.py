from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from textwrap import dedent
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Set

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
    """Tracks context compaction state for a session.

    The compacted_message_ids field stores IDs of all messages that have been summarized.
    This solves the "marks on copies" problem: history messages are deepcopy'd at load time,
    so marking them with is_compacted=True doesn't persist. By storing IDs centrally in
    session.compaction (which IS persisted), we can filter by ID on next load.
    """

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
class CompactionResult:
    """Result of context compaction."""

    view: List[Message]
    summary: Optional[str] = None


@dataclass
class ContextCompactionManager:
    """Manages context compaction — summarizing old conversation history."""

    model: Optional[Model] = None
    message_limit: Optional[int] = None
    token_limit: Optional[int] = None
    keep_recent: int = 10
    instructions: Optional[str] = None
    stats: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.model is not None:
            self.model = get_model(self.model)
        if self.message_limit is None and self.token_limit is None:
            self.message_limit = 50

    def compact(
        self,
        messages: List[Message],
        session: Optional["AgentSession"] = None,
        run_metrics: Optional["RunMetrics"] = None,
    ) -> CompactionResult:
        """Compact messages into a shorter context view.

        Two-phase compaction:
        1. Summarize old history messages (preserves recent messages verbatim)
        2. If still over token_limit, compress large tool results

        Returns CompactionResult with the compacted view. Session state is updated
        in-place (persisted when session is saved).
        """
        # 1. Early exit if no model configured
        if self.model is None:
            return CompactionResult(view=messages)

        # 2. Get stored summary for incremental compaction
        stored_summary = self._get_stored_summary(session)

        # 3. Check threshold — skip if under limit
        # Note: messages already filtered by _messages.py via skip_compacted_messages=True
        if not self._needs_compaction(messages):
            return CompactionResult(view=messages)

        # 4. Separate system messages (always kept at top)
        system_msgs = [m for m in messages if m.role == "system"]
        non_system = [m for m in messages if m.role != "system"]

        # 5. Partition non-system messages:
        #    - to_compact: older messages to summarize
        #    - preserved_user: recent user messages (kept verbatim for intent)
        #    - keep_verbatim: last N messages (tool-pair safe via safe_truncation_index)
        to_compact, preserved_user, keep_verbatim = self._partition(non_system)

        # 6. Nothing to compact — all messages are in keep_verbatim
        if not to_compact:
            return CompactionResult(view=messages)

        # 7. Generate summary via LLM (merges with previous summary if exists)
        summary = self._summarize(to_compact, stored_summary, run_metrics)
        if not summary:
            return CompactionResult(view=messages)

        # 8. Build compacted view: [system] + [summary] + [preserved_user] + [keep_verbatim]
        view = system_msgs + [self._make_summary_msg(summary)] + preserved_user + keep_verbatim
        log_info(f"[COMPACTION] Compacted {len(to_compact)} messages ({len(summary)} chars)")

        # 9. Phase 2: If still over token_limit, compress large tool results in keep_verbatim
        if self.token_limit is not None:
            view_tokens = self.model.count_tokens(view)
            if view_tokens > self.token_limit:
                keep_verbatim = self._compress_tool_results(keep_verbatim, run_metrics)
                view = system_msgs + [self._make_summary_msg(summary)] + preserved_user + keep_verbatim
                log_info(f"[COMPACTION] Compressed tool results, now {self.model.count_tokens(view)} tokens")

        # 10. Update session compaction state (persisted when session is saved)
        if session is not None:
            prev = session.compaction
            new_ids = {msg.id for msg in to_compact if msg.id}
            all_ids = new_ids.union(prev.compacted_message_ids if prev else set())

            session.compaction = CompactionState(
                summary=summary,
                compacted_message_ids=all_ids,
                compacted_count=(prev.compacted_count if prev else 0) + len(to_compact),
                total_compactions=(prev.total_compactions if prev else 0) + 1,
                updated_at=datetime.now(),
            )

        return CompactionResult(view=view, summary=summary)

    async def acompact(
        self,
        messages: List[Message],
        session: Optional["AgentSession"] = None,
        run_metrics: Optional["RunMetrics"] = None,
    ) -> CompactionResult:
        """Async version of compact(). See compact() for detailed documentation."""
        # 1. Early exit if no model configured
        if self.model is None:
            return CompactionResult(view=messages)

        # 2. Get stored summary for incremental compaction
        stored_summary = self._get_stored_summary(session)

        # 3. Check threshold — skip if under limit
        # Note: messages already filtered by _messages.py via skip_compacted_messages=True
        if not await self._aneeds_compaction(messages):
            return CompactionResult(view=messages)

        # 4. Separate system messages (always kept at top)
        system_msgs = [m for m in messages if m.role == "system"]
        non_system = [m for m in messages if m.role != "system"]

        # 5. Partition non-system messages
        to_compact, preserved_user, keep_verbatim = self._partition(non_system)

        # 6. Nothing to compact — all messages are in keep_verbatim
        if not to_compact:
            return CompactionResult(view=messages)

        # 7. Generate summary via LLM (merges with previous summary if exists)
        summary = await self._asummarize(to_compact, stored_summary, run_metrics)
        if not summary:
            return CompactionResult(view=messages)

        # 8. Build compacted view: [system] + [summary] + [preserved_user] + [keep_verbatim]
        view = system_msgs + [self._make_summary_msg(summary)] + preserved_user + keep_verbatim
        log_info(f"[COMPACTION] Compacted {len(to_compact)} messages ({len(summary)} chars)")

        # 9. Phase 2: If still over token_limit, compress large tool results in keep_verbatim
        if self.token_limit is not None:
            view_tokens = await self.model.acount_tokens(view)
            if view_tokens > self.token_limit:
                keep_verbatim = await self._acompress_tool_results(keep_verbatim, run_metrics)
                view = system_msgs + [self._make_summary_msg(summary)] + preserved_user + keep_verbatim
                log_info(f"[COMPACTION] Compressed tool results, now {await self.model.acount_tokens(view)} tokens")

        # 10. Update session compaction state (persisted when session is saved)
        if session is not None:
            prev = session.compaction
            new_ids = {msg.id for msg in to_compact if msg.id}
            all_ids = new_ids.union(prev.compacted_message_ids if prev else set())

            session.compaction = CompactionState(
                summary=summary,
                compacted_message_ids=all_ids,
                compacted_count=(prev.compacted_count if prev else 0) + len(to_compact),
                total_compactions=(prev.total_compactions if prev else 0) + 1,
                updated_at=datetime.now(),
            )

        return CompactionResult(view=view, summary=summary)

    # --- Private ---

    def _needs_compaction(self, active: List[Message]) -> bool:
        if self.token_limit is not None and self.model is not None:
            if self.model.count_tokens(active) >= self.token_limit:
                return True
        if self.message_limit is not None:
            if len(active) >= self.message_limit:
                return True
        return False

    async def _aneeds_compaction(self, active: List[Message]) -> bool:
        if self.token_limit is not None and self.model is not None:
            if await self.model.acount_tokens(active) >= self.token_limit:
                return True
        if self.message_limit is not None:
            if len(active) >= self.message_limit:
                return True
        return False

    def _get_stored_summary(self, session: Optional["AgentSession"]) -> Optional[str]:
        if session is None:
            return None
        compaction = getattr(session, "compaction", None)
        return compaction.summary if compaction and compaction.summary else None

    def _partition(self, messages: List[Message]) -> tuple:
        """Split non-system messages into three groups for compaction.

        Returns (to_compact, preserved_user, keep_verbatim):
        - to_compact: Older messages that will be summarized by LLM
        - preserved_user: Recent user messages kept verbatim (preserves intent)
        - keep_verbatim: Last N messages kept verbatim (tool-pair safe)

        Visual:
            [m1, m2, ..., m35, m36(user), m37, m38(user), m39, m40, ..., m50]
             └── to_compact ──┘ └─ preserved_user ─┘ └──── keep_verbatim ────┘
        """
        if not messages:
            return [], [], []

        # 1. Keep last N messages verbatim (default: 10)
        #    safe_truncation_index snaps boundary to avoid breaking tool pairs
        keep_count = min(self.keep_recent, len(messages))
        split_idx = safe_truncation_index(messages, len(messages) - keep_count)
        keep_verbatim = messages[split_idx:]
        remaining = messages[:split_idx]

        if not remaining:
            return [], [], keep_verbatim

        # 2. From remaining (older) messages, preserve recent user messages
        #    User messages often contain critical intent/corrections
        #    Budget: ~1000 tokens (roughly 2-5 user messages)
        limit = self.message_limit or len(messages)
        user_budget = max(100, limit * 20)
        preserved_user: List[Message] = []
        budget_used = 0
        preserved_indices = set()

        # Walk backwards to get most recent user messages first
        for i in range(len(remaining) - 1, -1, -1):
            msg = remaining[i]
            if msg.role == "user":
                tokens = self.model.count_tokens([msg]) if self.model else len(str(msg.content or "")) // 4
                if budget_used + tokens <= user_budget:
                    preserved_user.insert(0, msg)
                    preserved_indices.add(i)
                    budget_used += tokens
                else:
                    break

        # 3. Everything else gets summarized
        to_compact = [m for i, m in enumerate(remaining) if i not in preserved_indices]
        return to_compact, preserved_user, keep_verbatim

    def _make_summary_msg(self, summary: str) -> Message:
        # from_history=True prevents duplication on history reload
        # NOT temporary=True — that would strip summary from fallback models
        return Message(role="user", content=SUMMARY_PREFIX + summary, from_history=True)

    def _summarize(
        self, to_compact: List[Message], prev_summary: Optional[str], run_metrics: Optional["RunMetrics"]
    ) -> Optional[str]:
        prompt = self.instructions or DEFAULT_COMPACTION_PROMPT
        content = self._format_for_summary(to_compact, prev_summary)
        return self._call_llm(prompt, content, run_metrics)

    async def _asummarize(
        self, to_compact: List[Message], prev_summary: Optional[str], run_metrics: Optional["RunMetrics"]
    ) -> Optional[str]:
        prompt = self.instructions or DEFAULT_COMPACTION_PROMPT
        content = self._format_for_summary(to_compact, prev_summary)
        return await self._acall_llm(prompt, content, run_metrics)

    def _format_for_summary(self, to_compact: List[Message], prev_summary: Optional[str]) -> str:
        parts = []
        if prev_summary:
            parts.append(f"[PREVIOUS SUMMARY]\n{prev_summary}\n\n[NEW MESSAGES]")

        for msg in to_compact:
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

    def _call_llm(self, system_prompt: str, user_content: str, run_metrics: Optional["RunMetrics"]) -> Optional[str]:
        if self.model is None:
            return None
        try:
            response = self.model.response(
                messages=[Message(role="system", content=system_prompt), Message(role="user", content=user_content)]
            )
            if run_metrics is not None:
                from agno.metrics import ModelType, accumulate_model_metrics

                accumulate_model_metrics(response, self.model, ModelType.COMPRESSION_MODEL, run_metrics)
            return response.content
        except Exception as e:
            log_error(f"Compaction LLM call failed: {e}")
            return None

    async def _acall_llm(
        self, system_prompt: str, user_content: str, run_metrics: Optional["RunMetrics"]
    ) -> Optional[str]:
        if self.model is None:
            return None
        try:
            response = await self.model.aresponse(
                messages=[Message(role="system", content=system_prompt), Message(role="user", content=user_content)]
            )
            if run_metrics is not None:
                from agno.metrics import ModelType, accumulate_model_metrics

                accumulate_model_metrics(response, self.model, ModelType.COMPRESSION_MODEL, run_metrics)
            return response.content
        except Exception as e:
            log_error(f"Compaction LLM call failed: {e}")
            return None

    def _compress_tool_results(self, messages: List[Message], run_metrics: Optional["RunMetrics"]) -> List[Message]:
        """Compress large tool results using CompressionManager."""
        from agno.compression.manager import CompressionManager

        cm = CompressionManager(model=self.model)
        cm.compress(messages, run_metrics)
        return messages

    async def _acompress_tool_results(
        self, messages: List[Message], run_metrics: Optional["RunMetrics"]
    ) -> List[Message]:
        """Async version of _compress_tool_results."""
        from agno.compression.manager import CompressionManager

        cm = CompressionManager(model=self.model)
        await cm.acompress(messages, run_metrics)
        return messages
