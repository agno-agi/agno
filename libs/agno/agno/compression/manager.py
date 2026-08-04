from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Type, Union

from pydantic import BaseModel

from agno.compression._context import CompactionResult, acompress_context, compress_context
from agno.compression._tool import acompress_tool_results, compress_tool_results
from agno.metrics import RunMetrics
from agno.models.base import Model
from agno.models.message import Message
from agno.session.agent import AgentSession
from agno.utils.log import log_debug, log_info


@dataclass
class CompressionManager:
    """Orchestrates tool compression and context compaction.

    Tool compression: Summarizes individual tool outputs (mutates msg.compressed_content)
    Context compaction: Summarizes old conversation history (returns filtered view)
    """

    model: Optional[Model] = None

    # --- Tool compression config ---
    compress_tool_results: bool = False
    compress_tools_limit: Optional[int] = None
    compress_tools_token_limit: Optional[int] = None
    compress_tools_instructions: Optional[str] = None

    # --- Context compaction config ---
    compress_messages: bool = False
    compress_messages_token_limit: Optional[int] = None
    compress_messages_limit: Optional[int] = None
    keep_recent_messages: int = 10
    compress_messages_instructions: Optional[str] = None

    stats: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.model is not None:
            from agno.models.utils import get_model

            self.model = get_model(self.model)

        # Default tool compression trigger: after 3 uncompressed tool results
        if self.compress_tool_results:
            if self.compress_tools_limit is None and self.compress_tools_token_limit is None:
                self.compress_tools_limit = 3

        # Default context compaction trigger: after 50 messages
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
    ) -> CompactionResult:
        """Compress messages for model. Returns CompactionResult — call commit() after model success."""
        log_debug(f"[COMPRESS] compress: {len(messages)} messages")

        # 1. Tool compression (mutates in place)
        if self.compress_tool_results and self.model is not None:
            tool_msgs = self._get_tool_messages_to_compress(messages, tools, response_format)
            if tool_msgs:
                log_info(f"[COMPRESS] Tool compression: {len(tool_msgs)} messages")
                compress_tool_results(self, tool_msgs, run_metrics)

        # 2. Context compaction
        if self.compress_messages and self.model is not None:
            return compress_context(self, messages, session, run_metrics)

        return CompactionResult(view=messages, to_compact=[])

    async def acompress(
        self,
        messages: List[Message],
        session: Optional[AgentSession] = None,
        tools: Optional[List] = None,
        response_format: Optional[Union[Dict, Type[BaseModel]]] = None,
        run_metrics: Optional[RunMetrics] = None,
    ) -> CompactionResult:
        """Async version of compress."""
        log_debug(f"[COMPRESS] acompress: {len(messages)} messages")

        # 1. Tool compression (mutates in place)
        if self.compress_tool_results and self.model is not None:
            tool_msgs = await self._aget_tool_messages_to_compress(messages, tools, response_format)
            if tool_msgs:
                log_info(f"[COMPRESS] Tool compression: {len(tool_msgs)} messages")
                await acompress_tool_results(self, tool_msgs, run_metrics)

        # 2. Context compaction
        if self.compress_messages and self.model is not None:
            return await acompress_context(self, messages, session, run_metrics)

        return CompactionResult(view=messages, to_compact=[])

    # --- Tool compression helpers ---

    def _get_tool_messages_to_compress(
        self,
        messages: List[Message],
        tools: Optional[List],
        response_format: Optional[Union[Dict, Type[BaseModel]]],
    ) -> List[Message]:
        """Returns tool messages to compress, or empty list if below threshold."""
        uncompressed = [m for m in messages if m.role == "tool" and m.compressed_content is None]
        if not uncompressed:
            return []

        if self.compress_tools_token_limit is not None and self.model is not None:
            if self.model.count_tokens(messages, tools, response_format) >= self.compress_tools_token_limit:
                return uncompressed

        if self.compress_tools_limit is not None:
            if len(uncompressed) >= self.compress_tools_limit:
                return uncompressed

        return []

    async def _aget_tool_messages_to_compress(
        self,
        messages: List[Message],
        tools: Optional[List],
        response_format: Optional[Union[Dict, Type[BaseModel]]],
    ) -> List[Message]:
        """Async version."""
        uncompressed = [m for m in messages if m.role == "tool" and m.compressed_content is None]
        if not uncompressed:
            return []

        if self.compress_tools_token_limit is not None and self.model is not None:
            if await self.model.acount_tokens(messages, tools, response_format) >= self.compress_tools_token_limit:
                return uncompressed

        if self.compress_tools_limit is not None:
            if len(uncompressed) >= self.compress_tools_limit:
                return uncompressed

        return []
