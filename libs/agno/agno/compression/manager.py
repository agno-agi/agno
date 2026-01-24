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
from agno.utils.log import log_error, log_info, log_warning
from agno.utils.tokens import count_text_tokens


@dataclass
class CompressionManager:
    model: Optional[Model] = None

    # Token limit for compression
    compress_token_limit: Optional[int] = None

    # Tool compression
    compress_tool_results: bool = False
    compress_tool_results_limit: Optional[int] = None
    compress_tool_call_instructions: Optional[str] = None

    # Context compression
    compress_context: bool = False
    compress_context_messages_limit: Optional[int] = None
    compress_context_instructions: Optional[str] = None

    stats: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if self.compress_token_limit is None:
            # Set default limit to 3 if only compress_tool_results = True
            if self.compress_tool_results and self.compress_tool_results_limit is None:
                self.compress_tool_results_limit = 3
            # Set default limit to 10 if only compress_context = True
            if self.compress_context and self.compress_context_messages_limit is None:
                self.compress_context_messages_limit = 10

        if not (self.compress_tool_results or self.compress_context):
            log_warning(
                "No compression strategy is enabled. Please set compress_tool_results=True or compress_context=True."
            )

        if self.compress_tool_results and self.compress_context:
            log_warning(
                "Cannot enable `compress_tool_results` and `compress_context` simultaneously. Defaulting to `compress_context`."
            )

    def compress(
        self,
        messages: List[Message],
        tools: Optional[List] = None,
        compression_context: Optional[CompressedContext] = None,
        response_format: Optional[Union[Dict, Type[BaseModel]]] = None,
    ) -> Optional[CompressedContext]:
        if self.compress_context and self._should_compress_context(messages, tools, response_format):
            return self._compress_context(messages, compression_context)

        if self.compress_tool_results and self._should_compress_tools(messages, tools, response_format):
            self._compress_tools(messages)
            return None

        return None

    async def acompress(
        self,
        messages: List[Message],
        tools: Optional[List] = None,
        compression_context: Optional[CompressedContext] = None,
        response_format: Optional[Union[Dict, Type[BaseModel]]] = None,
    ) -> Optional[CompressedContext]:
        if self.compress_context and self._should_compress_context(messages, tools, response_format):
            return await self._acompress_context(messages, compression_context)

        if self.compress_tool_results and self._should_compress_tools(messages, tools, response_format):
            await self._acompress_tools(messages)
            return None

        return None

    def _should_compress_context(
        self,
        messages: List[Message],
        tools: Optional[List] = None,
        response_format: Optional[Union[Dict, Type[BaseModel]]] = None,
    ) -> bool:
        """Check if context compression should be triggered based on limits."""
        # Token-based compression
        if self.compress_token_limit:
            if self.model:
                token_count = self.model.count_tokens(messages, tools, output_schema=response_format)
                if token_count >= self.compress_token_limit:
                    return True
            return False

        # Message count-based compression (excludes system messages)
        if self.compress_context_messages_limit is not None:
            msg_count = len([m for m in messages if m.role != "system"])
            return msg_count >= self.compress_context_messages_limit

        return False

    def _should_compress_tools(
        self,
        messages: List[Message],
        tools: Optional[List] = None,
        response_format: Optional[Union[Dict, Type[BaseModel]]] = None,
    ) -> bool:
        """Check if tool compression should be triggered based on limits."""
        # Token-based compression
        if self.compress_token_limit:
            if self.model:
                token_count = self.model.count_tokens(messages, tools, output_schema=response_format)
                if token_count >= self.compress_token_limit:
                    return True
            return False

        # Count-based compression
        if self.compress_tool_results_limit is not None:
            uncompressed = sum(1 for m in messages if m.role == "tool" and m.compressed_content is None)
            return uncompressed >= self.compress_tool_results_limit

        return False

    def _compress_context(
        self,
        messages: List[Message],
        compression_context: Optional[CompressedContext] = None,
    ) -> Optional[CompressedContext]:
        if len(messages) < 3:
            return None

        self.model = get_model(self.model)
        if not self.model:
            log_warning("No compression model available for context compression")
            return None

        # Save original messages for rollback on failure
        original_messages = messages.copy()

        # 1. Find current user (latest user message with from_history=False)
        current_user_idx: Optional[int] = None
        for i in range(len(messages) - 1, -1, -1):
            msg = messages[i]
            if msg.role == "user" and not msg.from_history:
                current_user_idx = i
                break

        if current_user_idx is None:
            return None

        # 2. Find last tool batch (only after current user)
        last_tool_idx: Optional[int] = None
        for i in range(len(messages) - 1, current_user_idx, -1):
            msg = messages[i]
            if msg.role == "assistant" and msg.tool_calls:
                last_tool_idx = i
                break

        # Get already compressed message IDs from previous runs
        already_compressed_ids: Set[str] = set()
        if compression_context and compression_context.message_ids:
            already_compressed_ids = compression_context.message_ids

        # 3. Collect messages to compress (everything except system, current_user, last_tool_batch, and already-compressed)
        msgs_to_compress: List[Message] = []
        compressed_msg_ids: Set[str] = set()

        for i, msg in enumerate(messages):
            # Skip: system messages, current user message, last tool batch
            if msg.role == "system" or i == current_user_idx:
                continue
            if last_tool_idx is not None and i >= last_tool_idx:
                continue
            # Skip messages that were already compressed in previous runs
            if msg.id and msg.id in already_compressed_ids:
                continue

            msgs_to_compress.append(msg)
            if msg.id:
                compressed_msg_ids.add(msg.id)

        if not msgs_to_compress:
            return None

        # 4. Build conversation text for LLM
        conversation_parts = []
        for msg in msgs_to_compress:
            role = msg.role.upper()
            content = msg.compressed_content or msg.content or ""
            if msg.tool_name:
                conversation_parts.append(f"[{role} - {msg.tool_name}]: {content}")
            else:
                conversation_parts.append(f"[{role}]: {content}")

        conversation_text = "\n".join(conversation_parts)
        compression_prompt = self.compress_context_instructions or CONTEXT_COMPRESSION_PROMPT

        # Build user content - include previous summary for incremental compression
        if compression_context and compression_context.content:
            user_content = (
                f"Previous summary (merge new facts into this):\n"
                f"{compression_context.content}\n\n"
                f"New conversation to incorporate:\n\n{conversation_text}"
            )
        else:
            user_content = f"Conversation to compress:\n\n{conversation_text}"

        # Generate a new combined summary from: previous summary + new messages
        try:
            response = self.model.response(
                messages=[
                    Message(role="system", content=compression_prompt),
                    Message(role="user", content=user_content),
                ]
            )

            if not response.content:
                return None

            # Merge message IDs with previous compressed context
            all_msg_ids = compressed_msg_ids
            if compression_context and compression_context.message_ids:
                all_msg_ids = all_msg_ids.union(compression_context.message_ids)

            new_context = CompressedContext(
                content=response.content,
                message_ids=all_msg_ids,
                updated_at=datetime.now(),
            )

            # Calculate and track token savings
            original_tokens = count_text_tokens(conversation_text, self.model.id)
            compressed_tokens = count_text_tokens(response.content, self.model.id)

            self.stats["context_compressions"] = self.stats.get("context_compressions", 0) + 1
            self.stats["messages_compressed"] = self.stats.get("messages_compressed", 0) + len(msgs_to_compress)
            self.stats["original_context_tokens"] = self.stats.get("original_context_tokens", 0) + original_tokens
            self.stats["compression_context_tokens"] = (
                self.stats.get("compression_context_tokens", 0) + compressed_tokens
            )

            log_info(
                f"Context compressed: {original_tokens} -> {compressed_tokens} tokens ({len(msgs_to_compress)} msgs)"
            )

            # 6. Rebuild message list: system + summary + current_user + last_tool_batch
            new_messages: List[Message] = []

            # Keep system messages
            for msg in messages:
                if msg.role == "system":
                    new_messages.append(msg)
                else:
                    break

            # Add summary of compressed messages as user message
            summary_content = f"<previous_summary>\n{response.content}\n</previous_summary>"
            summary_msg = Message(
                role="user",
                content=summary_content,
                add_to_agent_memory=True,
            )
            new_messages.append(summary_msg)

            # Add current user
            new_messages.append(messages[current_user_idx])

            # Add last tool batch (if exists)
            if last_tool_idx is not None:
                new_messages.extend(messages[last_tool_idx:])

            # Replace messages in place
            messages[:] = new_messages

            return new_context

        except Exception as e:
            log_error(f"Error compressing context: {e}")
            # Restore original messages on failure
            messages[:] = original_messages

        return None

    async def _acompress_context(
        self,
        messages: List[Message],
        compression_context: Optional[CompressedContext] = None,
    ) -> Optional[CompressedContext]:
        if len(messages) < 3:
            return None

        self.model = get_model(self.model)
        if not self.model:
            log_warning("No compression model available for context compression")
            return None

        # Save original messages for rollback on failure
        original_messages = messages.copy()

        # 1. Find current user (latest user message with from_history=False)
        current_user_idx: Optional[int] = None
        for i in range(len(messages) - 1, -1, -1):
            msg = messages[i]
            if msg.role == "user" and not msg.from_history:
                current_user_idx = i
                break

        if current_user_idx is None:
            return None

        # 2. Find last tool batch (only after current user)
        last_tool_idx: Optional[int] = None
        for i in range(len(messages) - 1, current_user_idx, -1):
            msg = messages[i]
            if msg.role == "assistant" and msg.tool_calls:
                last_tool_idx = i
                break

        # Get already compressed message IDs from previous runs
        already_compressed_ids: Set[str] = set()
        if compression_context and compression_context.message_ids:
            already_compressed_ids = compression_context.message_ids

        # 3. Collect messages to compress (skip already-compressed)
        msgs_to_compress: List[Message] = []
        compressed_msg_ids: Set[str] = set()

        for i, msg in enumerate(messages):
            # Skip: system messages, current user message, last tool batch
            if msg.role == "system" or i == current_user_idx:
                continue
            if last_tool_idx is not None and i >= last_tool_idx:
                continue
            # Skip messages that were already compressed in previous runs
            if msg.id and msg.id in already_compressed_ids:
                continue

            msgs_to_compress.append(msg)
            if msg.id:
                compressed_msg_ids.add(msg.id)

        if not msgs_to_compress:
            return None

        # 4. Build conversation text for LLM
        conversation_parts = []
        for msg in msgs_to_compress:
            role = msg.role.upper()
            content = msg.compressed_content or msg.content or ""
            if msg.tool_name:
                conversation_parts.append(f"[{role} - {msg.tool_name}]: {content}")
            else:
                conversation_parts.append(f"[{role}]: {content}")

        conversation_text = "\n".join(conversation_parts)
        compression_prompt = self.compress_context_instructions or CONTEXT_COMPRESSION_PROMPT

        # Build user content - include previous summary for incremental compression
        if compression_context and compression_context.content:
            user_content = (
                f"Previous summary (merge new facts into this):\n"
                f"{compression_context.content}\n\n"
                f"New conversation to incorporate:\n\n{conversation_text}"
            )
        else:
            user_content = f"Conversation to compress:\n\n{conversation_text}"

        # Generate summary: previous summary + new messages
        try:
            response = await self.model.aresponse(
                messages=[
                    Message(role="system", content=compression_prompt),
                    Message(role="user", content=user_content),
                ]
            )

            if not response.content:
                return None

            # Merge message IDs with previous compressed context
            all_msg_ids = compressed_msg_ids
            if compression_context and compression_context.message_ids:
                all_msg_ids = all_msg_ids.union(compression_context.message_ids)

            new_context = CompressedContext(
                content=response.content,
                message_ids=all_msg_ids,
                updated_at=datetime.now(),
            )

            # Calculate and track token savings
            original_tokens = count_text_tokens(conversation_text, self.model.id)
            compressed_tokens = count_text_tokens(response.content, self.model.id)

            self.stats["context_compressions"] = self.stats.get("context_compressions", 0) + 1
            self.stats["messages_compressed"] = self.stats.get("messages_compressed", 0) + len(msgs_to_compress)
            self.stats["original_context_tokens"] = self.stats.get("original_context_tokens", 0) + original_tokens
            self.stats["compression_context_tokens"] = (
                self.stats.get("compression_context_tokens", 0) + compressed_tokens
            )

            log_info(
                f"Context compressed: {original_tokens} -> {compressed_tokens} tokens ({len(msgs_to_compress)} msgs)"
            )

            # 6. Rebuild message list: system + summary + current_user + last_tool_batch
            new_messages: List[Message] = []

            # Keep system messages
            for msg in messages:
                if msg.role == "system":
                    new_messages.append(msg)
                else:
                    break

            # Add summary as user message (provides context to LLM)
            summary_content = f"<previous_summary>\n{response.content}\n</previous_summary>"
            new_messages.append(
                Message(
                    role="user",
                    content=summary_content,
                    add_to_agent_memory=True,
                )
            )

            # Add current user
            new_messages.append(messages[current_user_idx])

            # Add last tool batch (if exists)
            if last_tool_idx is not None:
                new_messages.extend(messages[last_tool_idx:])

            # Replace messages in place
            messages[:] = new_messages

            return new_context

        except Exception as e:
            log_error(f"Error compressing context: {e}")
            # Restore original messages on failure
            messages[:] = original_messages

        return None

    def _compress_tools(self, messages: List[Message]) -> None:
        uncompressed_tools = [msg for msg in messages if msg.role == "tool" and msg.compressed_content is None]

        if not uncompressed_tools:
            return

        log_info(f"Compressing {len(uncompressed_tools)} tool results")
        self.stats["tool_compressions"] = self.stats.get("tool_compressions", 0) + 1

        for tool_msg in uncompressed_tools:
            original_content = str(tool_msg.content) if tool_msg.content else ""
            compressed = self._compress_tool_result(tool_msg)

            if compressed and self.model:
                tool_msg.compressed_content = compressed
                tool_results_count = len(tool_msg.tool_calls) if tool_msg.tool_calls else 1
                self.stats["tool_results_compressed"] = (
                    self.stats.get("tool_results_compressed", 0) + tool_results_count
                )
                # Track tokens
                original_tokens = count_text_tokens(original_content, self.model.id)
                compressed_tokens = count_text_tokens(compressed, self.model.id)

                self.stats["original_tool_tokens"] = self.stats.get("original_tool_tokens", 0) + original_tokens
                self.stats["compressed_tool_tokens"] = self.stats.get("compressed_tool_tokens", 0) + compressed_tokens
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
        uncompressed_tools = [msg for msg in messages if msg.role == "tool" and msg.compressed_content is None]

        if not uncompressed_tools:
            return

        log_info(f"Compressing {len(uncompressed_tools)} tool results")
        self.stats["tool_compressions"] = self.stats.get("tool_compressions", 0) + 1

        # Track original content before compression
        original_contents = [str(msg.content) if msg.content else "" for msg in uncompressed_tools]

        # Parallel compression using asyncio.gather
        tasks = [self._acompress_tool_result(msg) for msg in uncompressed_tools]
        results = await asyncio.gather(*tasks)

        # Apply results and track stats
        for msg, compressed, original_content in zip(uncompressed_tools, results, original_contents):
            if compressed and self.model:
                msg.compressed_content = compressed
                tool_results_count = len(msg.tool_calls) if msg.tool_calls else 1
                self.stats["tool_results_compressed"] = (
                    self.stats.get("tool_results_compressed", 0) + tool_results_count
                )
                # Track tokens
                original_tokens = count_text_tokens(original_content, self.model.id)
                compressed_tokens = count_text_tokens(compressed, self.model.id)

                self.stats["original_tool_tokens"] = self.stats.get("original_tool_tokens", 0) + original_tokens
                self.stats["compressed_tool_tokens"] = self.stats.get("compressed_tool_tokens", 0) + compressed_tokens
            else:
                log_warning(f"Compression failed for {msg.tool_name}")

    async def _acompress_tool_result(self, tool_result: Message) -> Optional[str]:
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
