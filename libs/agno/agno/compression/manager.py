import asyncio
from dataclasses import dataclass, field
from textwrap import dedent
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Type, Union

from pydantic import BaseModel

from agno.models.base import Model
from agno.models.message import Message
from agno.models.utils import get_model
from agno.utils.log import log_debug, log_error, log_info, log_warning

if TYPE_CHECKING:
    from agno.compression.context import CompactionResult, ContextCompactionManager
    from agno.metrics import RunMetrics
    from agno.run.agent import RunOutput

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
class CompressionManager:
    """Unified compression manager for tool results and message history.

    Handles two types of compression:
    1. Tool compression (mid-loop): Compresses individual tool results
    2. History compaction (pre-loop): Summarizes old conversation history

    Usage:
        # Tool compression only (default)
        compression_manager = CompressionManager(model=OpenAI(id="gpt-4o-mini"))

        # Both tool compression and history compaction
        compression_manager = CompressionManager(
            model=OpenAI(id="gpt-4o-mini"),
            compress_history=True,
            history_token_limit=50_000,
        )
    """

    model: Optional[Model] = None

    # Tool compression settings
    compress_tool_results: bool = True
    compress_tool_results_limit: Optional[int] = None
    compress_token_limit: Optional[int] = None
    compress_tool_call_instructions: Optional[str] = None

    # History compaction settings
    compress_history: bool = False
    history_message_limit: Optional[int] = None
    history_token_limit: Optional[int] = None
    history_keep_recent: int = 10
    history_preserve_user_budget: Optional[int] = None
    history_instructions: Optional[str] = None

    stats: Dict[str, Any] = field(default_factory=dict)

    # Internal compactor (created lazily)
    _compactor: Optional["ContextCompactionManager"] = field(default=None, repr=False)

    def __post_init__(self) -> None:
        if self.compress_tool_results_limit is None and self.compress_token_limit is None:
            self.compress_tool_results_limit = 3

        # Create internal compactor if history compression enabled
        if self.compress_history:
            from agno.compression.context import ContextCompactionManager

            self._compactor = ContextCompactionManager(
                model=self.model,
                message_limit=self.history_message_limit,
                token_limit=self.history_token_limit,
                keep_recent=self.history_keep_recent,
                preserve_user_budget=self.history_preserve_user_budget,
                instructions=self.history_instructions,
            )

    # --- Backward compatibility: expose internal compactor ---

    @property
    def context_compaction_manager(self) -> Optional["ContextCompactionManager"]:
        """Access the internal compactor for backward compatibility."""
        return self._compactor

    # --- Tool compression methods (existing) ---

    def _is_tool_result_message(self, msg: Message) -> bool:
        return msg.role == "tool"

    def should_compress(
        self,
        messages: List[Message],
        tools: Optional[List] = None,
        model: Optional[Model] = None,
        response_format: Optional[Union[Dict, Type[BaseModel]]] = None,
    ) -> bool:
        """Check if tool results should be compressed."""
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
            uncompressed_tools_count = len(
                [m for m in messages if self._is_tool_result_message(m) and m.compressed_content is None]
            )
            if uncompressed_tools_count >= self.compress_tool_results_limit:
                log_info(f"Tool count limit hit: {uncompressed_tools_count} >= {self.compress_tool_results_limit}")
                return True

        return False

    def _compress_tool_result(
        self,
        tool_result: Message,
        run_metrics: Optional["RunMetrics"] = None,
    ) -> Optional[str]:
        if not tool_result:
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
        """Compress uncompressed tool results."""
        if not self.compress_tool_results:
            return

        uncompressed_tools = [msg for msg in messages if msg.role == "tool" and msg.compressed_content is None]

        if not uncompressed_tools:
            return

        for tool_msg in uncompressed_tools:
            original_len = len(str(tool_msg.content)) if tool_msg.content else 0
            compressed = self._compress_tool_result(tool_msg, run_metrics=run_metrics)
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

    # --- History compaction methods (new) ---

    def should_compact(self, messages: List[Message]) -> bool:
        """Check if history should be compacted."""
        if self._compactor is None:
            return False
        return self._compactor.should_compact(messages)

    def compact(
        self,
        messages: List[Message],
        run_response: Optional["RunOutput"] = None,
        run_metrics: Optional["RunMetrics"] = None,
    ) -> "CompactionResult":
        """Compact history into summary message."""
        from agno.compression.context import CompactionResult

        if self._compactor is None:
            return CompactionResult(compacted_messages=messages)

        log_debug("[COMPRESSION_MANAGER] compact()")
        result = self._compactor.compact(messages, run_response, run_metrics)
        self._sync_compactor_stats()
        return result

    async def ashould_compact(self, messages: List[Message]) -> bool:
        """Async check if history should be compacted."""
        if self._compactor is None:
            return False
        return await self._compactor.ashould_compact(messages)

    async def acompact(
        self,
        messages: List[Message],
        run_response: Optional["RunOutput"] = None,
        run_metrics: Optional["RunMetrics"] = None,
    ) -> "CompactionResult":
        """Async compact history into summary message."""
        from agno.compression.context import CompactionResult

        if self._compactor is None:
            return CompactionResult(compacted_messages=messages)

        log_debug("[COMPRESSION_MANAGER] acompact()")
        result = await self._compactor.acompact(messages, run_response, run_metrics)
        self._sync_compactor_stats()
        return result

    def _sync_compactor_stats(self) -> None:
        """Sync stats from internal compactor."""
        if self._compactor is not None:
            compactor_stats = getattr(self._compactor, "stats", None)
            if compactor_stats:
                for key, value in compactor_stats.items():
                    self.stats[f"history_{key}"] = value

    # --- Async tool compression methods ---

    async def ashould_compress(
        self,
        messages: List[Message],
        tools: Optional[List] = None,
        model: Optional[Model] = None,
        response_format: Optional[Union[Dict, Type[BaseModel]]] = None,
    ) -> bool:
        """Async check if tool results should be compressed."""
        if not self.compress_tool_results:
            return False

        if self.compress_token_limit is not None and model is not None:
            tokens = await model.acount_tokens(messages, tools, response_format)
            if tokens >= self.compress_token_limit:
                log_info(f"Token limit hit: {tokens} >= {self.compress_token_limit}")
                return True

        if self.compress_tool_results_limit is not None:
            uncompressed_tools_count = len(
                [m for m in messages if self._is_tool_result_message(m) and m.compressed_content is None]
            )
            if uncompressed_tools_count >= self.compress_tool_results_limit:
                log_info(f"Tool count limit hit: {uncompressed_tools_count} >= {self.compress_tool_results_limit}")
                return True

        return False

    async def _acompress_tool_result(
        self,
        tool_result: Message,
        run_metrics: Optional["RunMetrics"] = None,
    ) -> Optional[str]:
        """Async compress a single tool result."""
        if not tool_result:
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
        """Async compress uncompressed tool results."""
        if not self.compress_tool_results:
            return

        uncompressed_tools = [msg for msg in messages if msg.role == "tool" and msg.compressed_content is None]

        if not uncompressed_tools:
            return

        original_sizes = [len(str(msg.content)) if msg.content else 0 for msg in uncompressed_tools]

        tasks = [self._acompress_tool_result(msg, run_metrics=run_metrics) for msg in uncompressed_tools]
        results = await asyncio.gather(*tasks)

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
