"""
Learning Machine
================
Orchestrator for all learning types.

The LearningMachine coordinates multiple learning stores:
- UserProfileStore: Long-term memories about users (ACCUMULATES)
- SessionContextStore: Current session state (REPLACES)
- KnowledgeStore: Reusable insights (SEMANTIC SEARCH)

Three DX levels:
1. Dead Simple: `Agent(learning=True)` - just works
2. Pick What You Want: `LearningMachine(user_profile=True, session_context=True)`
3. Full Control: `LearningMachine(user_profile=UserProfileConfig(...))`

Extensibility:
- Register custom stores via `register(name, store)`
- Custom stores implement the LearningStore protocol
"""

from dataclasses import dataclass, field
from os import getenv
from textwrap import dedent
from typing import Any, Callable, Dict, List, Optional, Union

from agno.learn.config import (
    ExtractionTiming,
    KnowledgeConfig,
    LearningMode,
    SessionContextConfig,
    UserProfileConfig,
)
from agno.learn.stores.base import LearningStore
from agno.utils.log import (
    log_debug,
    log_warning,
    set_log_level_to_debug,
    set_log_level_to_info,
)

# Conditional imports
try:
    from agno.db.base import AsyncBaseDb, BaseDb
    from agno.models.base import Model
except ImportError:
    pass


