import asyncio
import re
from dataclasses import dataclass, field
from textwrap import dedent
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Type, Union

from pydantic import BaseModel

from agno.models.base import Model
from agno.models.message import Message
from agno.models.utils import get_model
from agno.utils.log import log_error, log_info, log_warning

if TYPE_CHECKING:
    from agno.metrics import RunMetrics

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

# ResultStore envelopes are intentionally plain text because they need to be
# understood by every model provider.  Keep the recognition here local to the
# compression manager instead of importing the offload implementation: the
# manager is initialized for every Agent/Team and importing the storage stack
# would make an optional feature part of the compression hot path.
_RESULT_ENVELOPE_PREFIX = "<result "
_RESULT_ENVELOPE_CLOSE = "</result>"
_STORED_RESULT_NOTICE = "Full result stored; read with read_result("
_REFUSED_RESULT_NOTICE = "Full result was NOT stored."
_RESULT_ID_ATTRIBUTE = re.compile(r"\bid\s*=\s*(['\"])res_[^'\"]+\1")
_REFUSED_ATTRIBUTE = re.compile(r"\bstored\s*=\s*(['\"])false\1")


@dataclass
class CompressionManager:
    model: Optional[Model] = None  # model used for compression
    compress_tool_results: bool = True
    compress_tool_results_limit: Optional[int] = None
    compress_token_limit: Optional[int] = None
    compress_tool_call_instructions: Optional[str] = None

    stats: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if self.compress_tool_results_limit is None and self.compress_token_limit is None:
            self.compress_tool_results_limit = 3

    def _is_tool_result_message(self, msg: Message) -> bool:
        return msg.role == "tool"

    @staticmethod
    def _is_result_envelope(content: Any) -> bool:
        """Return whether *content* is an opaque ResultStore envelope.

        Offloaded results are represented as a short, protocol-like string
        rather than a typed message field.  The result-id / ``stored=\"false\"``
        attributes identify the two envelope variants; the follow-up notice
        is accepted as a backwards-compatible fallback.
        """
        if not isinstance(content, str):
            return False

        text = content.strip()
        if not text.startswith(_RESULT_ENVELOPE_PREFIX):
            return False

        opening_tag_end = text.find(">")
        closing_tag = text.find(_RESULT_ENVELOPE_CLOSE)
        if opening_tag_end < 0 or closing_tag < opening_tag_end:
            return False

        opening_tag = text[: opening_tag_end + 1]
        has_envelope_attribute = bool(
            _RESULT_ID_ATTRIBUTE.search(opening_tag) or _REFUSED_ATTRIBUTE.search(opening_tag)
        )
        if not has_envelope_attribute:
            # Keep the notice fallback for forwards-compatible envelopes that
            # retain the protocol text but change their opening attributes.
            notice = text[closing_tag + len(_RESULT_ENVELOPE_CLOSE) :]
            return _STORED_RESULT_NOTICE in notice or _REFUSED_RESULT_NOTICE in notice

        return True

    def _is_compressible_tool_result(self, msg: Message) -> bool:
        """Return whether a tool message is eligible for model compression."""
        return (
            self._is_tool_result_message(msg)
            and msg.compressed_content is None
            and not self._is_result_envelope(msg.content)
        )

    def should_compress(
        self,
        messages: List[Message],
        tools: Optional[List] = None,
        model: Optional[Model] = None,
        response_format: Optional[Union[Dict, Type[BaseModel]]] = None,
    ) -> bool:
        """Check if tool results should be compressed.

        Args:
            messages: List of messages to check.
            tools: List of tools for token counting.
            model: The Agent / Team model.
            response_format: Output schema for accurate token counting.
        """
        if not self.compress_tool_results:
            return False

        # Token-based threshold check
        if self.compress_token_limit is not None and model is not None:
            tokens = model.count_tokens(messages, tools, response_format)
            if tokens >= self.compress_token_limit:
                log_info(f"Token limit hit: {tokens} >= {self.compress_token_limit}")
                return True

        # Count-based threshold check
        if self.compress_tool_results_limit is not None:
            uncompressed_tools_count = len([m for m in messages if self._is_compressible_tool_result(m)])
            if uncompressed_tools_count >= self.compress_tool_results_limit:
                log_info(f"Tool count limit hit: {uncompressed_tools_count} >= {self.compress_tool_results_limit}")
                return True

        return False

    def _compress_tool_result(
        self,
        tool_result: Message,
        run_metrics: Optional["RunMetrics"] = None,
    ) -> Optional[str]:
        if not tool_result or self._is_result_envelope(tool_result.content):
            return None

        tool_content = f"Tool: {tool_result.tool_name or 'unknown'}\n{tool_result.content}"

        self.model = get_model(self.model)
        if not self.model:
            log_warning("No compression model available")
            return None

        compression_prompt = self.compress_tool_call_instructions or DEFAULT_COMPRESSION_PROMPT
        compression_message = "Tool Results to Compress: " + tool_content + "\n"

        try:
            response = self.model.response(
                messages=[
                    Message(role="system", content=compression_prompt),
                    Message(role="user", content=compression_message),
                ]
            )

            # Accumulate compression model metrics
            if run_metrics is not None:
                from agno.metrics import ModelType, accumulate_model_metrics

                accumulate_model_metrics(response, self.model, ModelType.COMPRESSION_MODEL, run_metrics)

            return response.content
        except Exception as e:
            log_error(f"Error compressing tool result: {str(e)}")
            return tool_content

    def compress(
        self,
        messages: List[Message],
        run_metrics: Optional["RunMetrics"] = None,
    ) -> None:
        """Compress uncompressed tool results"""
        if not self.compress_tool_results:
            return

        uncompressed_tools = [msg for msg in messages if self._is_compressible_tool_result(msg)]

        if not uncompressed_tools:
            return

        # Compress uncompressed tool results
        for tool_msg in uncompressed_tools:
            original_len = len(str(tool_msg.content)) if tool_msg.content else 0
            compressed = self._compress_tool_result(tool_msg, run_metrics=run_metrics)
            if compressed:
                tool_msg.compressed_content = compressed
                # Count actual tool results (Gemini combines multiple in one message)
                tool_results_count = len(tool_msg.tool_calls) if tool_msg.tool_calls else 1
                self.stats["tool_results_compressed"] = (
                    self.stats.get("tool_results_compressed", 0) + tool_results_count
                )
                self.stats["original_size"] = self.stats.get("original_size", 0) + original_len
                self.stats["compressed_size"] = self.stats.get("compressed_size", 0) + len(compressed)
            else:
                log_warning(f"Compression failed for {tool_msg.tool_name}")

    # * Async methods *#
    async def ashould_compress(
        self,
        messages: List[Message],
        tools: Optional[List] = None,
        model: Optional[Model] = None,
        response_format: Optional[Union[Dict, Type[BaseModel]]] = None,
    ) -> bool:
        """Async check if tool results should be compressed.

        Args:
            messages: List of messages to check.
            tools: List of tools for token counting.
            model: The Agent / Team model.
            response_format: Output schema for accurate token counting.
        """
        if not self.compress_tool_results:
            return False

        # Token-based threshold check
        if self.compress_token_limit is not None and model is not None:
            tokens = await model.acount_tokens(messages, tools, response_format)
            if tokens >= self.compress_token_limit:
                log_info(f"Token limit hit: {tokens} >= {self.compress_token_limit}")
                return True

        # Count-based threshold check
        if self.compress_tool_results_limit is not None:
            uncompressed_tools_count = len([m for m in messages if self._is_compressible_tool_result(m)])
            if uncompressed_tools_count >= self.compress_tool_results_limit:
                log_info(f"Tool count limit hit: {uncompressed_tools_count} >= {self.compress_tool_results_limit}")
                return True

        return False

    async def _acompress_tool_result(
        self,
        tool_result: Message,
        run_metrics: Optional["RunMetrics"] = None,
    ) -> Optional[str]:
        """Async compress a single tool result"""
        if not tool_result or self._is_result_envelope(tool_result.content):
            return None

        tool_content = f"Tool: {tool_result.tool_name or 'unknown'}\n{tool_result.content}"

        self.model = get_model(self.model)
        if not self.model:
            log_warning("No compression model available")
            return None

        compression_prompt = self.compress_tool_call_instructions or DEFAULT_COMPRESSION_PROMPT
        compression_message = "Tool Results to Compress: " + tool_content + "\n"

        try:
            response = await self.model.aresponse(
                messages=[
                    Message(role="system", content=compression_prompt),
                    Message(role="user", content=compression_message),
                ]
            )

            # Accumulate compression model metrics
            if run_metrics is not None:
                from agno.metrics import ModelType, accumulate_model_metrics

                accumulate_model_metrics(response, self.model, ModelType.COMPRESSION_MODEL, run_metrics)

            return response.content
        except Exception as e:
            log_error(f"Error compressing tool result: {str(e)}")
            return tool_content

    async def acompress(
        self,
        messages: List[Message],
        run_metrics: Optional["RunMetrics"] = None,
    ) -> None:
        """Async compress uncompressed tool results"""
        if not self.compress_tool_results:
            return

        uncompressed_tools = [msg for msg in messages if self._is_compressible_tool_result(msg)]

        if not uncompressed_tools:
            return

        # Track original sizes before compression
        original_sizes = [len(str(msg.content)) if msg.content else 0 for msg in uncompressed_tools]

        # Parallel compression using asyncio.gather
        tasks = [self._acompress_tool_result(msg, run_metrics=run_metrics) for msg in uncompressed_tools]
        results = await asyncio.gather(*tasks)

        # Apply results and track stats
        for msg, compressed, original_len in zip(uncompressed_tools, results, original_sizes):
            if compressed:
                msg.compressed_content = compressed
                # Count actual tool results (Gemini combines multiple in one message)
                tool_results_count = len(msg.tool_calls) if msg.tool_calls else 1
                self.stats["tool_results_compressed"] = (
                    self.stats.get("tool_results_compressed", 0) + tool_results_count
                )
                self.stats["original_size"] = self.stats.get("original_size", 0) + original_len
                self.stats["compressed_size"] = self.stats.get("compressed_size", 0) + len(compressed)
            else:
                log_warning(f"Compression failed for {msg.tool_name}")
