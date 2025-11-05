from dataclasses import dataclass
from textwrap import dedent
from typing import TYPE_CHECKING, List, Optional

from agno.models.message import Message
from agno.models.utils import get_model
from agno.utils.log import log_info

if TYPE_CHECKING:
    from agno.models.base import Model


@dataclass
class ContextManager:
    model: Optional["Model"] = None
    compress_tool_calls_limit: int = 3
    tool_compression_instructions: Optional[str] = None
    compress_tokens_limit: Optional[int] = None

    compression_count: int = 0

    def _get_total_input_tokens(self, metrics) -> int:
        """Calculate total input context size including cached and audio tokens.

        Args:
            metrics: Metrics object from a message

        Returns:
            Total input tokens (text + audio + cached)
        """
        if not metrics:
            return 0
        return metrics.input_tokens + metrics.audio_input_tokens + metrics.cache_read_tokens

    def should_compress(self, messages: List[Message]) -> bool:
        """Check if compression needed based on token or tool count threshold.

        Args:
            messages: List of messages in the current context

        Returns:
            True if threshold is exceeded (token-based or count-based)
        """
        # Count total and uncompressed tool calls
        tool_count = len([m for m in messages if m.role == "tool"])
        uncompressed_tool_count = len([m for m in messages if m.role == "tool" and not m.is_compressed])

        # Log detailed metrics analysis
        log_info("=" * 80)
        log_info("COMPRESSION CHECK - METRICS ANALYSIS")
        log_info("=" * 80)

        total_input = 0
        total_output = 0

        for i, msg in enumerate(messages):
            log_info(msg.metrics)
            has_metrics = msg.metrics and (msg.metrics.input_tokens > 0 or msg.metrics.output_tokens > 0)

            if has_metrics:
                log_info(
                    f"Msg {i:2d} [{msg.role:9s}]: "
                    f"input={msg.metrics.input_tokens:5d}, "
                    f"output={msg.metrics.output_tokens:5d}, "
                    f"total={msg.metrics.total_tokens:5d}"
                )
                total_input += msg.metrics.input_tokens
                total_output += msg.metrics.output_tokens
            else:
                log_info(f"Msg {i:2d} [{msg.role:9s}]: no metrics")

        log_info("-" * 80)
        log_info(f"Tool calls in context: {tool_count} (uncompressed: {uncompressed_tool_count})")

        # Show detailed tool call compression status
        tool_messages = [m for m in messages if m.role == "tool"]
        if tool_messages:
            log_info("\nTool Call Compression Status:")
            for i, tool_msg in enumerate(tool_messages, 1):
                content_preview = str(tool_msg.content)[:500] if tool_msg.content else ""
                compressed_marker = "🗜️ COMPRESSED" if tool_msg.is_compressed else "📄 UNCOMPRESSED"
                log_info(
                    f"  {i}. {compressed_marker} | {tool_msg.tool_name or 'unknown'} "
                    f"(ID: {tool_msg.tool_call_id or 'N/A'}) | "
                    f"Size: {len(str(tool_msg.content)) if tool_msg.content else 0} chars | "
                    f"Preview: {content_preview}..."
                )

        # Show last call context size if available
        assistant_messages = [m for m in messages if m.role == "assistant" and m.metrics]
        if assistant_messages:
            last_metrics = assistant_messages[-1].metrics
            last_input = self._get_total_input_tokens(last_metrics)

            # Show breakdown if there are cached/audio tokens
            if last_metrics.cache_read_tokens > 0 or last_metrics.audio_input_tokens > 0:
                log_info(
                    f"Last context size: {last_input:,} total input tokens "
                    f"(text: {last_metrics.input_tokens:,}, "
                    f"cached: {last_metrics.cache_read_tokens:,}, "
                    f"audio: {last_metrics.audio_input_tokens:,})"
                )
            else:
                log_info(f"Last context size: {last_input:,} input tokens")

        # Token-based check if threshold is set
        if self.compress_tokens_limit is not None:
            # Get the last (most recent) assistant message's total input tokens
            # This represents the current context size sent to the model
            assistant_messages = [m for m in messages if m.role == "assistant" and m.metrics]

            if assistant_messages:
                last_input_tokens = self._get_total_input_tokens(assistant_messages[-1].metrics)
                should_compress = last_input_tokens > self.compress_tokens_limit
                log_info(f"Token threshold: {self.compress_tokens_limit:,}")
                log_info(
                    f"Token-based check: last_input={last_input_tokens:,} > {self.compress_tokens_limit:,}? {should_compress}"
                )
                log_info("=" * 80)
                return should_compress
            else:
                # No assistant messages with metrics yet, can't determine context size
                log_info(f"Token threshold: {self.compress_tokens_limit:,}")
                log_info("No assistant messages with metrics yet, skipping token-based check")
                log_info("=" * 80)
                return False

        # Count-based check (default) - count only UNCOMPRESSED tools
        should_compress = uncompressed_tool_count > self.compress_tool_calls_limit
        log_info(f"Tool call threshold: {self.compress_tool_calls_limit}")
        log_info(
            f"Count-based check: uncompressed_count={uncompressed_tool_count} > {self.compress_tool_calls_limit}? {should_compress}"
        )
        log_info("=" * 80)
        return should_compress

    def _get_compression_prompt(self) -> str:
        if self.tool_compression_instructions:
            return self.tool_compression_instructions

        return dedent(
            """\
            You are compressing a single tool call result to preserve essential information while reducing size.
            
            Your task: Extract and preserve the most critical information from this tool result.
            
            MUST PRESERVE:
            - All specific facts, numbers, statistics, percentages, dates, times
            - Names of people, companies, products, locations, organizations
            - Key entities and their relationships
            - Important quotes, citations, or references
            - Critical findings, conclusions, or insights
            - URLs, links, or source references
            
            MUST REMOVE:
            - Verbose explanations and background context
            - Redundant or repetitive information
            - Formatting artifacts (markdown, HTML, JSON structure)
            - Filler words, unnecessary adjectives
            - Generic introductions or conclusions
            
            OUTPUT FORMAT:
            - Concise bullet points or short sentences
            - Preserve source attribution if present
            - Keep it under 200 words
            - Maximum information density
            
            Be extremely concise while retaining ALL factual data points."""
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
            log_info(f"   Calling compression model to summarize {len(old_tool_results)} tool results")
            compression_messages = [
                Message(role="system", content=self._get_compression_prompt()),
                Message(role="user", content=compression_input),
            ]

            response = self.model.response(messages=compression_messages)
            compressed_content = response.content if response.content else None

            if compressed_content:
                log_info(f"   Generated compressed summary ({len(str(compressed_content))} chars)")
                log_info(f"   Compressed content: {compressed_content[:500]}...")

            return compressed_content
        except Exception as e:
            log_info(f"   Compression model call failed: {e}")
            return None

    def compress_tool_results(
        self,
        messages: List[Message],
    ) -> List[Message]:
        """Compress all uncompressed tool results individually.

        Strategy: When threshold crossed, compress ALL uncompressed tool calls,
        each one separately with its own LLM call to preserve granularity.

        Args:
            messages: Current message list

        Returns:
            Modified message list with uncompressed tools compressed
        """
        # 1. Find all uncompressed tool messages
        uncompressed_tools = []
        for msg in messages:
            if msg.role == "tool" and not msg.is_compressed:
                # Pattern 1: Individual tool message (most common)
                if msg.tool_call_id:
                    uncompressed_tools.append(msg)
                # Pattern 2: Combined tool_calls array (Gemini)
                elif msg.tool_calls:
                    # Note: For combined messages, we'll compress the whole message
                    # but need to handle it specially
                    uncompressed_tools.append(msg)

        if not uncompressed_tools:
            log_info("No uncompressed tool calls to compress")
            return messages

        log_info(f"🗜️  Compressing {len(uncompressed_tools)} uncompressed tool calls individually")

        # 2. Compress each tool call individually (one LLM call per tool)
        compressed_count = 0
        from collections import Counter

        tool_names = []
        total_original_chars = 0
        total_compressed_chars = 0

        for tool_msg in uncompressed_tools:
            tool_names.append(tool_msg.tool_name)

            # Calculate original size
            original_content = str(tool_msg.content) if tool_msg.content else ""
            original_chars = len(original_content)
            original_tokens = original_chars // 4  # Rough estimate: 4 chars per token

            total_original_chars += original_chars

            # Compress this single tool result
            compressed_content = self._compress_with_llm([tool_msg])

            if not compressed_content:
                log_info(f"   ⚠️  Skipping {tool_msg.tool_name} (compression failed)")
                continue

            # Calculate compressed size
            compressed_chars = len(compressed_content)
            compressed_tokens = compressed_chars // 4
            total_compressed_chars += compressed_chars

            # Calculate compression ratio
            compression_ratio = (
                ((original_chars - compressed_chars) / original_chars * 100) if original_chars > 0 else 0
            )

            # Find and update the actual message in the list
            for msg in messages:
                if msg is tool_msg:
                    # Replace content with compressed version
                    msg.content = f"[COMPRESSED] {compressed_content}"
                    msg.is_compressed = True

                    # For Gemini combined format, also update tool_calls array
                    if msg.tool_calls:
                        for tc in msg.tool_calls:
                            if isinstance(tc, dict):
                                tc["content"] = compressed_content

                    compressed_count += 1

                    # Log with size details
                    log_info(
                        f"   ✓ {tool_msg.tool_name} (ID: {msg.tool_call_id or 'combined'}): "
                        f"{original_chars:,} → {compressed_chars:,} chars "
                        f"(~{original_tokens:,} → ~{compressed_tokens:,} tokens, "
                        f"{compression_ratio:.1f}% reduction)"
                    )
                    break

        # 3. Update stats
        self.compression_count += 1
        tool_type_counts = Counter(tool_names)

        # Calculate total compression stats
        total_saved_chars = total_original_chars - total_compressed_chars
        total_saved_tokens = total_saved_chars // 4
        overall_ratio = (total_saved_chars / total_original_chars * 100) if total_original_chars > 0 else 0

        log_info("=" * 80)
        log_info(
            f"✅ Compression complete: {compressed_count} tools compressed individually (compression #{self.compression_count})"
        )
        log_info(f"   Tools by type: {dict(tool_type_counts)}")
        log_info(
            f"   Total: {total_original_chars:,} → {total_compressed_chars:,} chars (~{total_saved_tokens:,} tokens saved, {overall_ratio:.1f}% reduction)"
        )
        log_info("=" * 80)

        return messages
