"""
Base Learning Store
===================
Protocol and utilities for all learning stores - built-in and custom.

The LearningStore protocol defines 4 required methods:
- recall(): Retrieve relevant data for context injection
- process(): Extract learnings from conversation
- format_for_prompt(): Format data for system prompt
- learning_type: String identifier for this learning type

Plus optional methods:
- get_tools(): Return tools to expose to agent
- was_updated: Check if store was updated in last operation
"""

from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, fields
from typing import Any, Callable, Dict, List, Optional, Type, TypeVar

T = TypeVar("T")


# =============================================================================
# Helper Functions
# =============================================================================


def from_dict_safe(cls: Type[T], data: Any) -> Optional[T]:
    """Safely create a dataclass instance from dict-like data.

    Works with any dataclass - automatically handles subclass fields.
    Never raises - returns None on any failure.

    Args:
        cls: The dataclass type to instantiate.
        data: Dict, JSON string, or existing instance.

    Returns:
        Instance of cls, or None if parsing fails.

    Example:
        >>> profile = from_dict_safe(BaseUserProfile, {"user_id": "123"})
        >>> profile.user_id
        '123'
    """
    if data is None:
        return None

    # Already the right type
    if isinstance(data, cls):
        return data

    try:
        # Parse JSON string if needed
        parsed = _parse_json(data)
        if parsed is None:
            return None

        # Get valid field names for this class
        field_names = {f.name for f in fields(cls)}

        # Filter to only valid fields
        kwargs = {k: v for k, v in parsed.items() if k in field_names}

        return cls(**kwargs)
    except Exception:
        return None


def to_dict_safe(obj: Any) -> Optional[Dict[str, Any]]:
    """Safely convert a dataclass to dict.

    Works with any dataclass. Never raises - returns None on failure.

    Args:
        obj: Dataclass instance to convert.

    Returns:
        Dict representation, or None if conversion fails.

    Example:
        >>> profile = BaseUserProfile(user_id="123")
        >>> to_dict_safe(profile)
        {'user_id': '123', 'name': None, ...}
    """
    if obj is None:
        return None

    try:
        # Already a dict
        if isinstance(obj, dict):
            return obj

        # Has to_dict method
        if hasattr(obj, "to_dict"):
            return obj.to_dict()

        # Is a dataclass
        if hasattr(obj, "__dataclass_fields__"):
            return asdict(obj)

        # Has __dict__
        if hasattr(obj, "__dict__"):
            return dict(obj.__dict__)

        return None
    except Exception:
        return None


def _parse_json(data: Any) -> Optional[Dict]:
    """Parse JSON string to dict, or return dict as-is."""
    if data is None:
        return None
    if isinstance(data, dict):
        return data
    if isinstance(data, str):
        import json

        try:
            return json.loads(data)
        except Exception:
            return None
    return None


# =============================================================================
# Base Learning Store Protocol
# =============================================================================


@dataclass
class LearningStore(ABC):
    """Base protocol for all learning stores.

    To create a custom learning type, subclass this and implement:
    - recall(): Retrieve relevant data for context injection
    - arecall(): Async version of recall
    - process(): Extract learnings from conversation
    - aprocess(): Async version of process
    - format_for_prompt(): Format data for system prompt
    - learning_type: Property returning string identifier

    Optional overrides:
    - get_tools(): Return tools to expose to agent
    - aget_tools(): Async version of get_tools
    - was_updated: Check if store was updated

    Example - Custom Project Context Store:
    ```python
    @dataclass
    class ProjectContextStore(LearningStore):
        config: ProjectContextConfig = field(default_factory=ProjectContextConfig)

        @property
        def learning_type(self) -> str:
            return "project_context"

        def recall(self, project_id: str = None, **kwargs) -> Optional[ProjectContext]:
            if not project_id:
                return None
            return self.get(project_id)

        async def arecall(self, project_id: str = None, **kwargs) -> Optional[ProjectContext]:
            if not project_id:
                return None
            return await self.aget(project_id)

        def process(self, messages: List[Message], project_id: str = None, **kwargs) -> None:
            if project_id:
                self.extract_and_save(messages, project_id)

        async def aprocess(self, messages: List[Message], project_id: str = None, **kwargs) -> None:
            if project_id:
                await self.aextract_and_save(messages, project_id)

        def format_for_prompt(self, data: ProjectContext) -> str:
            return f"<project_context>\\n{data.to_text()}\\n</project_context>"

        def get_tools(self, project_id: str = None, **kwargs) -> List[Callable]:
            if not project_id:
                return []
            return [self.get_update_tool(project_id)]
    ```
    """

    # -------------------------------------------------------------------------
    # Required: Core Protocol
    # -------------------------------------------------------------------------

    @property
    @abstractmethod
    def learning_type(self) -> str:
        """String identifier for this learning type.

        Used for database storage and debugging.
        Examples: "user_profile", "session_context", "project_context"
        """
        pass

    @abstractmethod
    def recall(self, **context) -> Optional[Any]:
        """Retrieve relevant learnings given context.

        Called before agent runs to inject context into prompt.

        Args:
            **context: Arbitrary context (user_id, session_id, project_id, etc.)
                      Each store uses the context keys it needs.

        Returns:
            Retrieved data (schema instance), or None if nothing found.

        Example:
            >>> store.recall(user_id="alice", agent_id="support")
            BaseUserProfile(user_id="alice", memories=[...])
        """
        pass

    @abstractmethod
    async def arecall(self, **context) -> Optional[Any]:
        """Async version of recall."""
        pass

    @abstractmethod
    def process(self, messages: List[Any], **context) -> None:
        """Extract and save learnings from messages.

        Called after agent runs to update learnings based on conversation.

        Args:
            messages: Conversation messages to analyze.
            **context: Arbitrary context (user_id, session_id, etc.)

        Example:
            >>> store.process(messages, user_id="alice")
            # Extracts user info and saves to profile
        """
        pass

    @abstractmethod
    async def aprocess(self, messages: List[Any], **context) -> None:
        """Async version of process."""
        pass

    @abstractmethod
    def format_for_prompt(self, data: Any) -> str:
        """Format recalled data for system prompt injection.

        Takes the data returned by recall() and formats it as XML
        suitable for including in a system prompt.

        Args:
            data: Data returned from recall().

        Returns:
            Formatted string with XML tags, or empty string if no data.

        Example:
            >>> store.format_for_prompt(profile)
            '<user_profile>\\nUser is a software engineer...\\n</user_profile>'
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
            >>> tools[0].__name__
            'update_user_memory'
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

        Useful for knowing whether extraction found new information.
        Override in subclass to track actual state.

        Returns:
            True if last process() call made changes, False otherwise.
        """
        return False

    # -------------------------------------------------------------------------
    # Optional: Lifecycle Hooks
    # -------------------------------------------------------------------------

    def on_conversation_start(self, **context) -> None:
        """Called when a new conversation starts.

        Override for setup logic like loading initial state.
        """
        pass

    def on_conversation_end(self, **context) -> None:
        """Called when conversation ends.

        Override for cleanup logic like final extraction.
        """
        pass
