import asyncio
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Set, Tuple, Type, Union

from pydantic import BaseModel

from agno.compression.context import CompressedContext
from agno.compression.prompts import CONTEXT_COMPRESSION_PROMPT, TOOL_COMPRESSION_PROMPT
from agno.models.base import Model
from agno.models.message import Message
from agno.models.utils import get_model
from agno.utils.log import log_error, log_info, log_warning
from agno.utils.tokens import count_text_tokens


@dataclass
class CompressionResult:
    """Result from a compression operation.

    Contains the compression context (if successful) and stats for this single operation.
    Separating stats from accumulated manager state makes the API more predictable.
    """

    context: Optional[CompressedContext]
    stats: Dict[str, Any] = field(default_factory=dict)


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

    # =========================================================================
    # Message Slicing Helpers (Phase 3: Simplify slicing logic)
    # =========================================================================

    def _find_current_user_index(self, messages: List[Message]) -> Optional[int]:
        """Find the latest user message with from_history=False.

        This identifies the "current turn" - the user message that triggered
        the current agent run, as opposed to historical context.
        """
        for i in range(len(messages) - 1, -1, -1):
            msg = messages[i]
            if msg.role == "user" and not msg.from_history:
                return i
        return None

    def _find_last_tool_batch_index(self, messages: List[Message], after_index: int) -> Optional[int]:
        """Find the last assistant message with tool_calls after the given index.

        The "last tool batch" includes this assistant message and all subsequent
        tool result messages. We keep this batch uncompressed because the LLM
        needs to see recent tool interactions to continue reasoning.
        """
        for i in range(len(messages) - 1, after_index, -1):
            msg = messages[i]
            if msg.role == "assistant" and msg.tool_calls:
                return i
        return None

    def _collect_messages_to_compress(
        self,
        messages: List[Message],
        current_user_idx: int,
        last_tool_idx: Optional[int],
        already_compressed_ids: Set[str],
    ) -> Tuple[List[Message], Set[str]]:
        """Collect messages that should be compressed.

        Returns:
            Tuple of (messages_to_compress, new_compressed_message_ids)

        Skips:
            - System messages (always preserved)
            - Current user message (from_history=False)
            - Last tool batch (after current user, if exists)
            - Already-compressed messages (by ID)
        """
        msgs_to_compress: List[Message] = []
        compressed_msg_ids: Set[str] = set()

        for i, msg in enumerate(messages):
            # Skip: system messages, current user message
            if msg.role == "system" or i == current_user_idx:
                continue
            # Skip: last tool batch
            if last_tool_idx is not None and i >= last_tool_idx:
                continue
            # Skip: already compressed in previous runs
            if msg.id and msg.id in already_compressed_ids:
                continue

            msgs_to_compress.append(msg)
            if msg.id:
                compressed_msg_ids.add(msg.id)

        return msgs_to_compress, compressed_msg_ids

    def _build_conversation_text(self, msgs_to_compress: List[Message]) -> str:
        """Build formatted conversation text for the compression LLM."""
        conversation_parts = []
        for msg in msgs_to_compress:
            role = msg.role.upper()
            content = msg.compressed_content or msg.content or ""
            if msg.tool_name:
                conversation_parts.append(f"[{role} - {msg.tool_name}]: {content}")
            else:
                conversation_parts.append(f"[{role}]: {content}")
        return "\n".join(conversation_parts)

    def _build_compression_prompt(
        self,
        conversation_text: str,
        compression_context: Optional[CompressedContext],
    ) -> str:
        """Build the user content for the compression LLM.

        If there's a previous summary, we ask the LLM to merge new facts into it.
        This enables incremental compression across multiple runs.
        """
        if compression_context and compression_context.content:
            return (
                f"Previous summary (merge new facts into this):\n"
                f"{compression_context.content}\n\n"
                f"New conversation to incorporate:\n\n{conversation_text}"
            )
        else:
            return f"Conversation to compress:\n\n{conversation_text}"

    # =========================================================================
    # Context Compression Helpers (Phase 1: Eliminate sync/async duplication)
    # =========================================================================

    def _prepare_compression(
        self,
        messages: List[Message],
        compression_context: Optional[CompressedContext],
    ) -> Optional[Tuple[List[Message], str, Set[str], int, Optional[int]]]:
        """Prepare messages for compression.

        Returns:
            Tuple of (msgs_to_compress, user_content, compressed_msg_ids,
                     current_user_idx, last_tool_idx) if compression should proceed.
            None if there's nothing to compress.
        """
        if len(messages) < 3:
            return None

        # Find current user message
        current_user_idx = self._find_current_user_index(messages)
        if current_user_idx is None:
            return None

        # Find last tool batch after current user
        last_tool_idx = self._find_last_tool_batch_index(messages, current_user_idx)

        # Get already compressed message IDs from previous runs
        already_compressed_ids: Set[str] = set()
        if compression_context and compression_context.message_ids:
            already_compressed_ids = compression_context.message_ids

        # Collect messages to compress
        msgs_to_compress, compressed_msg_ids = self._collect_messages_to_compress(
            messages, current_user_idx, last_tool_idx, already_compressed_ids
        )

        if not msgs_to_compress:
            return None

        # Build conversation text and prompt
        conversation_text = self._build_conversation_text(msgs_to_compress)
        user_content = self._build_compression_prompt(conversation_text, compression_context)

        return (msgs_to_compress, user_content, compressed_msg_ids, current_user_idx, last_tool_idx)

    def _finalize_compression(
        self,
        messages: List[Message],
        response_content: str,
        msgs_to_compress: List[Message],
        compressed_msg_ids: Set[str],
        compression_context: Optional[CompressedContext],
        current_user_idx: int,
        last_tool_idx: Optional[int],
        model_id: str,
    ) -> CompressedContext:
        """Rebuild message list and create new compression context.

        This modifies the messages list in-place (expected by callers) and
        returns the new compression context with merged message IDs.
        """
        # Merge message IDs with previous compressed context
        all_msg_ids = compressed_msg_ids
        if compression_context and compression_context.message_ids:
            all_msg_ids = all_msg_ids.union(compression_context.message_ids)

        new_context = CompressedContext(
            content=response_content,
            message_ids=all_msg_ids,
            updated_at=datetime.now(),
        )

        # Calculate and track token savings
        conversation_text = self._build_conversation_text(msgs_to_compress)
        original_tokens = count_text_tokens(conversation_text, model_id)
        compressed_tokens = count_text_tokens(response_content, model_id)

        self.stats["context_compressions"] = self.stats.get("context_compressions", 0) + 1
        self.stats["messages_compressed"] = self.stats.get("messages_compressed", 0) + len(msgs_to_compress)
        self.stats["original_context_tokens"] = self.stats.get("original_context_tokens", 0) + original_tokens
        self.stats["compression_context_tokens"] = self.stats.get("compression_context_tokens", 0) + compressed_tokens

        log_info(f"Context compressed: {original_tokens} -> {compressed_tokens} tokens ({len(msgs_to_compress)} msgs)")

        # Rebuild message list: system + summary + current_user + last_tool_batch
        new_messages: List[Message] = []

        # Keep system messages
        for msg in messages:
            if msg.role == "system":
                new_messages.append(msg)
            else:
                break

        # Add summary of compressed messages as user message
        summary_content = f"<previous_summary>\n{response_content}\n</previous_summary>"
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

        # Replace messages in place (expected by agent)
        messages[:] = new_messages

        return new_context

    # =========================================================================
    # Public API
    # =========================================================================

    def should_compress(
        self,
        messages: List[Message],
        model: Optional[Model] = None,
        tools: Optional[List] = None,
        response_format: Optional[Union[Dict, Type[BaseModel]]] = None,
    ) -> bool:
        """Check if compression should be triggered based on current settings.

        This is a convenience method to check whether the compression threshold
        has been reached without actually performing compression.

        Args:
            messages: The message list to evaluate.
            model: Optional model for token-based compression checks.
                   Note: Does NOT mutate self.model (Phase 2 fix).
            tools: Optional tools list for token counting.
            response_format: Optional response format for token counting.

        Returns:
            True if compression would be triggered, False otherwise.
        """
        # Use provided model for checking, but don't mutate self.model
        # This is a Phase 2 fix: avoid side effects in a query method
        check_model = model or self.model

        if self.compress_context:
            return self._should_compress_context(messages, tools, response_format, check_model)
        if self.compress_tool_results:
            return self._should_compress_tools(messages, tools, response_format, check_model)
        return False

    async def ashould_compress(
        self,
        messages: List[Message],
        model: Optional[Model] = None,
        tools: Optional[List] = None,
        response_format: Optional[Union[Dict, Type[BaseModel]]] = None,
    ) -> bool:
        """Async check if compression should be triggered.

        The underlying checks are synchronous, but this method provides
        API consistency with the async compression methods.
        """
        return self.should_compress(messages, model, tools, response_format)

    def compress(
        self,
        messages: List[Message],
        tools: Optional[List] = None,
        compression_context: Optional[CompressedContext] = None,
        response_format: Optional[Union[Dict, Type[BaseModel]]] = None,
    ) -> Optional[CompressedContext]:
        # Use self.model for checking (already set by agent)
        if self.compress_context and self._should_compress_context(messages, tools, response_format, self.model):
            return self._compress_context(messages, compression_context)

        if self.compress_tool_results and self._should_compress_tools(messages, tools, response_format, self.model):
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
        # Use self.model for checking (already set by agent)
        if self.compress_context and self._should_compress_context(messages, tools, response_format, self.model):
            return await self._acompress_context(messages, compression_context)

        if self.compress_tool_results and self._should_compress_tools(messages, tools, response_format, self.model):
            await self._acompress_tools(messages)
            return None

        return None

    # =========================================================================
    # Internal: Compression Checks
    # =========================================================================

    def _should_compress_context(
        self,
        messages: List[Message],
        tools: Optional[List] = None,
        response_format: Optional[Union[Dict, Type[BaseModel]]] = None,
        model: Optional[Model] = None,
    ) -> bool:
        """Check if context compression should be triggered based on limits."""
        # Token-based compression
        if self.compress_token_limit:
            if model:
                token_count = model.count_tokens(messages, tools, output_schema=response_format)
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
        model: Optional[Model] = None,
    ) -> bool:
        """Check if tool compression should be triggered based on limits."""
        # Token-based compression
        if self.compress_token_limit:
            if model:
                token_count = model.count_tokens(messages, tools, output_schema=response_format)
                if token_count >= self.compress_token_limit:
                    return True
            return False

        # Count-based compression
        if self.compress_tool_results_limit is not None:
            uncompressed = sum(1 for m in messages if m.role == "tool" and m.compressed_content is None)
            return uncompressed >= self.compress_tool_results_limit

        return False

    # =========================================================================
    # Internal: Context Compression (sync/async only differ in model call)
    # =========================================================================

    def _compress_context(
        self,
        messages: List[Message],
        compression_context: Optional[CompressedContext] = None,
    ) -> Optional[CompressedContext]:
        """Synchronous context compression."""
        # Ensure we have a model
        self.model = get_model(self.model)
        if not self.model:
            log_warning("No compression model available for context compression")
            return None

        # Prepare compression (shared logic)
        prep = self._prepare_compression(messages, compression_context)
        if not prep:
            return None

        msgs_to_compress, user_content, compressed_msg_ids, current_user_idx, last_tool_idx = prep

        # Save original messages for rollback on failure
        original_messages = messages.copy()
        compression_prompt = self.compress_context_instructions or CONTEXT_COMPRESSION_PROMPT

        try:
            # Only difference from async: sync model call
            response = self.model.response(
                messages=[
                    Message(role="system", content=compression_prompt),
                    Message(role="user", content=user_content),
                ]
            )

            if not response.content:
                return None

            # Finalize compression (shared logic)
            return self._finalize_compression(
                messages,
                response.content,
                msgs_to_compress,
                compressed_msg_ids,
                compression_context,
                current_user_idx,
                last_tool_idx,
                self.model.id,
            )

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
        """Asynchronous context compression."""
        # Ensure we have a model
        self.model = get_model(self.model)
        if not self.model:
            log_warning("No compression model available for context compression")
            return None

        # Prepare compression (shared logic)
        prep = self._prepare_compression(messages, compression_context)
        if not prep:
            return None

        msgs_to_compress, user_content, compressed_msg_ids, current_user_idx, last_tool_idx = prep

        # Save original messages for rollback on failure
        original_messages = messages.copy()
        compression_prompt = self.compress_context_instructions or CONTEXT_COMPRESSION_PROMPT

        try:
            # Only difference from sync: async model call
            response = await self.model.aresponse(
                messages=[
                    Message(role="system", content=compression_prompt),
                    Message(role="user", content=user_content),
                ]
            )

            if not response.content:
                return None

            # Finalize compression (shared logic)
            return self._finalize_compression(
                messages,
                response.content,
                msgs_to_compress,
                compressed_msg_ids,
                compression_context,
                current_user_idx,
                last_tool_idx,
                self.model.id,
            )

        except Exception as e:
            log_error(f"Error compressing context: {e}")
            # Restore original messages on failure
            messages[:] = original_messages
            return None

    # =========================================================================
    # Internal: Tool Compression
    # =========================================================================

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
