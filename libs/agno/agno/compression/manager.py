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

    # Token limit for compression
    compress_token_limit: Optional[int] = None

    # Tool compression
    compress_tool_results: bool = False
    compress_tool_results_limit: int = 3
    compress_tool_call_instructions: Optional[str] = None

    # Context compression
    compress_context: bool = False
    compress_context_messages_limit: int = 10
    compress_context_instructions: Optional[str] = None

    stats: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if self.compress_tool_results and self.compress_context:
            log_warning("Both tool-based and context-based compression are enabled. Compressing full context.")

    def should_compress(
        self, messages: List[Message], tools: Optional[List] = None, model: Optional[Model] = None
    ) -> bool:
        return self._should_compress_context(messages, tools, model) or self._should_compress_tools(
            messages, tools, model
        )

    async def ashould_compress(
        self, messages: List[Message], tools: Optional[List] = None, model: Optional[Model] = None
    ) -> bool:
        """Async version of should_compress for token counting."""
        return self._should_compress_context(messages, tools, model) or self._should_compress_tools(
            messages, tools, model
        )

    def compress(
        self,
        messages: List[Message],
        tools: Optional[List] = None,
        compressed_context: Optional[CompressedContext] = None,
        model: Optional[Model] = None,
    ) -> Optional[CompressedContext]:
        if self._should_compress_context(messages, tools, model):
            return self._compress_context(messages, compressed_context)
        elif self._should_compress_tools(messages, tools, model):
            self._compress_tools(messages)
        return None

    async def acompress(
        self,
        messages: List[Message],
        tools: Optional[List] = None,
        compressed_context: Optional[CompressedContext] = None,
        model: Optional[Model] = None,
    ) -> Optional[CompressedContext]:
        if self._should_compress_context(messages, tools, model):
            return await self._acompress_context(messages, compressed_context)
        elif self._should_compress_tools(messages, tools, model):
            await self._acompress_tools(messages)
        return None

    def _should_compress_context(
        self, messages: List[Message], tools: Optional[List] = None, model: Optional[Model] = None
    ) -> bool:
        if not self.compress_context:
            return False

        # Use the Agent/Team's model for token counting
        counting_model = model or self.model
        if self.compress_token_limit and counting_model:
            token_count = counting_model.count_tokens(messages, tools, compress_tool_results=self.compress_tool_results)
            return token_count >= self.compress_token_limit
        msg_count = len([m for m in messages if m.role in ("user", "assistant", "tool")])
        return msg_count >= self.compress_context_messages_limit

    def _should_compress_tools(
        self, messages: List[Message], tools: Optional[List] = None, model: Optional[Model] = None
    ) -> bool:
        if not self.compress_tool_results:
            return False

        # Use the Agent/Team's model for token counting
        counting_model = model or self.model
        if self.compress_token_limit and counting_model:
            token_count = counting_model.count_tokens(messages, tools, compress_tool_results=self.compress_tool_results)
            return token_count >= self.compress_token_limit
        uncompressed = sum(1 for m in messages if m.role == "tool" and m.compressed_content is None)
        return uncompressed >= self.compress_tool_results_limit

    def _compress_context(
        self,
        messages: List[Message],
        compressed_context: Optional[CompressedContext] = None,
    ) -> Optional[CompressedContext]:
        if len(messages) < 3:
            return None

        # 1. Find system message (optional)
        system_msg = messages[0] if messages[0].role == "system" else None
        start_idx = 1 if system_msg else 0

        # 2. Find LAST user message (the current run's input)
        last_user_msg = None
        last_user_idx = None
        for i, m in reversed(list(enumerate(messages))):
            if i < start_idx:
                break
            if m.role == "user" and not getattr(m, "from_history", False):
                last_user_msg = m
                last_user_idx = i
                break

        if last_user_msg is None or last_user_idx is None:
            return None

        # 3. Compress ALL messages except system and last user
        msgs_to_compress = [m for i, m in enumerate(messages) if i >= start_idx and i != last_user_idx]

        if len(msgs_to_compress) < 2:
            return None

        # 4. Generate summary
        summary = self._compress_messages(msgs_to_compress)
        if not summary:
            return None

        # 5. Track message IDs - accumulate with existing IDs
        existing_ids = compressed_context.message_ids if compressed_context else set()
        all_ids: Set[str] = set(existing_ids)
        new_ids = {m.id for m in msgs_to_compress}
        all_ids.update(new_ids)

        # 6. Rebuild: [system, summary, last_user]
        # Clean slate - no current work preserved, summary contains everything
        messages.clear()
        if system_msg:
            messages.append(system_msg)
        messages.append(
            Message(
                role="user",
                content=f"Context summary:\n\n{summary}",
                add_to_agent_memory=False,  # Don't store summary in run_response.messages
            )
        )
        messages.append(last_user_msg)

        new_context = CompressedContext(
            content=summary,
            message_ids=all_ids,
            updated_at=datetime.now(),
        )
        log_info(f"Compressed {len(msgs_to_compress)} messages into context summary")
        return new_context

    async def _acompress_context(
        self,
        messages: List[Message],
        compressed_context: Optional[CompressedContext] = None,
    ) -> Optional[CompressedContext]:
        if len(messages) < 3:
            return None

        # 1. Find system message (optional)
        system_msg = messages[0] if messages[0].role == "system" else None
        start_idx = 1 if system_msg else 0

        # 2. Find LAST user message (the current run's input)
        last_user_msg = None
        last_user_idx = None
        for i, m in reversed(list(enumerate(messages))):
            if i < start_idx:
                break
            if m.role == "user" and not getattr(m, "from_history", False):
                last_user_msg = m
                last_user_idx = i
                break

        if last_user_msg is None or last_user_idx is None:
            return None

        # 3. Compress ALL messages except system and last user
        msgs_to_compress = [m for i, m in enumerate(messages) if i >= start_idx and i != last_user_idx]

        # 4. Generate summary
        summary = await self._acompress_messages(msgs_to_compress)
        if not summary:
            return None

        # 5. Track message IDs - accumulate with existing IDs
        existing_ids = compressed_context.message_ids if compressed_context else set()
        all_ids: Set[str] = set(existing_ids)
        new_ids = {m.id for m in msgs_to_compress}
        all_ids.update(new_ids)

        # 6. Rebuild: [system, summary, last_user]
        messages.clear()
        if system_msg:
            messages.append(system_msg)
        messages.append(
            Message(
                role="user",
                content=f"Context summary:\n\n{summary}",
                add_to_agent_memory=False,  # Don't store summary in run_response.messages
            )
        )
        messages.append(last_user_msg)

        new_context = CompressedContext(
            content=summary,
            message_ids=all_ids,
            updated_at=datetime.now(),
        )
        log_info(f"Compressed {len(msgs_to_compress)} messages into context summary")
        return new_context

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
