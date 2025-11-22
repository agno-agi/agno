"""Memory optimization strategy types and factory."""

from enum import Enum

from agno.memory.strategies import MemoryOptimizationStrategy


class MemoryOptimizationStrategyType(str, Enum):
    """Enumeration of available memory optimization strategies."""

    SUMMARIZE = "summarize"


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
            MemoryOptimizationStrategyType.SUMMARIZE: cls._create_summarize_strategy,
        }
        return strategy_map[strategy_type](**kwargs)

    @classmethod
    def _create_summarize_strategy(cls, **kwargs) -> MemoryOptimizationStrategy:
        from agno.memory.strategies.summarize import SummarizeStrategy

        return SummarizeStrategy(**kwargs)
