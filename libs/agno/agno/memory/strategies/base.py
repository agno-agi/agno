from abc import ABC, abstractmethod
from typing import List

from agno.db.schemas import UserMemory
from agno.models.base import Model
from agno.utils.tokens import count_text_tokens


class MemoryOptimizationStrategy(ABC):
    """Abstract base class for memory optimization strategies.

    Subclasses must implement optimize() and aoptimize().
    get_system_prompt() is optional and only needed for LLM-based strategies.
    """

    def get_system_prompt(self) -> str:
        """Get system prompt for this optimization strategy.

        Returns:
            System prompt string for LLM-based strategies.
        """
        raise NotImplementedError

    @abstractmethod
    def optimize(
        self,
        memories: List[UserMemory],
        model: Model,
    ) -> List[UserMemory]:
        """Optimize memories synchronously.

        Args:
            memories: List of UserMemory objects to optimize
            model: Model to use for optimization (if needed)

        Returns:
            List of optimized UserMemory objects
        """
        raise NotImplementedError

    @abstractmethod
    async def aoptimize(
        self,
        memories: List[UserMemory],
        model: Model,
    ) -> List[UserMemory]:
        """Optimize memories asynchronously.

        Args:
            memories: List of UserMemory objects to optimize
            model: Model to use for optimization (if needed)

        Returns:
            List of optimized UserMemory objects
        """
        raise NotImplementedError

    def count_tokens(self, memories: List[UserMemory]) -> int:
        """Count total tokens across all memories.

        Args:
            memories: List of UserMemory objects
        Returns:
            Total token count
        """
        return sum(count_text_tokens(m.memory or "") for m in memories)
