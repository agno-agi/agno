from dataclasses import dataclass
from textwrap import dedent
from typing import TYPE_CHECKING, List, Optional

from agno.models.base import Model
from agno.models.message import Message
from agno.models.utils import get_model
from agno.utils.log import log_debug, log_warning

if TYPE_CHECKING:
    from agno.agent.agent import Agent
    from agno.team.team import Team

DEFAULT_COMPRESSION_PROMPT = dedent("""\
    You are compressing tool call results to save context space while preserving critical information.
    
    Your goal: Extract only the essential information from the tool output.
    
    ALWAYS PRESERVE:
    • Specific facts: numbers, statistics, amounts, prices, quantities, metrics
    • Temporal data: dates, times, timestamps (use short format: "Oct 21 2025")
    • Entities: people, companies, products, locations, organizations
    • Identifiers: URLs, IDs, codes, technical identifiers, versions
    • Key quotes, citations, sources (if relevant to agent's task)
    
    COMPRESS TO ESSENTIALS:
    • Descriptions: keep only key attributes
    • Explanations: distill to core insight
    • Lists: focus on most relevant items based on agent context
    • Background: minimal context only if critical
    
    REMOVE ENTIRELY:
    • Introductions, conclusions, transitions
    • Hedging language ("might", "possibly", "appears to")
    • Meta-commentary ("According to", "The results show")
    • Formatting artifacts (markdown, HTML, JSON structure)
    • Redundant or repetitive information
    • Generic background not relevant to agent's task
    • Promotional language, filler words
    
    EXAMPLE:
    Input: "According to recent market analysis and industry reports, OpenAI has made several significant announcements in the technology sector. The company revealed ChatGPT Atlas on October 21, 2025, which represents a new AI-powered browser application that has been specifically designed for macOS users. This browser is strategically positioned to compete with traditional search engines in the market. Additionally, on October 6, 2025, OpenAI launched Apps in ChatGPT, which includes a comprehensive software development kit (SDK) for developers. The company has also announced several initial strategic partners who will be integrating with this new feature, including well-known companies such as Spotify, the popular music streaming service, Zillow, which is a real estate marketplace platform, and Canva, a graphic design platform."
    
    Output: "OpenAI - Oct 21 2025: ChatGPT Atlas (AI browser, macOS, search competitor); Oct 6 2025: Apps in ChatGPT + SDK; Partners: Spotify, Zillow, Canva"
    
    Be concise while retaining all critical facts.
    """)


