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
    compress_context_messages_limit: int = 10
    compress_context_instructions: Optional[str] = None

    # State
    existing_compressed_ids: Optional[Set[str]] = None
    last_compressed_context: Optional[CompressedContext] = None

    stats: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if self.compress_context_token_limit is not None:
            self.compress_context = True

        if self.compress_tool_results_token_limit is not None:
            self.compress_tool_results = True

    def should_compress(self, messages: List[Message], tools: Optional[List] = None) -> bool:
        if self.compress_context:
            if self.compress_context_token_limit and self.model:
                tokens = self.model.count_tokens(messages, tools)
                if tokens >= self.compress_context_token_limit:
                    return True
            # Message count-based compression (fallback when no token limit)
            else:
                msg_count = len([m for m in messages if m.role in ("user", "assistant", "tool")])
                if msg_count >= self.compress_context_messages_limit:
                    return True

        # Tool compression
        if self.compress_tool_results:
            if self.compress_tool_results_token_limit and self.model:
                tokens = self.model.count_tokens(messages, tools)
                if tokens >= self.compress_tool_results_token_limit:
                    return True
            else:
                uncompressed = sum(1 for m in messages if m.role == "tool" and m.compressed_content is None)
                if uncompressed >= self.compress_tool_results_limit:
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
        if not self.compress_context:
            return False

        if self.compress_context_token_limit and self.model:
            return self.model.count_tokens(messages, tools) >= self.compress_context_token_limit
        msg_count = len([m for m in messages if m.role in ("user", "assistant", "tool")])
        return msg_count >= self.compress_context_messages_limit

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
        new_ids = {m.id for m in msgs_to_compress}
        all_ids.update(new_ids)

        # Rebuild: [system, context, original_user]
        messages.clear()
        messages.append(system_msg)
        messages.append(Message(role="user", content=f"Previous conversation summary:\n\n{summary}"))
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
        new_ids = {m.id for m in msgs_to_compress}
        all_ids.update(new_ids)

        # Rebuild: [system, context, original_user]
        messages.clear()
        messages.append(system_msg)
        messages.append(Message(role="user", content=f"Previous conversation summary:\n\n{summary}"))
        messages.append(latest_user)

        self.last_compressed_context = CompressedContext(
            content=summary,
            message_ids=all_ids,
            updated_at=datetime.now(),
        )
        log_info(f"Compressed {len(msgs_to_compress)} messages")

    def _compress_tools(self, messages: List[Message]) -> None:
        uncompressed = [m for m in messages if m.role == "tool" and m.compressed_content is None]

        compressed_count = 0
        for msg in uncompressed:
            original_size = len(str(msg.content)) if msg.content else 0
            compressed = self._compress_tool_result(msg)
            if compressed:
                msg.compressed_content = compressed
                compressed_count += 1
                # Track stats for display
                self.stats["tool_results_compressed"] = self.stats.get("tool_results_compressed", 0) + 1
                self.stats["original_size"] = self.stats.get("original_size", 0) + original_size
                self.stats["compressed_size"] = self.stats.get("compressed_size", 0) + len(compressed)

        if compressed_count > 0:
            log_info(f"Tool call compression threshold hit. Compressing {compressed_count} tool results")

    async def _acompress_tools(self, messages: List[Message]) -> None:
        uncompressed = [m for m in messages if m.role == "tool" and m.compressed_content is None]
        if not uncompressed:
            return

        # Track original sizes before compression
        original_sizes = [len(str(msg.content)) if msg.content else 0 for msg in uncompressed]
        results = await asyncio.gather(*[self._acompress_tool_result(m) for m in uncompressed])

        compressed_count = 0
        for msg, compressed, original_size in zip(uncompressed, results, original_sizes):
            if compressed:
                msg.compressed_content = compressed
                compressed_count += 1
                # Track stats for display
                self.stats["tool_results_compressed"] = self.stats.get("tool_results_compressed", 0) + 1
                self.stats["original_size"] = self.stats.get("original_size", 0) + original_size
                self.stats["compressed_size"] = self.stats.get("compressed_size", 0) + len(compressed)

        if compressed_count > 0:
            log_info(f"Tool call compression threshold hit. Compressing {compressed_count} tool results")

    def _compress_tool_result(self, tool_msg: Message) -> Optional[str]:
        self.model = get_model(self.model)
        if not self.model:
            log_warning("[Compression] No compression model available")
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
            log_error(f"[Compression] Tool compression failed for '{tool_name or 'unknown'}': {e}")
            return None

    async def _acompress_tool_result(self, tool_msg: Message) -> Optional[str]:
        self.model = get_model(self.model)
        if not self.model:
            log_warning("[Compression] No compression model available")
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
            log_error(f"[Compression] Async tool compression failed for '{tool_name or 'unknown'}': {e}")
            return None

    def _compress_messages(self, messages: List[Message]) -> Optional[str]:
        self.model = get_model(self.model)
        if not self.model:
            log_warning("[Compression] No compression model available")
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
            log_error(f"[Compression] Context compression failed: {e}")
            return None

    async def _acompress_messages(self, messages: List[Message]) -> Optional[str]:
        self.model = get_model(self.model)
        if not self.model:
            log_warning("[Compression] No compression model available")
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
            log_error(f"[Compression] Async context compression failed: {e}")
            return None
