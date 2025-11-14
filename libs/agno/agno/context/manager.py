from dataclasses import dataclass
from textwrap import dedent
from typing import List, Optional

from agno.models.base import Model
from agno.models.message import Message
from agno.models.utils import get_model
from agno.utils.log import log_debug, log_warning

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
    compress_tool_calls_limit: int = 3
    tool_compression_instructions: Optional[str] = None

    def _is_tool_result_message(self, msg: Message) -> bool:
        if msg.role == "tool":
            return True

        # Bedrock format: role="user"
        if msg.role == "user" and isinstance(msg.content, list):
            for item in msg.content:
                if isinstance(item, dict) and "toolResult" in item:
                    return True

        return False

    def should_compress(self, messages: List[Message]) -> bool:
        uncompressed_tools_count = len(
            [m for m in messages if self._is_tool_result_message(m) and m.compressed_content is None]
        )
        should_compress = uncompressed_tools_count > self.compress_tool_calls_limit

        log_debug(
            f"Compression check: {uncompressed_tools_count} uncompressed tools, threshold: {self.compress_tool_calls_limit}, compress: {should_compress}"
        )

        return should_compress

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
            log_debug(f"Compression failed: {e}. Using original content as fallback.")
            return tool_content

    def compress_tool_results(self, messages: List[Message], function_call_results: List[Message]) -> None:
        # Phase 1: Compress NEW results
        existing_tool_count = len([m for m in messages if m.role == "tool"])
        log_debug(f"🗜️  Compression starting:")
        log_debug(f"   Existing tools in messages: {existing_tool_count}")
        log_debug(f"   New results to process: {len(function_call_results)}")
        log_debug(f"   Compression model: {self.model.id if self.model else 'None'}")

        # Phase 1: Compress NEW results
        log_debug(f"  📝 Phase 1: Compressing new results...")
        for idx, result in enumerate(function_call_results):
            if result.compressed_content is None:
                compressed = self._compress_tool_result([result])
                if compressed:
                    result.compressed_content = compressed
                    original_len = len(str(result.content)) if result.content else 0
                    compressed_len = len(compressed)
                    log_debug(f"  NEW[{idx}] {result.tool_name}: {original_len}→{compressed_len}B")

        phase1_compressed = sum(1 for r in function_call_results if r.compressed_content is not None)
        log_debug(f"  ✅ Phase 1 complete: {phase1_compressed}/{len(function_call_results)} new results compressed")

        # Phase 2: Compress old tool messages
        log_debug(f"  📝 Phase 2: Compressing old tool messages...")
        old_count = 0
        for msg in messages:
            if msg.role == "tool" and msg.compressed_content is None:
                compressed = self._compress_tool_result([msg])
                if compressed:
                    original_len = len(str(msg.content)) if msg.content else 0
                    compressed_len = len(compressed)
                    msg.compressed_content = compressed
                    old_count += 1
                    log_debug(f"  OLD message {msg.tool_name}: {original_len}→{compressed_len}B (retroactive)")

        if old_count > 0:
            log_debug(f"  ✅ Phase 2 complete: {old_count} old tool messages compressed")
