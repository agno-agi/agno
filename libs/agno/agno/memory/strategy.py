"""Memory optimization strategies for managing and compressing user memories."""

from enum import Enum

from agno.memory.strategies.base import MemoryOptimizationStrategy


class MemoryOptimizationStrategyType(str, Enum):
    """Enumeration of available memory optimization strategies."""

    MERGE = "merge"


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
            MemoryOptimizationStrategyType.MERGE: cls._create_merge,
        }
        return strategy_map[strategy_type](**kwargs)

    @classmethod
    def _create_merge(cls, **kwargs) -> MemoryOptimizationStrategy:
        from agno.memory.strategies.merge import MergeStrategy

        return MergeStrategy(**kwargs)
