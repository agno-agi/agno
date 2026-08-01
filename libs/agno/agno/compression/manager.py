from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Type, Union

from pydantic import BaseModel

from agno.compression._context import _build_summary_message, _get_stored_summary, acompress_messages, compress_messages
from agno.compression._tool import acompress_tool_messages, compress_tool_messages
from agno.metrics import RunMetrics
from agno.models.base import Model
from agno.models.message import Message
from agno.session.agent import AgentSession
from agno.utils.log import log_info


@dataclass
class CompressionManager:
    """Orchestrates tool compression and message compression.

    Tool compression: Summarizes individual tool outputs (mutates msg.compressed_content)
    Message compression: Summarizes old conversation history (returns filtered view)
    """

    model: Optional[Model] = None

    # --- Tool compression config ---
    compress_tool_results: bool = False
    compress_tools_limit: Optional[int] = None
    compress_tools_token_limit: Optional[int] = None
    compress_tools_instructions: Optional[str] = None

    # --- Message compression config ---
    compress_messages: bool = False
    compress_messages_token_limit: Optional[int] = None
    compress_messages_limit: Optional[int] = None
    keep_recent_messages: int = 10
    compress_messages_instructions: Optional[str] = None

    stats: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        # Resolve model string to Model instance
        if self.model is not None:
            from agno.models.utils import get_model

            self.model = get_model(self.model)

        # Default tool compression trigger: after 3 uncompressed tool results
        if self.compress_tool_results:
            if self.compress_tools_limit is None and self.compress_tools_token_limit is None:
                self.compress_tools_limit = 3

        # Default message compression trigger: after 50 messages
        if self.compress_messages:
            if self.compress_messages_token_limit is None and self.compress_messages_limit is None:
                self.compress_messages_limit = 50

    def compress(
        self,
        messages: List[Message],
        session: Optional[AgentSession] = None,
        tools: Optional[List] = None,
        response_format: Optional[Union[Dict, Type[BaseModel]]] = None,
        run_metrics: Optional[RunMetrics] = None,
    ) -> List[Message]:
        """Compress messages for model. Returns messages ready to send."""

        # 1. Tool compression
        if self.compress_tool_results and self.model is not None:
            tool_messages_to_compress = self._should_compress_tool_messages(messages, tools, response_format)
            if tool_messages_to_compress:
                compress_tool_messages(self, tool_messages_to_compress, run_metrics)

        # 2. Message compression
        if self.compress_messages and self.model is not None:
            messages_to_compress = self._should_compress_messages(messages)
            if messages_to_compress:
                return compress_messages(self, messages, messages_to_compress, session, run_metrics)
            # Below threshold — re-inject stored summary if exists
            active = [m for m in messages if not m.is_compacted]
            stored = _get_stored_summary(session)
            if stored:
                return [_build_summary_message(stored)] + active
            return active

        return messages

    async def acompress(
        self,
        messages: List[Message],
        session: Optional[AgentSession] = None,
        tools: Optional[List] = None,
        response_format: Optional[Union[Dict, Type[BaseModel]]] = None,
        run_metrics: Optional[RunMetrics] = None,
    ) -> List[Message]:
        """Async version of compress."""

        # 1. Tool compression
        if self.compress_tool_results and self.model is not None:
            tool_messages_to_compress = await self._ashould_compress_tool_messages(messages, tools, response_format)
            if tool_messages_to_compress:
                await acompress_tool_messages(self, tool_messages_to_compress, run_metrics)

        # 2. Message compression
        if self.compress_messages and self.model is not None:
            messages_to_compress = await self._ashould_compress_messages(messages)
            if messages_to_compress:
                return await acompress_messages(self, messages, messages_to_compress, session, run_metrics)
            # Below threshold — re-inject stored summary if exists
            active = [m for m in messages if not m.is_compacted]
            stored = _get_stored_summary(session)
            if stored:
                return [_build_summary_message(stored)] + active
            return active

        return messages

    def _should_compress_tool_messages(
        self,
        messages: List[Message],
        tools: Optional[List],
        response_format: Optional[Union[Dict, Type[BaseModel]]],
    ) -> List[Message]:
        """Returns tool messages to compress, or empty list if not needed."""
        uncompressed = [m for m in messages if m.role == "tool" and m.compressed_content is None]
        if not uncompressed:
            return []

        # Check token limit
        if self.compress_tools_token_limit is not None and self.model is not None:
            if self.model.count_tokens(messages, tools, response_format) >= self.compress_tools_token_limit:
                log_info("Tool compression: token limit hit")
                return uncompressed

        # Check count limit
        if self.compress_tools_limit is not None:
            if len(uncompressed) >= self.compress_tools_limit:
                log_info(f"Tool compression: count limit {len(uncompressed)} >= {self.compress_tools_limit}")
                return uncompressed

        return []

    async def _ashould_compress_tool_messages(
        self,
        messages: List[Message],
        tools: Optional[List],
        response_format: Optional[Union[Dict, Type[BaseModel]]],
    ) -> List[Message]:
        """Async version. Returns tool messages to compress, or empty list if not needed."""
        uncompressed = [m for m in messages if m.role == "tool" and m.compressed_content is None]
        if not uncompressed:
            return []

        # Check token limit
        if self.compress_tools_token_limit is not None and self.model is not None:
            if await self.model.acount_tokens(messages, tools, response_format) >= self.compress_tools_token_limit:
                log_info("Tool compression: token limit hit")
                return uncompressed

        # Check count limit
        if self.compress_tools_limit is not None:
            if len(uncompressed) >= self.compress_tools_limit:
                log_info(f"Tool compression: count limit {len(uncompressed)} >= {self.compress_tools_limit}")
                return uncompressed

        return []

    def _should_compress_messages(
        self,
        messages: List[Message],
    ) -> List[Message]:
        """Returns active messages to compress, or empty list if not needed."""
        active = [m for m in messages if not m.is_compacted]

        # Check token limit
        if self.compress_messages_token_limit is not None:
            if self.model.count_tokens(active) >= self.compress_messages_token_limit:
                log_info(f"Message compression: token limit {self.compress_messages_token_limit} hit")
                return active

        # Check count limit
        if self.compress_messages_limit is not None:
            if len(active) >= self.compress_messages_limit:
                log_info(f"Message compression: message limit {self.compress_messages_limit} hit")
                return active

        return []

    async def _ashould_compress_messages(
        self,
        messages: List[Message],
    ) -> List[Message]:
        """Async version. Returns active messages to compress, or empty list if not needed."""
        active = [m for m in messages if not m.is_compacted]

        # Check token limit
        if self.compress_messages_token_limit is not None:
            if await self.model.acount_tokens(active) >= self.compress_messages_token_limit:
                log_info(f"Message compression: token limit {self.compress_messages_token_limit} hit")
                return active

        # Check count limit
        if self.compress_messages_limit is not None:
            if len(active) >= self.compress_messages_limit:
                log_info(f"Message compression: message limit {self.compress_messages_limit} hit")
                return active

        return []

    def _get_user_budget(self, active_count: int) -> int:
        """Get user message budget (10% of limit)."""
        if self.compress_messages_token_limit is not None:
            return self.compress_messages_token_limit // 10
        if self.compress_messages_limit is not None:
            return max(1, self.compress_messages_limit // 10)
        return max(1, active_count // 10)


def build_summary_message(summary: str) -> Message:
    """Build a summary message from stored compaction summary.

    Used by session.get_messages() to inject the summary into history.
    """
    from agno.compression.prompts import CONTEXT_COMPACTION_SUMMARY_PREFIX

    return Message(
        role="user",
        content=CONTEXT_COMPACTION_SUMMARY_PREFIX + summary,
        from_history=True,
        temporary=True,
    )
