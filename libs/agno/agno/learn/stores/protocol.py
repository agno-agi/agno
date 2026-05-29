"""
Learning Store Protocol
=======================
Defines the interface that all learning stores must implement.

This protocol enables:
- Consistent API across different learning types
- Easy addition of custom stores
- Type safety with Protocol typing
"""

from typing import Any, Callable, List, Optional, Protocol, runtime_checkable


@runtime_checkable
class LearningStore(Protocol):
    """Protocol that all learning stores must implement.

    A learning store handles one type of learning (user profile, session context,
    learned knowledge, etc.) and provides methods for:

    - recall: Retrieve relevant data for the current context
    - process: Extract and save learnings from conversations
    - build_context: Format data for inclusion in agent prompts
    - get_tools: Provide tools for agent interaction
    """

    @property
    def learning_type(self) -> str:
        """Unique identifier for this learning type.

        Used for storage keys and logging.

        Returns:
            String identifier (e.g., "user_profile", "session_context")
        """
        ...

    @property
    def schema(self) -> Any:
        """Schema class used for this learning type.

        Returns:
            The dataclass or schema class for this learning type.
        """
        ...

    def recall(self, **kwargs) -> Optional[Any]:
        """Retrieve relevant data for the current context.

        Args:
            **kwargs: Context including user_id, session_id, message, etc.

        Returns:
            Retrieved data (schema instance, list, or None if not found).
        """
        ...

    async def arecall(self, **kwargs) -> Optional[Any]:
        """Async version of recall."""
        ...

    def process(self, messages: List[Any], **kwargs) -> None:
        """Extract and save learnings from messages.

        Called after a conversation to extract learnings.

        Args:
            messages: Conversation messages to analyze.
            **kwargs: Context including user_id, session_id, etc.
        """
        ...

    async def aprocess(self, messages: List[Any], **kwargs) -> None:
        """Async version of process."""
        ...

    def build_context(self, data: Any) -> str:
        """Build context string for agent prompts.

        Formats the recalled data into a string that can be
        injected into the agent's system prompt.

        Args:
            data: Data returned from recall().

        Returns:
            Formatted context string, or empty string if no data.
        """
        ...

    def get_tools(self, **kwargs) -> List[Callable]:
        """Get tools to expose to the agent.

        Returns callable tools that the agent can use to interact
        with this learning type (e.g., update_user_memory, search_learnings).

        Args:
            **kwargs: Context including user_id, session_id, etc.

        Returns:
            List of callable tools, or empty list if no tools.
        """
        ...

    async def aget_tools(self, **kwargs) -> List[Callable]:
        """Async version of get_tools."""
        ...

    @property
    def was_updated(self) -> bool:
        """Check if the store was updated in the last operation.

        Returns:
            True if data was saved/updated, False otherwise.
        """
        ...