@dataclass
class ContextManager:
    model: Optional[Model] = None
    agent: Optional["Agent"] = None
    team: Optional["Team"] = None
    compress_tool_calls_limit: int = 3
    tool_compression_instructions: Optional[str] = None

    def _is_tool_result_message(self, msg: Message) -> bool:
        """
        Check if message contains tool results (any provider format).

        Standard providers (OpenAI, Gemini): role="tool"
        Bedrock: role="user" with content=[{"toolResult": {...}}]
        """
        if msg.role == "tool":
            return True

        # Bedrock format: role="user" with list containing toolResult dicts
        if msg.role == "user" and isinstance(msg.content, list):
            for item in msg.content:
                if isinstance(item, dict) and "toolResult" in item:
                    return True

        return False

    def should_compress(self, messages: List[Message]) -> bool:
        """
        Count uncompressed tool results, including Bedrock-style user messages.
        """
        uncompressed_tools_count = len(
            [m for m in messages if self._is_tool_result_message(m) and m.compressed_content is None]
        )
        result = uncompressed_tools_count > self.compress_tool_calls_limit

        log_debug(
            f"Compression check: {uncompressed_tools_count} uncompressed tools "
            f"(including Bedrock format), threshold: {self.compress_tool_calls_limit}, compress: {result}"
        )

        return result

    def _compress_tool_result(self, tool_results: List[Message]) -> Optional[str]:
        if not tool_results:
            return None

        tool_content = "\n---\n".join(f"Tool: {msg.tool_name or 'unknown'}\n{msg.content}" for msg in tool_results)
        original_size = len(tool_content)

        self.model = get_model(self.model)
        if not self.model:
            log_warning("No compression model available")
            return None

        compression_prompt = self.tool_compression_instructions or DEFAULT_COMPRESSION_PROMPT
        compression_message = "Tool Results to Compress: " + tool_content + "\n"

        try:
            response = self.model.response(
                messages=[
                    Message(role="system", content=compression_prompt),
                    Message(role="user", content=compression_message),
                ]
            )
            if response.content:
                compressed_size = len(response.content)
                reduction = int((1 - compressed_size / original_size) * 100) if original_size > 0 else 0
                log_debug(f"  Compressed: {original_size}→{compressed_size}B ({reduction}% reduction)")
            return response.content
        except Exception as e:
            log_warning(f"Compression failed: {e}")
            return None

    def compress_messages_and_results(self, messages: List[Message], function_call_results: List[Message]) -> None:
        """
        Compress tool results before formatting.

        Two-phase compression:
        1. Compress NEW function_call_results (sets compressed_content)
        2. Compress OLD tool messages in messages array (sets compressed_content + modifies content)

        Args:
            messages: Existing messages array (may contain old tool results)
            function_call_results: New tool results from current execution
        """
        existing_tool_count = len([m for m in messages if m.role == "tool"])
        log_debug(
            f"🗜️  Compression starting: {existing_tool_count} existing tools, {len(function_call_results)} new results"
        )

        # Phase 1: Compress NEW results
        for idx, result in enumerate(function_call_results):
            if result.compressed_content is None:
                compressed = self._compress_tool_result([result])
                if compressed:
                    result.compressed_content = compressed
                    original_len = len(str(result.content)) if result.content else 0
                    compressed_len = len(compressed)
                    log_debug(f"  NEW[{idx}] {result.tool_name}: {original_len}→{compressed_len}B")

        # Phase 2: Retroactively compress OLD standard tool messages
        old_count = 0
        for msg in messages:
            if msg.role == "tool" and msg.compressed_content is None:
                compressed = self._compress_tool_result([msg])
                if compressed:
                    original_len = len(str(msg.content)) if msg.content else 0
                    compressed_len = len(compressed)
                    msg.compressed_content = compressed
                    msg.content = compressed  # Modify for next API call
                    old_count += 1
                    log_debug(f"  OLD message {msg.tool_name}: {original_len}→{compressed_len}B (retroactive)")

        if old_count > 0:
            log_debug(f"  Total retroactively compressed: {old_count} old standard messages")

        # Phase 3: Compress Bedrock-style user messages with tool results
        bedrock_count = 0
        for msg in messages:
            if msg.role == "user" and isinstance(msg.content, list) and msg.compressed_content is None:
                # Extract tool results from Bedrock structure
                tool_results = []
                for item in msg.content:
                    if isinstance(item, dict) and "toolResult" in item:
                        tool_result = item.get("toolResult", {})
                        content_items = tool_result.get("content", [])
                        for content_item in content_items:
                            if isinstance(content_item, dict) and "json" in content_item:
                                result_data = content_item["json"].get("result", "")
                                tool_results.append(str(result_data))

                if tool_results:
                    # Compress the combined tool results
                    combined_content = "\n---\n".join(tool_results)
                    temp_msg = Message(role="tool", content=combined_content, tool_name="bedrock_combined")
                    compressed = self._compress_tool_result([temp_msg])

                    if compressed:
                        original_len = len(combined_content)
                        compressed_len = len(compressed)
                        msg.compressed_content = compressed
                        # Modify the nested content structure to use compressed version
                        for item in msg.content:
                            if isinstance(item, dict) and "toolResult" in item:
                                tool_result = item.get("toolResult", {})
                                content_items = tool_result.get("content", [])
                                for content_item in content_items:
                                    if isinstance(content_item, dict) and "json" in content_item:
                                        content_item["json"]["result"] = compressed
                        bedrock_count += 1
                        log_debug(f"  OLD Bedrock message: {original_len}→{compressed_len}B (retroactive)")

        if bedrock_count > 0:
            log_debug(f"  Total retroactively compressed: {bedrock_count} Bedrock-format messages")
