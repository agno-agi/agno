"""
Learning Machine
================
Gives agents learning capabilities.
"""

from dataclasses import dataclass, field
from os import getenv
from typing import Any, Callable, Dict, List, Optional, Union

from agno.learn.config import (
    LearningMode,
    UserProfileConfig,
    EntityMemoryConfig,
    LearnedKnowledgeConfig,
    SessionContextConfig,
)
from agno.learn.stores.protocol import LearningStore
from agno.utils.log import (
    log_debug,
    log_warning,
    set_log_level_to_debug,
    set_log_level_to_info,
)

try:
    from agno.db.base import AsyncBaseDb, BaseDb
    from agno.models.base import Model
except ImportError:
    pass

# Type aliases for cleaner signatures (Store types imported lazily)
UserProfileInput = Union[bool, UserProfileConfig, LearningStore, None]
EntityMemoryInput = Union[bool, EntityMemoryConfig, LearningStore, None]
SessionContextInput = Union[bool, SessionContextConfig, LearningStore, None]
LearnedKnowledgeInput = Union[bool, LearnedKnowledgeConfig, LearningStore, None]


@dataclass
class LearningMachine:
    """Central orchestrator for agent learning.

    Coordinates all learning stores and provides unified interface
    for recall, processing, and tool generation.

    Args:
        db: Database backend for persistence.
        model: Model for learning extraction.
        knowledge: Knowledge base for learned knowledge store. When provided, automatically
                   enables the learned_knowledge store if not explicitly disabled.
        user_profile: Enable user profile. Accepts:
                      - bool: True = defaults, False/None = disabled
                      - UserProfileConfig: Custom configuration
                      - UserProfileStore: Use provided store directly
        session_context: Enable session context. Accepts:
                         - bool: True = defaults, False/None = disabled
                         - SessionContextConfig: Custom configuration
                         - SessionContextStore: Use provided store directly
        learned_knowledge: Enable learned knowledge. Accepts:
                           - bool: True = defaults, False/None = disabled
                           - LearnedKnowledgeConfig: Custom configuration
                           - LearnedKnowledgeStore: Use provided store directly
                           Auto-enabled when knowledge is provided.
        custom_stores: Additional stores implementing LearningStore protocol.
        debug_mode: Enable debug logging.
    """

    db: Optional[Union["BaseDb", "AsyncBaseDb"]] = None
    model: Optional["Model"] = None
    knowledge: Optional[Any] = None

    # Store configurations
    user_profile: UserProfileInput = True
    session_context: SessionContextInput = False
    learned_knowledge: LearnedKnowledgeInput = False

    # Custom stores
    custom_stores: Optional[Dict[str, LearningStore]] = None

    # Debug mode
    debug_mode: bool = False

    # Internal state (lazy initialization)
    _stores: Optional[Dict[str, LearningStore]] = field(default=None, init=False)

    # =========================================================================
    # Initialization (Lazy)
    # =========================================================================

    @property
    def stores(self) -> Dict[str, LearningStore]:
        """All registered stores, keyed by name. Lazily initialized on first access."""
        if self._stores is None:
            self._initialize_stores()
        return self._stores  # type: ignore

    def _initialize_stores(self) -> None:
        """Initialize all configured stores.

        For each store type, accepts:
        - bool: True = create with defaults, False/None = disabled
        - Config: Create store with custom configuration
        - Store: Use provided store instance directly
        """
        self._stores = {}

        if self.user_profile:
            if isinstance(self.user_profile, LearningStore):
                # Store instance provided directly
                self._stores["user_profile"] = self.user_profile
            else:
                # Bool or Config - create the store
                self._stores["user_profile"] = self._create_user_profile_store()

        if self.session_context:
            if isinstance(self.session_context, LearningStore):
                # Store instance provided directly
                self._stores["session_context"] = self.session_context
            else:
                # Bool or Config - create the store
                self._stores["session_context"] = self._create_session_context_store()

        # Auto-enable learned_knowledge if knowledge is provided
        if self.learned_knowledge or self.knowledge is not None:
            if isinstance(self.learned_knowledge, LearningStore):
                # Store instance provided directly
                self._stores["learned_knowledge"] = self.learned_knowledge
            else:
                # Bool or Config - create the store
                self._stores["learned_knowledge"] = self._create_learned_knowledge_store()

        if self.custom_stores:
            for name, store in self.custom_stores.items():
                self._stores[name] = store

        log_debug(f"LearningMachine initialized with stores: {list(self._stores.keys())}")

    def _create_user_profile_store(self) -> "LearningStore":
        """Create UserProfileStore with resolved config."""
        from agno.learn.stores import UserProfileStore

        if isinstance(self.user_profile, UserProfileConfig):
            config = self.user_profile
            if config.db is None:
                config.db = self.db
            if config.model is None:
                config.model = self.model
        else:
            config = UserProfileConfig(
                db=self.db,
                model=self.model,
                mode=LearningMode.BACKGROUND,
            )

        return UserProfileStore(config=config, debug_mode=self.debug_mode)

    def _create_session_context_store(self) -> "LearningStore":
        """Create SessionContextStore with resolved config."""
        from agno.learn.stores import SessionContextStore

        if isinstance(self.session_context, SessionContextConfig):
            config = self.session_context
            if config.db is None:
                config.db = self.db
            if config.model is None:
                config.model = self.model
        else:
            config = SessionContextConfig(
                db=self.db,
                model=self.model,
                enable_planning=False,
            )

        return SessionContextStore(config=config, debug_mode=self.debug_mode)

    def _create_learned_knowledge_store(self) -> "LearningStore":
        """Create LearnedKnowledgeStore with resolved config."""
        from agno.learn.stores import LearnedKnowledgeStore

        if isinstance(self.learned_knowledge, LearnedKnowledgeConfig):
            config = self.learned_knowledge
            if config.model is None:
                config.model = self.model
            # Use top-level knowledge as fallback
            if config.knowledge is None and self.knowledge is not None:
                config.knowledge = self.knowledge
        else:
            config = LearnedKnowledgeConfig(
                model=self.model,
                knowledge=self.knowledge,  # Use top-level knowledge
                mode=LearningMode.AGENTIC,
            )

        return LearnedKnowledgeStore(config=config, debug_mode=self.debug_mode)

    # =========================================================================
    # Store Access
    # =========================================================================

    @property
    def was_updated(self) -> bool:
        """True if any store was updated in the last operation."""
        return any(store.was_updated for store in self.stores.values() if hasattr(store, "was_updated"))

    # =========================================================================
    # Main API
    # =========================================================================

    def build_context(
        self,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        message: Optional[str] = None,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
        **kwargs,
    ) -> str:
        """Build memory context for the agent's system prompt.
        Call before generating a response to give the agent context about relevant learnings.

        Args:
            user_id: User identifier (for user profile lookup).
            session_id: Session identifier (for session context lookup).
            message: Current message (for semantic search of learnings).
            agent_id: Optional agent context.
            team_id: Optional team context.

        Returns:
            Formatted context string to append to system prompt.

        Example:
            >>> context = learning.build_context(
            ...     user_id="alice",
            ...     session_id="sess-123",
            ...     message="How do I optimize async code?",
            ... )
            >>> print(context)
            <user_profile>
            What you know about this user:
            - User is a Python developer
            - User prefers concise explanations
            </user_profile>

            <session_context>
            Earlier in this session:
            User asked about Python best practices...
            </session_context>
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

        return self._format_results(results)

    async def abuild_context(
        self,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        message: Optional[str] = None,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
        **kwargs,
    ) -> str:
        """Async version of build_context."""
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

        return self._format_results(results)

    def get_tools(
        self,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
        **kwargs,
    ) -> List[Callable]:
        """Get learning tools to expose to the agent.
        Returns tools like `update_user_memory`, `search_learnings`, etc. depending on which stores are enabled.

        Args:
            user_id: User identifier (required for user profile tool).
            session_id: Session identifier.
            agent_id: Optional agent context.
            team_id: Optional team context.

        Returns:
            List of callable tools.

        Example:
            >>> tools = learning.get_tools(user_id="alice")
            >>> [t.__name__ for t in tools]
            ['update_user_memory', 'search_learnings', 'save_learning']
        """
        tools = []
        context = {
            "user_id": user_id,
            "session_id": session_id,
            "agent_id": agent_id,
            "team_id": team_id,
            **kwargs,
        }

        for name, store in self.stores.items():
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

        for name, store in self.stores.items():
            try:
                store_tools = await store.aget_tools(**context)
                if store_tools:
                    tools.extend(store_tools)
                    log_debug(f"Got {len(store_tools)} tools from {name}")
            except Exception as e:
                log_warning(f"Error getting tools from {name}: {e}")

        return tools

    def process(
        self,
        messages: List[Any],
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
        **kwargs,
    ) -> None:
        """Extract and save learnings from a conversation.
        Call after a conversation to extract learnings from enabled stores.

        Args:
            messages: Conversation messages to analyze.
            user_id: User identifier (for user profile extraction).
            session_id: Session identifier (for session context extraction).
            agent_id: Optional agent context.
            team_id: Optional team context.
        """
        context = {
            "messages": messages,
            "user_id": user_id,
            "session_id": session_id,
            "agent_id": agent_id,
            "team_id": team_id,
            **kwargs,
        }

        for name, store in self.stores.items():
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

        for name, store in self.stores.items():
            try:
                await store.aprocess(**context)
                log_debug(f"Processed through {name}")
            except Exception as e:
                log_warning(f"Error processing through {name}: {e}")

    # =========================================================================
    # Lower-Level API (for debugging/advanced use)
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
        """Retrieve raw data from all stores.

        Most users should use `build_context()` instead.
        This is useful for debugging or when you need the raw data.

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

        for name, store in self.stores.items():
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

        for name, store in self.stores.items():
            try:
                result = await store.arecall(**context)
                if result is not None:
                    results[name] = result
                    log_debug(f"Recalled from {name}: {type(result)}")
            except Exception as e:
                log_warning(f"Error recalling from {name}: {e}")

        return results

    def _format_results(self, results: Dict[str, Any]) -> str:
        """Format recalled data into context string."""
        parts = []

        for name, data in results.items():
            store = self.stores.get(name)
            if store and data is not None:
                try:
                    formatted = store.build_context(data=data)
                    if formatted:
                        parts.append(formatted)
                except Exception as e:
                    log_warning(f"Error building context from {name}: {e}")

        return "\n\n".join(parts)

    # =========================================================================
    # Debug
    # =========================================================================

    def set_log_level(self) -> None:
        """Set log level based on debug_mode or AGNO_DEBUG env var."""
        if self.debug_mode or getenv("AGNO_DEBUG", "false").lower() == "true":
            self.debug_mode = True
            set_log_level_to_debug()
        else:
            set_log_level_to_info()

    # =========================================================================
    # Representation
    # =========================================================================

    def __repr__(self) -> str:
        """String representation for debugging."""
        store_names = list(self.stores.keys()) if self._stores is not None else "[not initialized]"
        db_name = self.db.__class__.__name__ if self.db else None
        model_name = self.model.id if self.model and hasattr(self.model, "id") else None
        has_knowledge = self.knowledge is not None

        return f"LearningMachine(stores={store_names}, db={db_name}, model={model_name}, knowledge={has_knowledge})"
