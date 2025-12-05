import asyncio
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Set

from agno.compression.context import CompressedContext
from agno.compression.prompts import CONTEXT_COMPRESSION_PROMPT, TOOL_COMPRESSION_PROMPT
from agno.models.base import Model
from agno.models.message import Message
from agno.models.utils import get_model
from agno.utils.log import log_error, log_info, log_warning


@dataclass
class CompressionManager:
    model: Optional[Model] = None

    # Tool compression
    compress_tool_results: bool = False
    compress_tool_results_limit: int = 3
    compress_tool_results_token_limit: Optional[int] = None
    compress_tool_call_instructions: Optional[str] = None

    # Context compression
    compress_context: bool = False
    compress_context_token_limit: Optional[int] = None
    compress_context_instructions: Optional[str] = None

    # State
    existing_compressed_ids: Optional[Set[str]] = None
    last_compressed_context: Optional[CompressedContext] = None

    stats: Dict[str, Any] = field(default_factory=dict)

    def should_compress(self, messages: List[Message], tools: Optional[List] = None) -> bool:
        # Context compression takes priority
        if self.compress_context and self.compress_context_token_limit and self.model:
            tokens = self.model.count_tokens(messages, tools)
            if tokens >= self.compress_context_token_limit:
                log_info(f"Context token limit hit: {tokens} >= {self.compress_context_token_limit}")
                return True

        # Tool compression
        if self.compress_tool_results:
            if self.compress_tool_results_token_limit and self.model:
                tokens = self.model.count_tokens(messages, tools)
                if tokens >= self.compress_tool_results_token_limit:
                    log_info(f"Tool token limit hit: {tokens} >= {self.compress_tool_results_token_limit}")
                    return True
            else:
                uncompressed = sum(1 for m in messages if m.role == "tool" and m.compressed_content is None)
                if uncompressed >= self.compress_tool_results_limit:
                    log_info(f"Tool count limit hit: {uncompressed} >= {self.compress_tool_results_limit}")
                    return True

        return False

    def compress(self, messages: List[Message], tools: Optional[List] = None) -> None:
        if self._should_compress_context(messages, tools):
            self._compress_context(messages)
        elif self._should_compress_tools(messages, tools):
            self._compress_tools(messages)

    async def acompress(self, messages: List[Message], tools: Optional[List] = None) -> None:
        if self._should_compress_context(messages, tools):
            await self._acompress_context(messages)
        elif self._should_compress_tools(messages, tools):
            await self._acompress_tools(messages)

    def _should_compress_context(self, messages: List[Message], tools: Optional[List] = None) -> bool:
        if not self.compress_context or not self.compress_context_token_limit or not self.model:
            return False
        return self.model.count_tokens(messages, tools) >= self.compress_context_token_limit

    def _should_compress_tools(self, messages: List[Message], tools: Optional[List] = None) -> bool:
        if not self.compress_tool_results:
            return False
        if self.compress_tool_results_token_limit and self.model:
            return self.model.count_tokens(messages, tools) >= self.compress_tool_results_token_limit
        uncompressed = sum(1 for m in messages if m.role == "tool" and m.compressed_content is None)
        return uncompressed >= self.compress_tool_results_limit

    def _compress_context(self, messages: List[Message]) -> None:
        if len(messages) < 2:
            return

        system_msg = messages[0] if messages[0].role == "system" else None
        if not system_msg:
            return

        # Find last user message
        latest_user = next((m for m in reversed(messages) if m.role == "user"), None)
        if not latest_user:
            return

        # Compress everything except system and latest user
        msgs_to_compress = [m for m in messages if m is not system_msg and m is not latest_user]
        if not msgs_to_compress:
            return

        summary = self._compress_messages(msgs_to_compress)
        if not summary:
            return

        # Track message IDs
        all_ids: Set[str] = set(self.existing_compressed_ids or set())
        all_ids.update(m.id for m in msgs_to_compress)

        # Rebuild: [system, context, original_user]
        messages.clear()
        messages.append(system_msg)
        messages.append(Message(role="user", content=f"<compressed_context>\n{summary}\n</compressed_context>"))
        messages.append(latest_user)

        self.last_compressed_context = CompressedContext(
            content=summary,
            message_ids=all_ids,
            updated_at=datetime.now(),
        )
        log_info(f"Compressed {len(msgs_to_compress)} messages")

    async def _acompress_context(self, messages: List[Message]) -> None:
        if len(messages) < 2:
            return

        system_msg = messages[0] if messages[0].role == "system" else None
        if not system_msg:
            return

        # Find last user message
        latest_user = next((m for m in reversed(messages) if m.role == "user"), None)
        if not latest_user:
            return

        # Compress everything except system and latest user
        msgs_to_compress = [m for m in messages if m is not system_msg and m is not latest_user]
        if not msgs_to_compress:
            return

        summary = await self._acompress_messages(msgs_to_compress)
        if not summary:
            return

        # Track message IDs
        all_ids: Set[str] = set(self.existing_compressed_ids or set())
        all_ids.update(m.id for m in msgs_to_compress)

        # Rebuild: [system, context, original_user]
        messages.clear()
        messages.append(system_msg)
        messages.append(Message(role="user", content=f"<compressed_context>\n{summary}\n</compressed_context>"))
        messages.append(latest_user)

        self.last_compressed_context = CompressedContext(
            content=summary,
            message_ids=all_ids,
            updated_at=datetime.now(),
        )
        log_info(f"Compressed {len(msgs_to_compress)} messages")

    def _compress_tools(self, messages: List[Message]) -> None:
        for msg in messages:
            if msg.role == "tool" and msg.compressed_content is None:
                compressed = self._compress_tool_result(msg)
                if compressed:
                    msg.compressed_content = compressed

    async def _acompress_tools(self, messages: List[Message]) -> None:
        uncompressed = [m for m in messages if m.role == "tool" and m.compressed_content is None]
        if not uncompressed:
            return
        results = await asyncio.gather(*[self._acompress_tool_result(m) for m in uncompressed])
        for msg, compressed in zip(uncompressed, results):
            if compressed:
                msg.compressed_content = compressed

    def _compress_tool_result(self, tool_msg: Message) -> Optional[str]:
        self.model = get_model(self.model)
        if not self.model:
            log_warning("No compression model available")
            return None

        tool_name = tool_msg.tool_name
        if not tool_name and tool_msg.tool_calls:
            names = [str(tc.get("tool_name")) for tc in tool_msg.tool_calls if tc.get("tool_name")]
            tool_name = ", ".join(names) if names else None

        content = f"Tool: {tool_name or 'unknown'}\n{tool_msg.content}"
        prompt = self.compress_tool_call_instructions or TOOL_COMPRESSION_PROMPT

        try:
            response = self.model.response(
                messages=[
                    Message(role="system", content=prompt),
                    Message(role="user", content=f"Compress:\n{content}"),
                ]
            )
            return response.content
        except Exception as e:
            log_error(f"Tool compression failed: {e}")
            return None

    async def _acompress_tool_result(self, tool_msg: Message) -> Optional[str]:
        self.model = get_model(self.model)
        if not self.model:
            log_warning("No compression model available")
            return None

        tool_name = tool_msg.tool_name
        if not tool_name and tool_msg.tool_calls:
            names = [str(tc.get("tool_name")) for tc in tool_msg.tool_calls if tc.get("tool_name")]
            tool_name = ", ".join(names) if names else None

        content = f"Tool: {tool_name or 'unknown'}\n{tool_msg.content}"
        prompt = self.compress_tool_call_instructions or TOOL_COMPRESSION_PROMPT

        try:
            response = await self.model.aresponse(
                messages=[
                    Message(role="system", content=prompt),
                    Message(role="user", content=f"Compress:\n{content}"),
                ]
            )
            return response.content
        except Exception as e:
            log_error(f"Tool compression failed: {e}")
            return None

    def _compress_messages(self, messages: List[Message]) -> Optional[str]:
        self.model = get_model(self.model)
        if not self.model:
            log_warning("No compression model available")
            return None

        parts = []
        for msg in messages:
            content = msg.get_content_string() if hasattr(msg, "get_content_string") else str(msg.content)
            if content:
                parts.append(f"{msg.role.capitalize()}: {content}")
        conversation = "\n".join(parts)

        prompt = self.compress_context_instructions or CONTEXT_COMPRESSION_PROMPT
        try:
            response = self.model.response(
                messages=[
                    Message(role="system", content=prompt),
                    Message(role="user", content=f"Compress:\n\n{conversation}"),
                ]
            )
            return response.content
        except Exception as e:
            log_error(f"Context compression failed: {e}")
            return None

    async def _acompress_messages(self, messages: List[Message]) -> Optional[str]:
        self.model = get_model(self.model)
        if not self.model:
            log_warning("No compression model available")
            return None

        parts = []
        for msg in messages:
            content = msg.get_content_string() if hasattr(msg, "get_content_string") else str(msg.content)
            if content:
                parts.append(f"{msg.role.capitalize()}: {content}")
        conversation = "\n".join(parts)

        prompt = self.compress_context_instructions or CONTEXT_COMPRESSION_PROMPT
        try:
            response = await self.model.aresponse(
                messages=[
                    Message(role="system", content=prompt),
                    Message(role="user", content=f"Compress:\n\n{conversation}"),
                ]
            )
            return response.content
        except Exception as e:
            log_error(f"Context compression failed: {e}")
            return None