@dataclass
class LearningMachine:
    """Orchestrator for all learning types.

    Coordinates multiple learning stores and provides a unified interface
    for recall, processing, and tool aggregation.

    Usage:
        # Level 1: Dead Simple (use defaults)
        learning = LearningMachine(db=db, model=model)

        # Level 2: Pick What You Want
        learning = LearningMachine(
            db=db,
            model=model,
            user_profile=True,
            session_context=True,
            learned_knowledge=False,
        )

        # Level 3: Full Control
        learning = LearningMachine(
            db=db,
            model=model,
            user_profile=UserProfileConfig(
                mode=LearningMode.BACKGROUND,
                enable_tool=True,
            ),
            session_context=SessionContextConfig(
                enable_planning=True,
            ),
        )

        # With custom stores
        learning = LearningMachine(
            db=db,
            model=model,
            custom_stores={
                "project": ProjectContextStore(config=...),
            },
        )

    Args:
        db: Database backend for persistence.
        model: Model for extraction.
        user_profile: Enable user profile learning (bool or config).
        session_context: Enable session context learning (bool or config).
        learned_knowledge: Enable knowledge learning (bool or config).
        custom_stores: Dict of custom stores to register.
        debug_mode: Enable debug logging.
    """

    # Dependencies
    db: Optional[Union["BaseDb", "AsyncBaseDb"]] = None
    model: Optional["Model"] = None

    # Store configurations (bool = use defaults, Config = custom settings)
    user_profile: Union[bool, UserProfileConfig, None] = True
    session_context: Union[bool, SessionContextConfig, None] = True
    learned_knowledge: Union[bool, KnowledgeConfig, None] = False

    # Custom stores
    custom_stores: Optional[Dict[str, LearningStore]] = None

    # Debug mode
    debug_mode: bool = False

    # Internal state
    _stores: Dict[str, LearningStore] = field(default_factory=dict, init=False)
    _initialized: bool = field(default=False, init=False)

    def __post_init__(self):
        self._initialize_stores()

    # =========================================================================
    # Initialization
    # =========================================================================

    def _initialize_stores(self) -> None:
        """Initialize all configured stores."""
        if self._initialized:
            return

        # Initialize user profile store
        if self.user_profile:
            self._stores["user_profile"] = self._create_user_profile_store()

        # Initialize session context store
        if self.session_context:
            self._stores["session_context"] = self._create_session_context_store()

        # Initialize knowledge store
        if self.learned_knowledge:
            self._stores["learned_knowledge"] = self._create_knowledge_store()

        # Register custom stores
        if self.custom_stores:
            for name, store in self.custom_stores.items():
                self._stores[name] = store

        self._initialized = True
        log_debug(f"LearningMachine initialized with stores: {list(self._stores.keys())}")

    def _create_user_profile_store(self) -> "LearningStore":
        """Create UserProfileStore with resolved config."""
        from agno.learn.stores.user import UserProfileStore

        if isinstance(self.user_profile, UserProfileConfig):
            config = self.user_profile
            # Inject db/model if not set
            if config.db is None:
                config.db = self.db
            if config.model is None:
                config.model = self.model
        else:
            # Default config
            config = UserProfileConfig(
                db=self.db,
                model=self.model,
                mode=LearningMode.BACKGROUND,
                enable_tool=True,
            )

        return UserProfileStore(config=config, debug_mode=self.debug_mode)

    def _create_session_context_store(self) -> "LearningStore":
        """Create SessionContextStore with resolved config."""
        from agno.learn.stores.session import SessionContextStore

        if isinstance(self.session_context, SessionContextConfig):
            config = self.session_context
            # Inject db/model if not set
            if config.db is None:
                config.db = self.db
            if config.model is None:
                config.model = self.model
        else:
            # Default config
            config = SessionContextConfig(
                db=self.db,
                model=self.model,
                enable_planning=False,
            )

        return SessionContextStore(config=config, debug_mode=self.debug_mode)

    def _create_knowledge_store(self) -> "LearningStore":
        """Create KnowledgeStore with resolved config."""
        from agno.learn.stores.knowledge import KnowledgeStore

        if isinstance(self.learned_knowledge, KnowledgeConfig):
            config = self.learned_knowledge
            # Inject model if not set
            if config.model is None:
                config.model = self.model
        else:
            # Default config (requires knowledge base to be useful)
            config = KnowledgeConfig(
                model=self.model,
                mode=LearningMode.AGENTIC,
                enable_tool=True,
            )

        return KnowledgeStore(config=config, debug_mode=self.debug_mode)

    # =========================================================================
    # Debug/Logging
    # =========================================================================

    def set_log_level(self) -> None:
        """Set log level based on debug_mode or environment variable."""
        if self.debug_mode or getenv("AGNO_DEBUG", "false").lower() == "true":
            self.debug_mode = True
            set_log_level_to_debug()
        else:
            set_log_level_to_info()

    # =========================================================================
    # Store Access
    # =========================================================================

    @property
    def stores(self) -> Dict[str, LearningStore]:
        """Get all registered stores."""
        return self._stores

    @property
    def user_profile_store(self) -> Optional["LearningStore"]:
        """Get the user profile store if enabled."""
        return self._stores.get("user_profile")

    @property
    def session_context_store(self) -> Optional["LearningStore"]:
        """Get the session context store if enabled."""
        return self._stores.get("session_context")

    @property
    def knowledge_store(self) -> Optional["LearningStore"]:
        """Get the knowledge store if enabled."""
        return self._stores.get("learned_knowledge")

    def get_store(self, name: str) -> Optional[LearningStore]:
        """Get a store by name.

        Args:
            name: Store name (e.g., "user_profile", "session_context", or custom).

        Returns:
            The store, or None if not found.
        """
        return self._stores.get(name)

    def register(self, name: str, store: LearningStore) -> None:
        """Register a custom store.

        Args:
            name: Unique name for the store.
            store: Store instance implementing LearningStore protocol.
        """
        self._stores[name] = store
        log_debug(f"Registered custom store: {name}")

    def unregister(self, name: str) -> bool:
        """Unregister a store.

        Args:
            name: Name of the store to remove.

        Returns:
            True if removed, False if not found.
        """
        if name in self._stores:
            del self._stores[name]
            log_debug(f"Unregistered store: {name}")
            return True
        return False

    # =========================================================================
    # State Tracking
    # =========================================================================

    @property
    def profile_updated(self) -> bool:
        """Check if user profile was updated in last operation."""
        store = self.user_profile_store
        return store.was_updated if store else False

    @property
    def context_updated(self) -> bool:
        """Check if session context was updated in last operation."""
        store = self.session_context_store
        return store.was_updated if store else False

    @property
    def learning_saved(self) -> bool:
        """Check if knowledge was saved in last operation."""
        store = self.knowledge_store
        return store.was_updated if store else False

    @property
    def was_updated(self) -> bool:
        """Check if any store was updated in last operation."""
        return any(store.was_updated for store in self._stores.values() if hasattr(store, "was_updated"))

    # =========================================================================
    # Core Operations
    # =========================================================================

    def recall(
        self,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        message: Optional[str] = None,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
        **kwargs,
    ) -> Dict[str, Any]:
        """Retrieve learnings from all stores.

        Args:
            user_id: User identifier for profile lookup.
            session_id: Session identifier for context lookup.
            message: Current message for knowledge search.
            agent_id: Optional agent context.
            team_id: Optional team context.
            **kwargs: Additional context passed to stores.

        Returns:
            Dict mapping store names to their recalled data.
        """
        results = {}

        context = {
            "user_id": user_id,
            "session_id": session_id,
            "message": message,
            "agent_id": agent_id,
            "team_id": team_id,
            **kwargs,
        }

        for name, store in self._stores.items():
            try:
                result = store.recall(**context)
                if result is not None:
                    results[name] = result
                    log_debug(f"Recalled from {name}: {type(result)}")
            except Exception as e:
                log_warning(f"Error recalling from {name}: {e}")

        return results

    async def arecall(
        self,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        message: Optional[str] = None,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
        **kwargs,
    ) -> Dict[str, Any]:
        """Async version of recall."""
        results = {}

        context = {
            "user_id": user_id,
            "session_id": session_id,
            "message": message,
            "agent_id": agent_id,
            "team_id": team_id,
            **kwargs,
        }

        for name, store in self._stores.items():
            try:
                result = await store.arecall(**context)
                if result is not None:
                    results[name] = result
                    log_debug(f"Recalled from {name}: {type(result)}")
            except Exception as e:
                log_warning(f"Error recalling from {name}: {e}")

        return results

    def process(
        self,
        messages: List[Any],
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
        **kwargs,
    ) -> None:
        """Process messages through all stores for extraction.

        Args:
            messages: Conversation messages to analyze.
            user_id: User identifier for profile extraction.
            session_id: Session identifier for context extraction.
            agent_id: Optional agent context.
            team_id: Optional team context.
            **kwargs: Additional context passed to stores.
        """
        context = {
            "messages": messages,
            "user_id": user_id,
            "session_id": session_id,
            "agent_id": agent_id,
            "team_id": team_id,
            **kwargs,
        }

        for name, store in self._stores.items():
            try:
                store.process(**context)
                log_debug(f"Processed through {name}")
            except Exception as e:
                log_warning(f"Error processing through {name}: {e}")

    async def aprocess(
        self,
        messages: List[Any],
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
        **kwargs,
    ) -> None:
        """Async version of process."""
        context = {
            "messages": messages,
            "user_id": user_id,
            "session_id": session_id,
            "agent_id": agent_id,
            "team_id": team_id,
            **kwargs,
        }

        for name, store in self._stores.items():
            try:
                await store.aprocess(**context)
                log_debug(f"Processed through {name}")
            except Exception as e:
                log_warning(f"Error processing through {name}: {e}")

    def get_tools(
        self,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
        **kwargs,
    ) -> List[Callable]:
        """Get tools from all stores to expose to agent.

        Args:
            user_id: User identifier for user profile tool.
            session_id: Session identifier (not typically used).
            agent_id: Optional agent context.
            team_id: Optional team context.
            **kwargs: Additional context passed to stores.

        Returns:
            List of all tools from all stores.
        """
        tools = []

        context = {
            "user_id": user_id,
            "session_id": session_id,
            "agent_id": agent_id,
            "team_id": team_id,
            **kwargs,
        }

        for name, store in self._stores.items():
            try:
                store_tools = store.get_tools(**context)
                if store_tools:
                    tools.extend(store_tools)
                    log_debug(f"Got {len(store_tools)} tools from {name}")
            except Exception as e:
                log_warning(f"Error getting tools from {name}: {e}")

        return tools

    async def aget_tools(
        self,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
        **kwargs,
    ) -> List[Callable]:
        """Async version of get_tools."""
        tools = []

        context = {
            "user_id": user_id,
            "session_id": session_id,
            "agent_id": agent_id,
            "team_id": team_id,
            **kwargs,
        }

        for name, store in self._stores.items():
            try:
                store_tools = await store.aget_tools(**context)
                if store_tools:
                    tools.extend(store_tools)
                    log_debug(f"Got {len(store_tools)} tools from {name}")
            except Exception as e:
                log_warning(f"Error getting tools from {name}: {e}")

        return tools

    # =========================================================================
    # Formatting
    # =========================================================================

    def format_recall_for_context(self, results: Dict[str, Any]) -> str:
        """Format recalled data for system prompt injection.

        Args:
            results: Dict from recall() method.

        Returns:
            Formatted string suitable for system prompts.
        """
        parts = []

        for name, data in results.items():
            store = self._stores.get(name)
            if store and data:
                try:
                    formatted = store.format_for_prompt(data=data)
                    if formatted:
                        parts.append(formatted)
                except Exception as e:
                    log_warning(f"Error formatting {name}: {e}")

        return "\n\n".join(parts)

    def get_system_prompt_injection(
        self,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        message: Optional[str] = None,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
        **kwargs,
    ) -> str:
        """Get formatted learnings for system prompt injection.

        Convenience method that combines recall + format.

        Args:
            user_id: User identifier for profile lookup.
            session_id: Session identifier for context lookup.
            message: Current message for knowledge search.
            agent_id: Optional agent context.
            team_id: Optional team context.
            **kwargs: Additional context.

        Returns:
            Formatted string for system prompt injection.
        """
        results = self.recall(
            user_id=user_id,
            session_id=session_id,
            message=message,
            agent_id=agent_id,
            team_id=team_id,
            **kwargs,
        )

        if not results:
            return ""

        return self.format_recall_for_context(results=results)

    async def aget_system_prompt_injection(
        self,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        message: Optional[str] = None,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
        **kwargs,
    ) -> str:
        """Async version of get_system_prompt_injection."""
        results = await self.arecall(
            user_id=user_id,
            session_id=session_id,
            message=message,
            agent_id=agent_id,
            team_id=team_id,
            **kwargs,
        )

        if not results:
            return ""

        return self.format_recall_for_context(results=results)

    # =========================================================================
    # Lifecycle Hooks
    # =========================================================================

    def on_conversation_start(
        self,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        **kwargs,
    ) -> None:
        """Called when a conversation starts.

        Args:
            user_id: User identifier.
            session_id: Session identifier.
            **kwargs: Additional context.
        """
        for name, store in self._stores.items():
            if hasattr(store, "on_conversation_start"):
                try:
                    store.on_conversation_start(
                        user_id=user_id,
                        session_id=session_id,
                        **kwargs,
                    )
                except Exception as e:
                    log_warning(f"Error in {name}.on_conversation_start: {e}")

    def on_conversation_end(
        self,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        messages: Optional[List[Any]] = None,
        **kwargs,
    ) -> None:
        """Called when a conversation ends.

        Args:
            user_id: User identifier.
            session_id: Session identifier.
            messages: Full conversation messages.
            **kwargs: Additional context.
        """
        for name, store in self._stores.items():
            if hasattr(store, "on_conversation_end"):
                try:
                    store.on_conversation_end(
                        user_id=user_id,
                        session_id=session_id,
                        messages=messages,
                        **kwargs,
                    )
                except Exception as e:
                    log_warning(f"Error in {name}.on_conversation_end: {e}")


# =========================================================================
# Factory Function
# =========================================================================


def create_learning_machine(
    db: Optional[Union["BaseDb", "AsyncBaseDb"]] = None,
    model: Optional["Model"] = None,
    user_profile: Union[bool, UserProfileConfig, None] = True,
    session_context: Union[bool, SessionContextConfig, None] = True,
    learned_knowledge: Union[bool, KnowledgeConfig, None] = False,
    custom_stores: Optional[Dict[str, LearningStore]] = None,
    debug_mode: bool = False,
) -> LearningMachine:
    """Factory function to create a LearningMachine.

    Args:
        db: Database backend for persistence.
        model: Model for extraction.
        user_profile: Enable user profile learning (bool or config).
        session_context: Enable session context learning (bool or config).
        learned_knowledge: Enable knowledge learning (bool or config).
        custom_stores: Dict of custom stores to register.
        debug_mode: Enable debug logging.

    Returns:
        Configured LearningMachine instance.
    """
    return LearningMachine(
        db=db,
        model=model,
        user_profile=user_profile,
        session_context=session_context,
        learned_knowledge=learned_knowledge,
        custom_stores=custom_stores,
        debug_mode=debug_mode,
    )
