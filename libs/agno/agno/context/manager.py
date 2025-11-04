from dataclasses import dataclass
from textwrap import dedent
from typing import TYPE_CHECKING, List, Optional

from agno.models.message import Message
from agno.models.utils import get_model
from agno.utils.log import log_debug, log_info

if TYPE_CHECKING:
    from agno.models.base import Model


@dataclass
class ContextManager:
    model: Optional["Model"] = None
    tool_compression_threshold: int = 3
    tool_compression_instructions: Optional[str] = None

    compression_count: int = 0

    def should_compress(self, messages: List[Message]) -> bool:
        tool_count = len([m for m in messages if m.role == "tool"])
        return tool_count > self.tool_compression_threshold

    def _get_compression_prompt(self) -> str:
        if self.tool_compression_instructions:
            return self.tool_compression_instructions

        return dedent(
            """\
            You are compressing tool call results to reduce context size while preserving critical information.
            
            Your task: Extract and consolidate key information from multiple tool results.
            
            MUST PRESERVE:
            - Specific facts, numbers, statistics, percentages
            - Dates, times, and temporal information
            - Names of people, companies, products, locations
            - Important entities and their relationships
            - Actionable insights and conclusions
            - Direct quotes (if relevant)
            
            MUST REMOVE:
            - Verbose explanations and background information
            - Redundant or repeated information across results
            - Formatting artifacts (markdown, HTML, etc.)
            - Filler words and unnecessary context
            
            OUTPUT FORMAT:
            - Concise, factual statements
            - Organized by topic or tool type if multiple tools used
            - Maximum density of useful information
            - Keep it under 300 words total
            
            Be extremely concise while retaining ALL critical data points."""
        )

    def _compress_with_llm(self, old_tool_results: List[Message]) -> Optional[str]:
        """Compress tool results using LLM.

        Args:
            old_tool_results: List of tool result messages to compress

        Returns:
            Compressed summary string, or None if compression fails/unavailable
        """
        if not old_tool_results:
            return None

        # Build compression input
        tool_results_text = []
        for i, msg in enumerate(old_tool_results, 1):
            tool_name = msg.tool_name or "unknown_tool"
            content = str(msg.content) if msg.content else "(empty)"
            tool_results_text.append(f"Tool {i}: {tool_name}\nResult:\n{content}\n")

        compression_input = "\n---\n".join(tool_results_text)

        # Call compression model
        self.model = get_model(self.model)
        if not self.model:
            return None

        try:
            log_debug(f"   Calling compression model to summarize {len(old_tool_results)} tool results")
            compression_messages = [
                Message(role="system", content=self._get_compression_prompt()),
                Message(role="user", content=compression_input),
            ]

            response = self.model.response(messages=compression_messages)
            compressed_content = response.content if response.content else None

            if compressed_content:
                log_debug(f"   Generated compressed summary ({len(str(compressed_content))} chars)")

            return compressed_content
        except Exception as e:
            log_debug(f"   Compression model call failed: {e}")
            return None

    async def _acompress_with_llm(self, old_tool_results: List[Message]) -> Optional[str]:
        """Async version: Compress tool results using LLM.

        Args:
            old_tool_results: List of tool result messages to compress

        Returns:
            Compressed summary string, or None if compression fails/unavailable
        """
        if not old_tool_results:
            return None

        # Build compression input
        tool_results_text = []
        for i, msg in enumerate(old_tool_results, 1):
            tool_name = msg.tool_name or "unknown_tool"
            content = str(msg.content) if msg.content else "(empty)"
            tool_results_text.append(f"Tool {i}: {tool_name}\nResult:\n{content}\n")

        compression_input = "\n---\n".join(tool_results_text)

        # Call compression model
        self.model = get_model(self.model)
        if not self.model:
            return None

        try:
            log_debug(f"   Calling compression model to summarize {len(old_tool_results)} tool results")
            compression_messages = [
                Message(role="system", content=self._get_compression_prompt()),
                Message(role="user", content=compression_input),
            ]

            response = await self.model.aresponse(messages=compression_messages)
            compressed_content = response.content if response.content else None

            if compressed_content:
                log_debug(f"   Generated compressed summary ({len(str(compressed_content))} chars)")

            return compressed_content
        except Exception as e:
            log_debug(f"   Compression model call failed: {e}")
            return None

    def compress_tool_results(
        self,
        messages: List[Message],
        keep_last_n: Optional[int] = None,
    ) -> List[Message]:
        from copy import deepcopy

        threshold = keep_last_n or self.tool_compression_threshold

        # 1. Get all tool_call_ids from tool messages (in order)
        all_tool_call_ids = []
        for msg in messages:
            if msg.role == "tool" and msg.tool_call_id:
                all_tool_call_ids.append(msg.tool_call_id)

        # 2. Check if compression needed
        if len(all_tool_call_ids) <= threshold:
            log_debug(f"Tool count ({len(all_tool_call_ids)}) <= threshold ({threshold}), skipping compression")
            return messages

        # 3. Split: old (compress content) vs recent (keep original)
        old_ids = set(all_tool_call_ids[:-threshold])
        recent_ids = set(all_tool_call_ids[-threshold:])

        # Log compression details
        log_info(f"🗜️  Context compression triggered: {len(all_tool_call_ids)} tool calls > threshold ({threshold})")
        log_info(f"   Compressing {len(old_ids)} older tool results, keeping {threshold} recent")

        # 4. Get old tool results for compression
        old_tool_results = [m for m in messages if m.role == "tool" and m.tool_call_id in old_ids]

        # Show what's being compressed
        if old_tool_results:
            from collections import Counter

            tool_counts = Counter(m.tool_name for m in old_tool_results)
            log_info(f"   Compressed tools by type: {dict(tool_counts)}")

        # 5. Compress old tool results with LLM
        compressed_content = self._compress_with_llm(old_tool_results)

        # 6. Replace content in old tool results, keep everything else as-is
        result = []
        for msg in messages:
            if msg.role == "tool" and msg.tool_call_id in old_ids:
                # Replace with compressed content
                compressed_msg = deepcopy(msg)
                compressed_msg.content = compressed_content or "[COMPRESSED - content removed]"
                result.append(compressed_msg)
            else:
                # Keep as-is (assistant, user, system, recent tools)
                result.append(msg)

        # 7. Update stats and log results
        self.compression_count += 1
        log_info(
            f"✅ Compression complete: {len(old_ids)} tool results compressed (compression #{self.compression_count})"
        )

        return result

    async def acompress_tool_results(
        self,
        messages: List[Message],
        keep_last_n: Optional[int] = None,
    ) -> List[Message]:
        """Async version of compress_tool_results.

        Args:
            messages: Current message list from the agentic loop
            keep_last_n: Number of recent tool results to keep (overrides threshold)

        Returns:
            Modified message list with old tool results compressed
        """
        from copy import deepcopy

        threshold = keep_last_n or self.tool_compression_threshold

        # 1. Get all tool_call_ids from tool messages (in order)
        all_tool_call_ids = []
        for msg in messages:
            if msg.role == "tool" and msg.tool_call_id:
                all_tool_call_ids.append(msg.tool_call_id)

        # 2. Check if compression needed
        if len(all_tool_call_ids) <= threshold:
            log_debug(f"Tool count ({len(all_tool_call_ids)}) <= threshold ({threshold}), skipping compression")
            return messages

        # 3. Split: old (compress content) vs recent (keep original)
        old_ids = set(all_tool_call_ids[:-threshold])
        recent_ids = set(all_tool_call_ids[-threshold:])

        # Log compression details
        log_info(f"🗜️  Context compression triggered: {len(all_tool_call_ids)} tool calls > threshold ({threshold})")
        log_info(f"   Compressing {len(old_ids)} older tool results, keeping {threshold} recent")

        # 4. Get old tool results for compression
        old_tool_results = [m for m in messages if m.role == "tool" and m.tool_call_id in old_ids]

        # Show what's being compressed
        if old_tool_results:
            from collections import Counter

            tool_counts = Counter(m.tool_name for m in old_tool_results)
            log_info(f"   Compressed tools by type: {dict(tool_counts)}")

        # 5. Compress old tool results with LLM (async)
        compressed_content = await self._acompress_with_llm(old_tool_results)

        # 6. Replace content in old tool results, keep everything else as-is
        result = []
        for msg in messages:
            if msg.role == "tool" and msg.tool_call_id in old_ids:
                # Replace with compressed content
                compressed_msg = deepcopy(msg)
                compressed_msg.content = compressed_content or "[COMPRESSED - content removed]"
                result.append(compressed_msg)
            else:
                # Keep as-is (assistant, user, system, recent tools)
                result.append(msg)

        # 7. Update stats and log results
        self.compression_count += 1
        log_info(
            f"✅ Compression complete: {len(old_ids)} tool results compressed (compression #{self.compression_count})"
        )

        return result
