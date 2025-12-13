import asyncio
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Set, Type, Union

from pydantic import BaseModel

from agno.compression.context import CompressedContext
from agno.compression.prompts import CONTEXT_COMPRESSION_PROMPT, TOOL_COMPRESSION_PROMPT
from agno.models.base import Model
from agno.models.message import Message
from agno.models.utils import get_model
from agno.utils.log import log_debug, log_error, log_info, log_warning


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
        self,
        messages: List[Message],
        tools: Optional[List] = None,
        model: Optional[Model] = None,
        response_format: Optional[Union[Dict, Type[BaseModel]]] = None,
    ) -> bool:
        return self._should_compress_context(messages, tools, model, response_format) or self._should_compress_tools(
            messages, tools, model, response_format
        )

    async def ashould_compress(
        self,
        messages: List[Message],
        tools: Optional[List] = None,
        model: Optional[Model] = None,
        response_format: Optional[Union[Dict, Type[BaseModel]]] = None,
    ) -> bool:
        """Async version of should_compress for token counting."""
        return self._should_compress_context(messages, tools, model, response_format) or self._should_compress_tools(
            messages, tools, model, response_format
        )

    def compress(
        self,
        messages: List[Message],
        tools: Optional[List] = None,
        compressed_context: Optional[CompressedContext] = None,
        model: Optional[Model] = None,
        response_format: Optional[Union[Dict, Type[BaseModel]]] = None,
    ) -> Optional[CompressedContext]:
        if self._should_compress_context(messages, tools, model, response_format):
            return self._compress_context(messages, compressed_context)
        elif self._should_compress_tools(messages, tools, model, response_format):
            self._compress_tools(messages)
        return None

    async def acompress(
        self,
        messages: List[Message],
        tools: Optional[List] = None,
        compressed_context: Optional[CompressedContext] = None,
        model: Optional[Model] = None,
        response_format: Optional[Union[Dict, Type[BaseModel]]] = None,
    ) -> Optional[CompressedContext]:
        if self._should_compress_context(messages, tools, model, response_format):
            return await self._acompress_context(messages, compressed_context)
        elif self._should_compress_tools(messages, tools, model, response_format):
            await self._acompress_tools(messages)
        return None

    def _should_compress_context(
        self,
        messages: List[Message],
        tools: Optional[List] = None,
        model: Optional[Model] = None,
        response_format: Optional[Union[Dict, Type[BaseModel]]] = None,
    ) -> bool:
        if not self.compress_context:
            return False

        # Use the Agent/Team's model for token counting
        counting_model = model or self.model

        # Token-based compression (if limit is set)
        if self.compress_token_limit:
            if counting_model:
                token_count = counting_model.count_tokens(messages, tools, output_schema=response_format)
                if token_count >= self.compress_token_limit:
                    log_info(f"Context compression token limit hit: {token_count} >= {self.compress_token_limit}")
                    return True
            # Token limit is set - only use token-based, don't fall back to message count
            return False

        # Count-based fallback ONLY when no token limit is set
        msg_count = len([m for m in messages if m.role in ("user", "assistant", "tool")])
        return msg_count >= self.compress_context_messages_limit

    def _should_compress_tools(
        self,
        messages: List[Message],
        tools: Optional[List] = None,
        model: Optional[Model] = None,
        response_format: Optional[Union[Dict, Type[BaseModel]]] = None,
    ) -> bool:
        if not self.compress_tool_results:
            return False

        # Use the Agent/Team's model for token counting
        counting_model = model or self.model

        # Token-based compression (if limit is set)
        if self.compress_token_limit:
            if counting_model:
                token_count = counting_model.count_tokens(messages, tools, output_schema=response_format)
                if token_count >= self.compress_token_limit:
                    log_info(f"Tool compression token limit hit: {token_count} >= {self.compress_token_limit}")
                    return True
            # Token limit is set - only use token-based, don't fall back to tool count
            return False

        # Count-based fallback ONLY when no token limit is set
        uncompressed = sum(1 for m in messages if m.role == "tool" and m.compressed_content is None)
        return uncompressed >= self.compress_tool_results_limit

    def _compress_context(
        self,
        messages: List[Message],
        compressed_context: Optional[CompressedContext] = None,
    ) -> Optional[CompressedContext]:
        if len(messages) < 3:
            return None

        self.model = get_model(self.model)
        if not self.model:
            log_warning("No compression model available for context compression")
            return None

        # Collect messages to compress (exclude system messages)
        msgs_to_compress: List[Message] = []
        msg_ids: Set[str] = set()

        for msg in messages:
            if msg.role in ("user", "assistant", "tool"):
                msgs_to_compress.append(msg)
                if msg.id:
                    msg_ids.add(msg.id)

        if not msgs_to_compress:
            return None

        # Build conversation text for compression
        conversation_parts = []
        if compressed_context and compressed_context.content:
            conversation_parts.append(f"Previous context summary:\n{compressed_context.content}\n\n")

        for msg in msgs_to_compress:
            role = msg.role.upper()
            content = msg.compressed_content or msg.content or ""
            if msg.tool_name:
                conversation_parts.append(f"[{role} - {msg.tool_name}]: {content}")
            else:
                conversation_parts.append(f"[{role}]: {content}")

        conversation_text = "\n".join(conversation_parts)
        compression_prompt = self.compress_context_instructions or CONTEXT_COMPRESSION_PROMPT

        try:
            response = self.model.response(
                messages=[
                    Message(role="system", content=compression_prompt),
                    Message(role="user", content=f"Conversation to compress:\n\n{conversation_text}"),
                ]
            )

            if response.content:
                # Merge message IDs
                all_msg_ids = msg_ids
                if compressed_context and compressed_context.message_ids:
                    all_msg_ids = all_msg_ids.union(compressed_context.message_ids)

                new_context = CompressedContext(
                    content=response.content,
                    message_ids=all_msg_ids,
                    updated_at=datetime.now(),
                )

                # Update stats
                original_len = len(conversation_text)
                compressed_len = len(response.content)
                self.stats["context_compressions"] = self.stats.get("context_compressions", 0) + 1
                self.stats["original_context_size"] = self.stats.get("original_context_size", 0) + original_len
                self.stats["compressed_context_size"] = self.stats.get("compressed_context_size", 0) + compressed_len
                self.stats["messages_compressed"] = self.stats.get("messages_compressed", 0) + len(msgs_to_compress)

                log_info(f"Context compressed: {original_len} -> {compressed_len} chars ({len(msgs_to_compress)} msgs)")

                # Inject summary into user message and remove compressed messages
                user_msg_idx = next((i for i, m in enumerate(messages) if m.role == "user"), None)
                log_debug(f"Context compression: user_msg_idx={user_msg_idx}")

                if user_msg_idx is not None:
                    # Find where to start keeping messages (last assistant with tool_calls)
                    keep_from_idx = len(messages)
                    for i in range(len(messages) - 1, -1, -1):
                        if messages[i].role == "assistant" and messages[i].tool_calls:
                            keep_from_idx = i
                            break

                    log_debug(f"Context compression: keep_from_idx={keep_from_idx}, total_messages={len(messages)}")

                    # Only compress if there are messages to remove
                    if keep_from_idx > user_msg_idx + 1:
                        # Log what's being kept
                        kept_roles = [m.role for m in messages[keep_from_idx:]]
                        log_debug(
                            f"Context compression: keeping {len(messages) - keep_from_idx} messages: {kept_roles}"
                        )

                        # Remove compressed messages first
                        removed_count = keep_from_idx - user_msg_idx - 1
                        del messages[user_msg_idx + 1 : keep_from_idx]
                        log_debug(f"Context compression: removed {removed_count} messages")

                        # Insert summary as new user message after original user message
                        summary_msg = Message(role="user", content=f"---\nCOMPLETED:\n{response.content}\n---")
                        messages.insert(user_msg_idx + 1, summary_msg)
                        log_debug(f"Context compression: inserted summary message:\n{response.content}")

                return new_context

        except Exception as e:
            log_error(f"Error compressing context: {e}")

        return None

    async def _acompress_context(
        self,
        messages: List[Message],
        compressed_context: Optional[CompressedContext] = None,
    ) -> Optional[CompressedContext]:
        if len(messages) < 3:
            return None

        self.model = get_model(self.model)
        if not self.model:
            log_warning("No compression model available for context compression")
            return None

        # Collect messages to compress (exclude system messages)
        msgs_to_compress: List[Message] = []
        msg_ids: Set[str] = set()

        for msg in messages:
            if msg.role in ("user", "assistant", "tool"):
                msgs_to_compress.append(msg)
                if msg.id:
                    msg_ids.add(msg.id)

        if not msgs_to_compress:
            return None

        # Build conversation text for compression
        conversation_parts = []
        if compressed_context and compressed_context.content:
            conversation_parts.append(f"Previous context summary:\n{compressed_context.content}\n\n")

        for msg in msgs_to_compress:
            role = msg.role.upper()
            content = msg.compressed_content or msg.content or ""
            if msg.tool_name:
                conversation_parts.append(f"[{role} - {msg.tool_name}]: {content}")
            else:
                conversation_parts.append(f"[{role}]: {content}")

        conversation_text = "\n".join(conversation_parts)
        compression_prompt = self.compress_context_instructions or CONTEXT_COMPRESSION_PROMPT

        try:
            response = await self.model.aresponse(
                messages=[
                    Message(role="system", content=compression_prompt),
                    Message(role="user", content=f"Conversation to compress:\n\n{conversation_text}"),
                ]
            )

            if response.content:
                # Merge message IDs
                all_msg_ids = msg_ids
                if compressed_context and compressed_context.message_ids:
                    all_msg_ids = all_msg_ids.union(compressed_context.message_ids)

                new_context = CompressedContext(
                    content=response.content,
                    message_ids=all_msg_ids,
                    updated_at=datetime.now(),
                )

                # Update stats
                original_len = len(conversation_text)
                compressed_len = len(response.content)
                self.stats["context_compressions"] = self.stats.get("context_compressions", 0) + 1
                self.stats["original_context_size"] = self.stats.get("original_context_size", 0) + original_len
                self.stats["compressed_context_size"] = self.stats.get("compressed_context_size", 0) + compressed_len
                self.stats["messages_compressed"] = self.stats.get("messages_compressed", 0) + len(msgs_to_compress)

                log_info(f"Context compressed: {original_len} -> {compressed_len} chars ({len(msgs_to_compress)} msgs)")

                # Inject summary into user message and remove compressed messages
                user_msg_idx = next((i for i, m in enumerate(messages) if m.role == "user"), None)
                log_debug(f"Context compression: user_msg_idx={user_msg_idx}")

                if user_msg_idx is not None:
                    # Find where to start keeping messages (last assistant with tool_calls)
                    keep_from_idx = len(messages)
                    for i in range(len(messages) - 1, -1, -1):
                        if messages[i].role == "assistant" and messages[i].tool_calls:
                            keep_from_idx = i
                            break

                    log_debug(f"Context compression: keep_from_idx={keep_from_idx}, total_messages={len(messages)}")

                    # Only compress if there are messages to remove
                    if keep_from_idx > user_msg_idx + 1:
                        # Log what's being kept
                        kept_roles = [m.role for m in messages[keep_from_idx:]]
                        log_debug(
                            f"Context compression: keeping {len(messages) - keep_from_idx} messages: {kept_roles}"
                        )

                        # Remove compressed messages first
                        removed_count = keep_from_idx - user_msg_idx - 1
                        del messages[user_msg_idx + 1 : keep_from_idx]
                        log_debug(f"Context compression: removed {removed_count} messages")

                        # Insert summary as new user message after original user message
                        summary_msg = Message(role="user", content=f"---\nCOMPLETED:\n{response.content}\n---")
                        messages.insert(user_msg_idx + 1, summary_msg)
                        log_debug(f"Context compression: inserted summary message:\n{response.content}")

                return new_context

        except Exception as e:
            log_error(f"Error compressing context: {e}")

        return None

    def _compress_tools(self, messages: List[Message]) -> None:
        """Compress uncompressed tool results"""
        uncompressed_tools = [msg for msg in messages if msg.role == "tool" and msg.compressed_content is None]

        if not uncompressed_tools:
            return

        for tool_msg in uncompressed_tools:
            original_len = len(str(tool_msg.content)) if tool_msg.content else 0
            compressed = self._compress_tool_result(tool_msg)
            if compressed:
                tool_msg.compressed_content = compressed
                tool_results_count = len(tool_msg.tool_calls) if tool_msg.tool_calls else 1
                self.stats["tool_results_compressed"] = (
                    self.stats.get("tool_results_compressed", 0) + tool_results_count
                )
                self.stats["original_size"] = self.stats.get("original_size", 0) + original_len
                self.stats["compressed_size"] = self.stats.get("compressed_size", 0) + len(compressed)
            else:
                log_warning(f"Compression failed for {tool_msg.tool_name}")

    def _compress_tool_result(self, tool_result: Message) -> Optional[str]:
        if not tool_result:
            return None

        tool_content = f"Tool: {tool_result.tool_name or 'unknown'}\n{tool_result.content}"

        self.model = get_model(self.model)
        if not self.model:
            log_warning("No compression model available")
            return None

        compression_prompt = self.compress_tool_call_instructions or TOOL_COMPRESSION_PROMPT
        compression_message = "Tool Results to Compress: " + tool_content + "\n"

        try:
            response = self.model.response(
                messages=[
                    Message(role="system", content=compression_prompt),
                    Message(role="user", content=compression_message),
                ]
            )
            return response.content
        except Exception as e:
            log_error(f"Error compressing tool result: {e}")
            return tool_content

    async def _acompress_tools(self, messages: List[Message]) -> None:
        """Async compress uncompressed tool results"""
        uncompressed_tools = [msg for msg in messages if msg.role == "tool" and msg.compressed_content is None]

        if not uncompressed_tools:
            return

        # Track original sizes before compression
        original_sizes = [len(str(msg.content)) if msg.content else 0 for msg in uncompressed_tools]

        # Parallel compression using asyncio.gather
        tasks = [self._acompress_tool_result(msg) for msg in uncompressed_tools]
        results = await asyncio.gather(*tasks)

        # Apply results and track stats
        for msg, compressed, original_len in zip(uncompressed_tools, results, original_sizes):
            if compressed:
                msg.compressed_content = compressed
                tool_results_count = len(msg.tool_calls) if msg.tool_calls else 1
                self.stats["tool_results_compressed"] = (
                    self.stats.get("tool_results_compressed", 0) + tool_results_count
                )
                self.stats["original_size"] = self.stats.get("original_size", 0) + original_len
                self.stats["compressed_size"] = self.stats.get("compressed_size", 0) + len(compressed)
            else:
                log_warning(f"Compression failed for {msg.tool_name}")

    async def _acompress_tool_result(self, tool_result: Message) -> Optional[str]:
        """Async compress a single tool result"""
        if not tool_result:
            return None

        tool_content = f"Tool: {tool_result.tool_name or 'unknown'}\n{tool_result.content}"

        self.model = get_model(self.model)
        if not self.model:
            log_warning("No compression model available")
            return None

        compression_prompt = self.compress_tool_call_instructions or TOOL_COMPRESSION_PROMPT
        compression_message = "Tool Results to Compress: " + tool_content + "\n"

        try:
            response = await self.model.aresponse(
                messages=[
                    Message(role="system", content=compression_prompt),
                    Message(role="user", content=compression_message),
                ]
            )
            return response.content
        except Exception as e:
            log_error(f"Error compressing tool result: {e}")
            return tool_content
