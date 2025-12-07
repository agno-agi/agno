import asyncio
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Set

from agno.compression.context import CompressedContext
from agno.compression.prompts import CONTEXT_COMPRESSION_PROMPT, TOOL_COMPRESSION_PROMPT
from agno.models.base import Model
from agno.models.message import Message
from agno.models.utils import get_model
from agno.utils.log import log_debug, log_error, log_info, log_warning


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
        log_debug(f"[Compression] Checking if compression needed for {len(messages)} messages")

        # Context compression takes priority
        if self.compress_context and self.compress_context_token_limit and self.model:
            tokens = self.model.count_tokens(messages, tools)
            log_debug(f"[Compression] Context tokens: {tokens}, limit: {self.compress_context_token_limit}")
            if tokens >= self.compress_context_token_limit:
                log_debug(f"[Compression] Context token limit exceeded - will compress context")
                return True

        # Tool compression
        if self.compress_tool_results:
            if self.compress_tool_results_token_limit and self.model:
                tokens = self.model.count_tokens(messages, tools)
                log_debug(f"[Compression] Tool tokens: {tokens}, limit: {self.compress_tool_results_token_limit}")
                if tokens >= self.compress_tool_results_token_limit:
                    log_debug(f"[Compression] Tool token limit exceeded - will compress tools")
                    return True
            else:
                uncompressed = sum(1 for m in messages if m.role == "tool" and m.compressed_content is None)
                log_debug(
                    f"[Compression] Uncompressed tool messages: {uncompressed}, limit: {self.compress_tool_results_limit}"
                )
                if uncompressed >= self.compress_tool_results_limit:
                    log_debug(f"[Compression] Tool count limit exceeded - will compress tools")
                    return True

        log_debug("[Compression] No compression needed")
        return False

    def compress(self, messages: List[Message], tools: Optional[List] = None) -> None:
        if self._should_compress_context(messages, tools):
            log_debug("[Compression] Triggering context compression")
            self._compress_context(messages)
        elif self._should_compress_tools(messages, tools):
            log_debug("[Compression] Triggering tool compression")
            self._compress_tools(messages)

    async def acompress(self, messages: List[Message], tools: Optional[List] = None) -> None:
        if self._should_compress_context(messages, tools):
            log_debug("[Compression] Triggering async context compression")
            await self._acompress_context(messages)
        elif self._should_compress_tools(messages, tools):
            log_debug("[Compression] Triggering async tool compression")
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
        log_debug(f"[Compression] Starting context compression with {len(messages)} messages")

        if len(messages) < 2:
            log_debug("[Compression] Not enough messages to compress (< 2)")
            return

        system_msg = messages[0] if messages[0].role == "system" else None
        if not system_msg:
            log_debug("[Compression] No system message found, skipping compression")
            return

        # Find last user message
        latest_user = next((m for m in reversed(messages) if m.role == "user"), None)
        if not latest_user:
            log_debug("[Compression] No user message found, skipping compression")
            return

        # Compress everything except system and latest user
        msgs_to_compress = [m for m in messages if m is not system_msg and m is not latest_user]
        if not msgs_to_compress:
            log_debug("[Compression] No messages to compress after excluding system and latest user")
            return

        log_debug(f"[Compression] Compressing {len(msgs_to_compress)} messages (excluding system and latest user)")

        # Log message roles being compressed
        role_counts = {}
        for m in msgs_to_compress:
            role_counts[m.role] = role_counts.get(m.role, 0) + 1
        log_debug(f"[Compression] Message roles to compress: {role_counts}")

        summary = self._compress_messages(msgs_to_compress)
        if not summary:
            log_debug("[Compression] Compression returned no summary")
            return

        # Track message IDs
        existing_count = len(self.existing_compressed_ids) if self.existing_compressed_ids else 0
        all_ids: Set[str] = set(self.existing_compressed_ids or set())
        new_ids = {m.id for m in msgs_to_compress}
        all_ids.update(new_ids)

        log_debug(f"[Compression] Tracking IDs: {existing_count} existing + {len(new_ids)} new = {len(all_ids)} total")

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
        log_debug(f"[Compression] Context compressed: {len(msgs_to_compress)} messages -> {len(summary)} chars summary")
        log_info(f"Compressed {len(msgs_to_compress)} messages")

    async def _acompress_context(self, messages: List[Message]) -> None:
        log_debug(f"[Compression] Starting async context compression with {len(messages)} messages")

        if len(messages) < 2:
            log_debug("[Compression] Not enough messages to compress (< 2)")
            return

        system_msg = messages[0] if messages[0].role == "system" else None
        if not system_msg:
            log_debug("[Compression] No system message found, skipping compression")
            return

        # Find last user message
        latest_user = next((m for m in reversed(messages) if m.role == "user"), None)
        if not latest_user:
            log_debug("[Compression] No user message found, skipping compression")
            return

        # Compress everything except system and latest user
        msgs_to_compress = [m for m in messages if m is not system_msg and m is not latest_user]
        if not msgs_to_compress:
            log_debug("[Compression] No messages to compress after excluding system and latest user")
            return

        log_debug(f"[Compression] Compressing {len(msgs_to_compress)} messages (excluding system and latest user)")

        # Log message roles being compressed
        role_counts = {}
        for m in msgs_to_compress:
            role_counts[m.role] = role_counts.get(m.role, 0) + 1
        log_debug(f"[Compression] Message roles to compress: {role_counts}")

        summary = await self._acompress_messages(msgs_to_compress)
        if not summary:
            log_debug("[Compression] Compression returned no summary")
            return

        # Track message IDs
        existing_count = len(self.existing_compressed_ids) if self.existing_compressed_ids else 0
        all_ids: Set[str] = set(self.existing_compressed_ids or set())
        new_ids = {m.id for m in msgs_to_compress}
        all_ids.update(new_ids)

        log_debug(f"[Compression] Tracking IDs: {existing_count} existing + {len(new_ids)} new = {len(all_ids)} total")

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
        log_debug(f"[Compression] Context compressed: {len(msgs_to_compress)} messages -> {len(summary)} chars summary")
        log_info(f"Compressed {len(msgs_to_compress)} messages")

    def _compress_tools(self, messages: List[Message]) -> None:
        uncompressed = [m for m in messages if m.role == "tool" and m.compressed_content is None]
        log_debug(f"[Compression] Compressing {len(uncompressed)} tool results")

        compressed_count = 0
        for msg in uncompressed:
            compressed = self._compress_tool_result(msg)
            if compressed:
                msg.compressed_content = compressed
                compressed_count += 1

        log_debug(f"[Compression] Successfully compressed {compressed_count}/{len(uncompressed)} tool results")

    async def _acompress_tools(self, messages: List[Message]) -> None:
        uncompressed = [m for m in messages if m.role == "tool" and m.compressed_content is None]
        if not uncompressed:
            log_debug("[Compression] No uncompressed tool results to process")
            return

        log_debug(f"[Compression] Async compressing {len(uncompressed)} tool results")
        results = await asyncio.gather(*[self._acompress_tool_result(m) for m in uncompressed])

        compressed_count = 0
        for msg, compressed in zip(uncompressed, results):
            if compressed:
                msg.compressed_content = compressed
                compressed_count += 1

        log_debug(f"[Compression] Successfully compressed {compressed_count}/{len(uncompressed)} tool results")

    def _compress_tool_result(self, tool_msg: Message) -> Optional[str]:
        self.model = get_model(self.model)
        if not self.model:
            log_warning("[Compression] No compression model available")
            return None

        tool_name = tool_msg.tool_name
        if not tool_name and tool_msg.tool_calls:
            names = [str(tc.get("tool_name")) for tc in tool_msg.tool_calls if tc.get("tool_name")]
            tool_name = ", ".join(names) if names else None

        original_size = len(str(tool_msg.content)) if tool_msg.content else 0
        log_debug(f"[Compression] Compressing tool '{tool_name or 'unknown'}': {original_size} chars")

        content = f"Tool: {tool_name or 'unknown'}\n{tool_msg.content}"
        prompt = self.compress_tool_call_instructions or TOOL_COMPRESSION_PROMPT

        try:
            response = self.model.response(
                messages=[
                    Message(role="system", content=prompt),
                    Message(role="user", content=f"Compress:\n{content}"),
                ]
            )
            compressed_size = len(response.content) if response.content else 0
            reduction = ((original_size - compressed_size) / original_size * 100) if original_size > 0 else 0
            log_debug(
                f"[Compression] Tool '{tool_name or 'unknown'}': {original_size} -> {compressed_size} chars ({reduction:.1f}% reduction)"
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

        original_size = len(str(tool_msg.content)) if tool_msg.content else 0
        log_debug(f"[Compression] Async compressing tool '{tool_name or 'unknown'}': {original_size} chars")

        content = f"Tool: {tool_name or 'unknown'}\n{tool_msg.content}"
        prompt = self.compress_tool_call_instructions or TOOL_COMPRESSION_PROMPT

        try:
            response = await self.model.aresponse(
                messages=[
                    Message(role="system", content=prompt),
                    Message(role="user", content=f"Compress:\n{content}"),
                ]
            )
            compressed_size = len(response.content) if response.content else 0
            reduction = ((original_size - compressed_size) / original_size * 100) if original_size > 0 else 0
            log_debug(
                f"[Compression] Tool '{tool_name or 'unknown'}': {original_size} -> {compressed_size} chars ({reduction:.1f}% reduction)"
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

        original_size = len(conversation)
        log_debug(f"[Compression] Compressing conversation: {len(messages)} messages, {original_size} chars")

        prompt = self.compress_context_instructions or CONTEXT_COMPRESSION_PROMPT
        try:
            response = self.model.response(
                messages=[
                    Message(role="system", content=prompt),
                    Message(role="user", content=f"Compress:\n\n{conversation}"),
                ]
            )
            compressed_size = len(response.content) if response.content else 0
            reduction = ((original_size - compressed_size) / original_size * 100) if original_size > 0 else 0
            log_debug(
                f"[Compression] Conversation compressed: {original_size} -> {compressed_size} chars ({reduction:.1f}% reduction)"
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

        original_size = len(conversation)
        log_debug(f"[Compression] Async compressing conversation: {len(messages)} messages, {original_size} chars")

        prompt = self.compress_context_instructions or CONTEXT_COMPRESSION_PROMPT
        try:
            response = await self.model.aresponse(
                messages=[
                    Message(role="system", content=prompt),
                    Message(role="user", content=f"Compress:\n\n{conversation}"),
                ]
            )
            compressed_size = len(response.content) if response.content else 0
            reduction = ((original_size - compressed_size) / original_size * 100) if original_size > 0 else 0
            log_debug(
                f"[Compression] Conversation compressed: {original_size} -> {compressed_size} chars ({reduction:.1f}% reduction)"
            )
            return response.content
        except Exception as e:
            log_error(f"[Compression] Async context compression failed: {e}")
            return None
