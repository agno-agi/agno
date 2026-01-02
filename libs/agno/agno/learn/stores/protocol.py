"""
Learning Protocol
=================
The interface that all learning stores must implement.

A LearningStore handles four core operations:
1. recall() - Retrieve learnings from storage
2. process() - Extract and save learnings to storage
3. build_context() - Build context for the agent
4. get_tools() - Provide tools to the agent (optional)

This is THE protocol for extending LearningMachine with custom learning types.
Implement this to create stores for project context, team preferences,
domain knowledge, or any other learning type your agents need.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Callable, List, Optional, Type

# =============================================================================
# Learning Protocol
# =============================================================================


@dataclass
class LearningStore(ABC):
    """Protocol for all learning stores.

    Implement this to create custom learning types for LearningMachine.

    Required Methods:
        learning_type: Unique string identifier for this learning type.
        recall(): Retrieve learnings from storage.
        arecall(): Async version of recall.
        process(): Extract and save learnings to storage.
        aprocess(): Async version of process.
        build_context(): Build context for the agent.

    Optional Methods:
        schema: Schema class for introspection.
        get_tools(): Return tools to expose to agent.
        aget_tools(): Async version of get_tools.
        was_updated: Check if store was updated in last operation.
    """

    # -------------------------------------------------------------------------
    # Required: Identity
    # -------------------------------------------------------------------------

    @property
    @abstractmethod
    def learning_type(self) -> str:
        """Unique identifier for this learning type.

        Used for database storage, logging, and debugging.

        Examples:
            "user_profile"
            "session_context"
            "learnings"
            "project_context"
        """
        pass

    # -------------------------------------------------------------------------
    # Optional: Schema
    # -------------------------------------------------------------------------

    @property
    def schema(self) -> Optional[Type[Any]]:
        """Schema class this store uses.

        Override to enable introspection by LearningMachine.

        Returns:
            The dataclass type (e.g., UserProfile, SessionContext),
            or None if not applicable.
        """
        return None

    # -------------------------------------------------------------------------
    # Required: Recall
    # -------------------------------------------------------------------------

    @abstractmethod
    def recall(self, **context) -> Optional[Any]:
        """Retrieve learnings from storage.

        Each store interprets context differently:
        - UserProfileStore uses user_id
        - SessionContextStore uses session_id
        - LearningsStore uses message for semantic search

        Args:
            **context: Arbitrary context. Common keys:
                - user_id: User identifier
                - session_id: Session identifier
                - agent_id: Agent identifier
                - team_id: Team identifier
                - message: Current message (for semantic search)

        Returns:
            Retrieved data (schema instance, list, etc.),
            or None if nothing found.

        Example:
            >>> store.recall(user_id="alice")
            UserProfile(user_id="alice", name="Alice", ...)
        """
        pass

    @abstractmethod
    async def arecall(self, **context) -> Optional[Any]:
        """Async version of recall."""
        pass

    # -------------------------------------------------------------------------
    # Required: Process
    # -------------------------------------------------------------------------

    @abstractmethod
    def process(self, **context) -> None:
        """Extract and save learnings to storage.

        Args:
            **context: Arbitrary context (messages, user_id, session_id, etc.)

        Example:
            >>> store.process(messages=messages, user_id="alice")
            # Extracts user info and saves to profile
        """
        pass

    @abstractmethod
    async def aprocess(self, **context) -> None:
        """Async version of process."""
        pass

    # -------------------------------------------------------------------------
    # Required: Build Context
    # -------------------------------------------------------------------------

    @abstractmethod
    def build_context(self, data: Any) -> str:
        """Build context for the agent.

        Takes data from recall() and builds a string to inject into
        the agent's system prompt. This could be:
        - Formatted data (UserProfile, SessionContext)
        - Instructions for using tools (Learnings in AGENTIC mode)
        - Any other context the agent needs

        Args:
            data: Data returned from recall(), or None.

        Returns:
            Context string (typically XML-formatted),
            or empty string if no context to add.

        Example - Data context:
            >>> store.build_context(profile)
            '<user_profile>\\nName: Alice\\n- Prefers concise answers\\n</user_profile>'

        Example - Instruction context:
            >>> store.build_context(None)
            '<learnings_instructions>\\nUse search_learnings to find relevant knowledge.\\n</learnings_instructions>'
        """
        pass

    # -------------------------------------------------------------------------
    # Optional: Agent Tools
    # -------------------------------------------------------------------------

    def get_tools(self, **context) -> List[Callable]:
        """Get tools to expose to agent.

        Override to provide agent tools for this learning type.

        Args:
            **context: Arbitrary context (user_id, session_id, etc.)

        Returns:
            List of callable tools, or empty list if none.

        Example:
            >>> tools = store.get_tools(user_id="alice")
            >>> [t.__name__ for t in tools]
            ['update_user_memory']
        """
        return []

    async def aget_tools(self, **context) -> List[Callable]:
        """Async version of get_tools.

        Default implementation calls sync version.
        Override if async tool creation is needed.
        """
        return self.get_tools(**context)

    # -------------------------------------------------------------------------
    # Optional: State Tracking
    # -------------------------------------------------------------------------

    @property
    def was_updated(self) -> bool:
        """Check if store was updated in last operation.

        Useful for knowing whether process() found new information.
        Override in subclass to track actual state.

        Returns:
            True if last process() call made changes, False otherwise.
        """
        return False
