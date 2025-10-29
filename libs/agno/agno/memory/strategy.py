"""Memory optimization strategies for managing and compressing user memories."""

from abc import ABC, abstractmethod
from enum import Enum
from typing import TYPE_CHECKING, List, Optional

if TYPE_CHECKING:
    from agno.db.schemas import UserMemory
    from agno.models.base import Model


class MemoryOptimizationStrategyType(str, Enum):
    """Enumeration of available memory optimization strategies."""

    SUMMARIZE = "summarize"
    MERGE = "merge"

    @classmethod
    def from_string(cls, strategy_name: str) -> "MemoryOptimizationStrategyType":
        """Convert a string to a MemoryOptimizationStrategyType.

        Args:
            strategy_name: Strategy name to convert

        Returns:
            MemoryOptimizationStrategyType enum member

        Raises:
            ValueError: If strategy name is not recognized
        """
        strategy_name_clean = strategy_name.strip().lower()

        # Try exact enum value match
        for enum_member in cls:
            if enum_member.value == strategy_name_clean:
                return enum_member

        raise ValueError(f"Unsupported optimization strategy: {strategy_name}. Valid options: {[e.value for e in cls]}")


class MemoryOptimizationStrategy(ABC):
    """Base class for memory optimization strategies."""

    def count_tokens(self, memories: List["UserMemory"]) -> int:
        """Count total tokens in memories using tiktoken.

        Args:
            memories: List of UserMemory objects to count tokens for.

        Returns:
            Total token count across all memories.
        """
        try:
            import tiktoken

            # Use cl100k_base encoding (GPT-4, GPT-4o, GPT-3.5-turbo)
            encoding = tiktoken.get_encoding("cl100k_base")

            total_tokens = 0
            for memory in memories:
                if memory.memory:
                    tokens = encoding.encode(memory.memory)
                    total_tokens += len(tokens)

            return total_tokens
        except ImportError:
            from agno.utils.log import log_warning

            log_warning("tiktoken not installed. Using character-based estimation.")
            # Fallback: rough estimation (1 token ≈ 4 characters)
            total_chars = sum(len(memory.memory) for memory in memories if memory.memory)
            return total_chars // 4
        except Exception as e:
            from agno.utils.log import log_warning

            log_warning(f"Error counting tokens: {e}. Using character-based estimation.")
            total_chars = sum(len(memory.memory) for memory in memories if memory.memory)
            return total_chars // 4

    @abstractmethod
    def get_system_prompt(self, **kwargs) -> str:
        """Get strategy-specific system prompt.

        Args:
            **kwargs: Strategy-specific parameters for prompt generation

        Returns:
            System prompt string for LLM
        """
        raise NotImplementedError

    @abstractmethod
    def optimize(
        self,
        memories: List["UserMemory"],
        token_limit: int,
        model: "Model",
        user_id: Optional[str] = None,
    ) -> List["UserMemory"]:
        """Optimize memories according to strategy.

        Args:
            memories: List of memories to optimize
            token_limit: Maximum tokens for optimized result
            model: Model to use for optimization
            user_id: Optional user ID for context

        Returns:
            List of optimized UserMemory objects
        """
        raise NotImplementedError


class MemoryOptimizationStrategyFactory:
    """Factory for creating memory optimization strategy instances."""

    @classmethod
    def create_strategy(cls, strategy_type: MemoryOptimizationStrategyType, **kwargs) -> MemoryOptimizationStrategy:
        """Create an instance of the optimization strategy with given parameters.

        Args:
            strategy_type: Type of strategy to create
            **kwargs: Additional parameters for strategy initialization

        Returns:
            MemoryOptimizationStrategy instance
        """
        strategy_map = {
            MemoryOptimizationStrategyType.SUMMARIZE: cls._create_summarize,
            MemoryOptimizationStrategyType.MERGE: cls._create_merge,
        }
        return strategy_map[strategy_type](**kwargs)

    @classmethod
    def _create_summarize(cls, **kwargs) -> MemoryOptimizationStrategy:
        from agno.memory.strategies.summarize import SummarizeStrategy

        return SummarizeStrategy(**kwargs)

    @classmethod
    def _create_merge(cls, **kwargs) -> MemoryOptimizationStrategy:
        from agno.memory.strategies.merge import MergeStrategy

        return MergeStrategy(**kwargs)
