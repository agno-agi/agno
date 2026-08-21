"""Unified compaction manager for tool results and conversation history."""

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Type, Union

from pydantic import BaseModel

from agno.compression._context import (
    CompactionResult,
    acompact_context,
    ashould_compact_context,
    compact_context,
    should_compact_context,
)
from agno.compression._tool import (
    acompact_tools,
    ashould_compact_tools,
    compact_tools,
    should_compact_tools,
)
from agno.models.base import Model
from agno.models.message import Message
from agno.utils.log import log_debug

if TYPE_CHECKING:
    from agno.metrics import RunMetrics
    from agno.run.agent import RunOutput
    from agno.run.team import TeamRunOutput


@dataclass
class CompactionManager:
    """Unified compaction manager for tool results and message history.

    Handles two types of compaction:
    1. Tool compaction (mid-loop): Compresses individual tool results
    2. Context compaction (pre-loop): Summarizes old conversation history

    Usage:
        # Tool compaction only (default)
        compaction_manager = CompactionManager(model=OpenAI(id="gpt-4o-mini"))

        # Both tool and context compaction
        compaction_manager = CompactionManager(
            model=OpenAI(id="gpt-4o-mini"),
            compact_context=True,
            compact_context_token_limit=50_000,
        )
    """

    model: Optional[Model] = None

    # Tool compaction settings
    compact_tools: bool = True
    compact_tools_limit: Optional[int] = None
    compact_tools_token_limit: Optional[int] = None
    compact_tools_instructions: Optional[str] = None

    # Deprecated tool aliases (backward compat)
    tool_result_limit: Optional[int] = None
    compact_tool_results_limit: Optional[int] = None
    tool_token_limit: Optional[int] = None
    tool_instructions: Optional[str] = None
    compress_token_limit: Optional[int] = None
    compress_tool_call_instructions: Optional[str] = None
    compress_tool_results_limit: Optional[int] = None

    # Context compaction settings
    compact_context: bool = False
    compact_context_message_limit: Optional[int] = None
    compact_context_token_limit: Optional[int] = None
    compact_context_keep_recent: int = 10
    compact_context_preserve_user_budget: Optional[int] = None
    compact_context_instructions: Optional[str] = None

    stats: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        # Handle deprecated tool aliases
        if self.tool_result_limit is not None and self.compact_tools_limit is None:
            log_debug("tool_result_limit is deprecated, use compact_tools_limit")
            self.compact_tools_limit = self.tool_result_limit
        if self.compact_tool_results_limit is not None and self.compact_tools_limit is None:
            log_debug("compact_tool_results_limit is deprecated, use compact_tools_limit")
            self.compact_tools_limit = self.compact_tool_results_limit
        if self.tool_token_limit is not None and self.compact_tools_token_limit is None:
            log_debug("tool_token_limit is deprecated, use compact_tools_token_limit")
            self.compact_tools_token_limit = self.tool_token_limit
        if self.tool_instructions is not None and self.compact_tools_instructions is None:
            log_debug("tool_instructions is deprecated, use compact_tools_instructions")
            self.compact_tools_instructions = self.tool_instructions
        if self.compress_token_limit is not None and self.compact_tools_token_limit is None:
            log_debug("compress_token_limit is deprecated, use compact_tools_token_limit")
            self.compact_tools_token_limit = self.compress_token_limit
        if self.compress_tool_call_instructions is not None and self.compact_tools_instructions is None:
            log_debug("compress_tool_call_instructions is deprecated, use compact_tools_instructions")
            self.compact_tools_instructions = self.compress_tool_call_instructions
        if self.compress_tool_results_limit is not None and self.compact_tools_limit is None:
            log_debug("compress_tool_results_limit is deprecated, use compact_tools_limit")
            self.compact_tools_limit = self.compress_tool_results_limit

        # Default tool limit to 3 if neither limit is set
        if self.compact_tools_limit is None and self.compact_tools_token_limit is None:
            self.compact_tools_limit = 3

        # Default context message limit if neither specified
        if self.compact_context:
            if self.compact_context_message_limit is None and self.compact_context_token_limit is None:
                self.compact_context_message_limit = 50

        # Derive preserve_user_budget as 25% of token_limit if not set
        if self.compact_context_preserve_user_budget is None:
            if self.compact_context_token_limit is not None:
                self.compact_context_preserve_user_budget = int(self.compact_context_token_limit * 0.25)
            else:
                self.compact_context_preserve_user_budget = 20_000

    # --- Backward compatibility ---

    @property
    def compact_history(self) -> bool:
        return self.compact_context

    # --- Tool compaction (delegates to _tool.py) ---

    def should_compact_tools(
        self,
        messages: List[Message],
        tools: Optional[List] = None,
        model: Optional[Model] = None,
        response_format: Optional[Union[Dict, Type[BaseModel]]] = None,
    ) -> bool:
        """Check if tool results should be compacted."""
        return should_compact_tools(
            messages=messages,
            compact_tools=self.compact_tools,
            compact_tools_limit=self.compact_tools_limit,
            compact_tools_token_limit=self.compact_tools_token_limit,
            tools=tools,
            model=model or self.model,
            response_format=response_format,
        )

    async def ashould_compact_tools(
        self,
        messages: List[Message],
        tools: Optional[List] = None,
        model: Optional[Model] = None,
        response_format: Optional[Union[Dict, Type[BaseModel]]] = None,
    ) -> bool:
        """Async check if tool results should be compacted."""
        return await ashould_compact_tools(
            messages=messages,
            compact_tools=self.compact_tools,
            compact_tools_limit=self.compact_tools_limit,
            compact_tools_token_limit=self.compact_tools_token_limit,
            tools=tools,
            model=model or self.model,
            response_format=response_format,
        )

    def compact_tool_results(
        self,
        messages: List[Message],
        run_metrics: Optional["RunMetrics"] = None,
    ) -> None:
        """Compress uncompressed tool results."""
        stats = compact_tools(
            messages=messages,
            model=self.model,
            compact_tools_enabled=self.compact_tools,
            instructions=self.compact_tools_instructions,
            run_metrics=run_metrics,
        )
        self._merge_stats(stats)

    async def acompact_tool_results(
        self,
        messages: List[Message],
        run_metrics: Optional["RunMetrics"] = None,
    ) -> None:
        """Async compress uncompressed tool results."""
        stats = await acompact_tools(
            messages=messages,
            model=self.model,
            compact_tools_enabled=self.compact_tools,
            instructions=self.compact_tools_instructions,
            run_metrics=run_metrics,
        )
        self._merge_stats(stats)

    # --- Context compaction (delegates to _context.py) ---

    def should_compact(self, messages: List[Message]) -> bool:
        """Check if context should be compacted."""
        if not self.compact_context:
            return False
        return should_compact_context(
            messages=messages,
            model=self.model,
            message_limit=self.compact_context_message_limit,
            token_limit=self.compact_context_token_limit,
        )

    async def ashould_compact(self, messages: List[Message]) -> bool:
        """Async check if context should be compacted."""
        if not self.compact_context:
            return False
        return await ashould_compact_context(
            messages=messages,
            model=self.model,
            message_limit=self.compact_context_message_limit,
            token_limit=self.compact_context_token_limit,
        )

    def compact(
        self,
        messages: List[Message],
        run_response: Optional[Union["RunOutput", "TeamRunOutput"]] = None,
        run_metrics: Optional["RunMetrics"] = None,
    ) -> CompactionResult:
        """Compact context into summary message."""
        if not self.compact_context:
            return CompactionResult(compacted_messages=messages)

        if not self.should_compact(messages):
            return CompactionResult(compacted_messages=messages)

        log_debug("[COMPACTION_MANAGER] compact()")
        return compact_context(
            messages=messages,
            model=self.model,
            keep_recent=self.compact_context_keep_recent,
            preserve_user_budget=self.compact_context_preserve_user_budget or 20_000,
            token_limit=self.compact_context_token_limit,
            instructions=self.compact_context_instructions,
            run_response=run_response,
            run_metrics=run_metrics,
        )

    async def acompact(
        self,
        messages: List[Message],
        run_response: Optional[Union["RunOutput", "TeamRunOutput"]] = None,
        run_metrics: Optional["RunMetrics"] = None,
    ) -> CompactionResult:
        """Async compact context into summary message."""
        if not self.compact_context:
            return CompactionResult(compacted_messages=messages)

        if not await self.ashould_compact(messages):
            return CompactionResult(compacted_messages=messages)

        log_debug("[COMPACTION_MANAGER] acompact()")
        return await acompact_context(
            messages=messages,
            model=self.model,
            keep_recent=self.compact_context_keep_recent,
            preserve_user_budget=self.compact_context_preserve_user_budget or 20_000,
            token_limit=self.compact_context_token_limit,
            instructions=self.compact_context_instructions,
            run_response=run_response,
            run_metrics=run_metrics,
        )

    # --- Stats ---

    def _merge_stats(self, stats: Dict[str, Any]) -> None:
        """Merge stats from tool compaction."""
        for key, value in stats.items():
            self.stats[key] = self.stats.get(key, 0) + value


# Backward compatibility alias
CompressionManager = CompactionManager
