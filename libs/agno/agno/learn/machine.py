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
    LearningsConfig,
    SessionContextConfig,
    UserProfileConfig,
)
from agno.learn.stores.protocol import LearningStore
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
    """Coordinates multiple learning stores for agent memory.

    Args:
        db: Database backend for persistence.
        model: Model for extraction.
        user_profile: Enable user profile (bool or UserProfileConfig).
        session_context: Enable session context (bool or SessionContextConfig).
        learnings: Enable learnings (bool or LearningsConfig).
        custom_stores: Additional stores implementing LearningStore protocol.
        debug_mode: Enable debug logging.
    """

    # Dependencies
    db: Optional[Union["BaseDb", "AsyncBaseDb"]] = None
    model: Optional["Model"] = None

    # Store configurations (bool = use defaults, Config = custom settings)
    user_profile: Union[bool, UserProfileConfig, None] = True
    session_context: Union[bool, SessionContextConfig, None] = True
    learnings: Union[bool, LearningsConfig, None] = False

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

        if self.user_profile:
            self._stores["user_profile"] = self._create_user_profile_store()

        if self.session_context:
            self._stores["session_context"] = self._create_session_context_store()

        if self.learnings:
            self._stores["learnings"] = self._create_learnings_store()

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
            if config.db is None:
                config.db = self.db
            if config.model is None:
                config.model = self.model
        else:
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

    def _create_learnings_store(self) -> "LearningStore":
        """Create LearningsStore with resolved config."""
        from agno.learn.stores.learnings import LearningsStore

        if isinstance(self.learnings, LearningsConfig):
            config = self.learnings
            if config.model is None:
                config.model = self.model
        else:
            config = LearningsConfig(
                model=self.model,
                mode=LearningMode.AGENTIC,
            )

        return LearningsStore(config=config, debug_mode=self.debug_mode)

    # =========================================================================
    # Store Access
    # =========================================================================

    @property
    def stores(self) -> Dict[str, LearningStore]:
        """All registered stores, keyed by name."""
        return self._stores

    @property
    def was_updated(self) -> bool:
        """True if any store was updated in the last operation."""
        return any(store.was_updated for store in self._stores.values() if hasattr(store, "was_updated"))

    # =========================================================================
    # Main API
    # =========================================================================

    def build_context(
        self,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
        **kwargs,
    ) -> str:
        """Build memory context for the agent's system prompt.

        This is the main method for retrieving memories. Call before generating
        a response to give the agent context about the user, session, and
        relevant learnings.

        Args:
            user_id: User identifier (for user profile lookup).
            session_id: Session identifier (for session context lookup).
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
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
        **kwargs,
    ) -> str:
        """Async version of build_context."""
        results = await self.arecall(
            user_id=user_id,
            session_id=session_id,
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
        """Get memory tools to expose to the agent.

        Returns tools like `update_user_memory`, `search_learnings`, etc.
        depending on which stores are enabled and their configurations.

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

    def process(
        self,
        messages: List[Any],
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
        **kwargs,
    ) -> None:
        """Extract and save memories from a conversation.

        Call after a conversation to extract user profile info, session
        context, and learnings. Each store processes according to its
        mode (BACKGROUND, AGENTIC, etc.).

        Args:
            messages: Conversation messages to analyze.
            user_id: User identifier (for user profile extraction).
            session_id: Session identifier (for session context extraction).
            agent_id: Optional agent context.
            team_id: Optional team context.

        Example:
            >>> learning.process(
            ...     messages=conversation.messages,
            ...     user_id="alice",
            ...     session_id="sess-123",
            ... )
            >>> learning.was_updated
            True
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

    def _format_results(self, results: Dict[str, Any]) -> str:
        """Format recalled data into context string."""
        parts = []

        for name, data in results.items():
            store = self._stores.get(name)
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
