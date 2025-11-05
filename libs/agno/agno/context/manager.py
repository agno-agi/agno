from dataclasses import dataclass
from textwrap import dedent
from typing import List, Optional

from agno.models.base import Model
from agno.models.message import Message
from agno.models.utils import get_model
from agno.utils.log import log_info

DEFAULT_COMPRESSION_PROMPT = dedent("""\
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
    
    Be extremely concise while retaining ALL factual data points.
    """
)


@dataclass
class ContextManager:
    model: Optional["Model"] = None
    compress_tool_calls_limit: int = 3
    compress_tokens_limit: Optional[int] = None
    tool_compression_instructions: Optional[str] = None

    def _get_total_input_tokens(self, metrics) -> int:
        if not metrics:
            return 0
        return metrics.input_tokens + metrics.audio_input_tokens + metrics.cache_read_tokens

    def should_compress(self, messages: List[Message]) -> bool:
        uncompressed_count = len([m for m in messages if m.role == "tool" and not m.is_compressed])

        # Token-based check
        if self.compress_tokens_limit:
            assistant_msgs = [m for m in messages if m.role == "assistant" and m.metrics]
            if assistant_msgs:
                last_input = self._get_total_input_tokens(assistant_msgs[-1].metrics)
                should_compress = last_input > self.compress_tokens_limit
                log_info(
                    f"Context: {last_input:,} tokens (threshold: {self.compress_tokens_limit:,}) - "
                    f"{'Compressing' if should_compress else 'OK'}"
                )
                return should_compress
            return False

        # Tool call count-based check
        should_compress = uncompressed_count > self.compress_tool_calls_limit
        log_info(
            f"Uncompressed tools: {uncompressed_count} (threshold: {self.compress_tool_calls_limit}) - "
            f"{'Compressing' if should_compress else 'OK'}"
        )
        return should_compress


    def _compress_tool_result(self, tool_results: List[Message]) -> Optional[str]:
        if not tool_results:
            return None

        # Build input
        tool_content = "\n---\n".join(f"Tool: {msg.tool_name or 'unknown'}\n{msg.content}" for msg in tool_results)

        self.model = get_model(self.model)
        if not self.model:
            return None

        compression_prompt = self.tool_compression_instructions or DEFAULT_COMPRESSION_PROMPT
        try:
            response = self.model.response(
                messages=[
                    Message(role="system", content=compression_prompt),
                    Message(role="user", content=tool_content),
                ]
            )
            return response.content
        except Exception:
            return None

    def compress_tool_results(self, messages: List[Message]) -> List[Message]:
        """Compress all uncompressed tool results individually."""
        # Find uncompressed tools
        uncompressed = [m for m in messages if m.role == "tool" and not m.is_compressed]
        if not uncompressed:
            return messages

        compressed_count = 0
        for tool_msg in uncompressed:
            compressed_content = self._compress_tool_result([tool_msg])

            if compressed_content:
                # Update message
                tool_msg.content = f"[COMPRESSED] {compressed_content}"
                tool_msg.is_compressed = True

                # Update tool_calls array if present (Gemini)
                if tool_msg.tool_calls:
                    for tc in tool_msg.tool_calls:
                        if isinstance(tc, dict):
                            tc["content"] = compressed_content

                compressed_count += 1

        log_info(f"Compressed {compressed_count}/{len(uncompressed)} tool calls")
        return messages
