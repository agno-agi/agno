"""
Learning Machine
================
Unified learning system for agents.

Coordinates multiple learning stores to give agents:
- User memory (who they're talking to)
- Session context (what's happened so far)
- Entity memory (knowledge about external things)
- Learned knowledge (reusable insights)

Plus maintenance via the Curator for keeping memories healthy.
"""

from dataclasses import dataclass, field
from os import getenv
from typing import Any, Callable, Dict, List, Optional, Union

from agno.learn.config import (
    DecisionLogConfig,
    EntityMemoryConfig,
    LearnedKnowledgeConfig,
    LearningMode,
    SessionContextConfig,
    UserMemoryConfig,
    UserProfileConfig,
)
from agno.learn.curate import Curator
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

# Type aliases for cleaner signatures
UserProfileInput = Union[bool, UserProfileConfig, LearningStore, None]
UserMemoryInput = Union[bool, UserMemoryConfig, LearningStore, None]
EntityMemoryInput = Union[bool, EntityMemoryConfig, LearningStore, None]
SessionContextInput = Union[bool, SessionContextConfig, LearningStore, None]
LearnedKnowledgeInput = Union[bool, LearnedKnowledgeConfig, LearningStore, None]
DecisionLogInput = Union[bool, DecisionLogConfig, LearningStore, None]


@dataclass
class LearningMachine:
    """Central orchestrator for agent learning.

    Coordinates all learning stores and provides unified interface
    for recall, processing, tool generation, and maintenance.

    Args:
        db: Database backend for persistence.
        model: Model for learning extraction.
        knowledge: Knowledge base for learned knowledge store.

        user_profile: Enable user profile. Accepts bool, Config, or Store.
        user_memory: Enable user memory. Accepts bool, Config, or Store.
        session_context: Enable session context. Accepts bool, Config, or Store.
        entity_memory: Enable entity memory. Accepts bool, Config, or Store.
        learned_knowledge: Enable learned knowledge. Auto-enabled when knowledge provided.

        namespace: Default namespace for entity_memory and learned_knowledge.
        custom_stores: Additional stores implementing LearningStore protocol.
        debug_mode: Enable debug logging.
    """

    db: Optional[Union["BaseDb", "AsyncBaseDb"]] = None
    model: Optional["Model"] = None
    knowledge: Optional[Any] = None

    # Store configurations (accepts bool, Config, or Store instance)
    user_profile: UserProfileInput = False
    user_memory: UserMemoryInput = False
    session_context: SessionContextInput = False
    entity_memory: EntityMemoryInput = False
    learned_knowledge: LearnedKnowledgeInput = False
    decision_log: DecisionLogInput = False  # Phase 2

    # Namespace for entity_memory and learned_knowledge
    namespace: str = "global"

    # Custom stores
    custom_stores: Optional[Dict[str, LearningStore]] = None

    # Debug mode
    debug_mode: bool = False

    # Internal state (lazy initialization)
    _stores: Optional[Dict[str, LearningStore]] = field(default=None, init=False)
    _curator: Optional[Any] = field(default=None, init=False)

    # =========================================================================
    # Initialization (Lazy)
    # =========================================================================

    @property
    def stores(self) -> Dict[str, LearningStore]:
        """All registered stores, keyed by name. Lazily initialized."""
        if self._stores is None:
            self._initialize_stores()
        return self._stores  # type: ignore

    def _initialize_stores(self) -> None:
        """Initialize all configured stores."""
        self._stores = {}

        # User Profile
        if self.user_profile:
            self._stores["user_profile"] = self._resolve_store(
                input_value=self.user_profile,
                store_type="user_profile",
            )

        # User Memory
        if self.user_memory:
            self._stores["user_memory"] = self._resolve_store(
                input_value=self.user_memory,
                store_type="user_memory",
            )

        # Session Context
        if self.session_context:
            self._stores["session_context"] = self._resolve_store(
                input_value=self.session_context,
                store_type="session_context",
            )

        # Entity Memory
        if self.entity_memory:
            self._stores["entity_memory"] = self._resolve_store(
                input_value=self.entity_memory,
                store_type="entity_memory",
            )

        # Learned Knowledge (auto-enable if knowledge provided)
        if self.learned_knowledge or self.knowledge is not None:
            self._stores["learned_knowledge"] = self._resolve_store(
                input_value=self.learned_knowledge if self.learned_knowledge else True,
                store_type="learned_knowledge",
            )

        # Decision Log (Phase 2)
        if self.decision_log:
            self._stores["decision_log"] = self._resolve_store(
                input_value=self.decision_log,
                store_type="decision_log",
            )

        # Custom stores
        if self.custom_stores:
            for name, store in self.custom_stores.items():
                self._stores[name] = store

        log_debug(f"LearningMachine initialized with stores: {list(self._stores.keys())}")

    def _resolve_store(
        self,
        input_value: Any,
        store_type: str,
    ) -> LearningStore:
        """Resolve input to a store instance.

        Args:
            input_value: bool, Config, or Store instance
            store_type: One of "user_profile", "user_memory", "session_context", "entity_memory", "learned_knowledge"

        Returns:
            Initialized store instance.
        """
        # Already a store instance
        if isinstance(input_value, LearningStore):
            return input_value

        # Create store based on type
        if store_type == "user_profile":
            return self._create_user_profile_store(config=input_value)
        elif store_type == "user_memory":
            return self._create_user_memory_store(config=input_value)
        elif store_type == "session_context":
            return self._create_session_context_store(config=input_value)
        elif store_type == "entity_memory":
            return self._create_entity_memory_store(config=input_value)
        elif store_type == "learned_knowledge":
            return self._create_learned_knowledge_store(config=input_value)
        elif store_type == "decision_log":
            return self._create_decision_log_store(config=input_value)
        else:
            raise ValueError(f"Unknown store type: {store_type}")

    def _create_user_profile_store(self, config: Any) -> LearningStore:
        """Create UserProfileStore with resolved config."""
        from agno.learn.stores import UserProfileStore

        if isinstance(config, UserProfileConfig):
            if config.db is None:
                config.db = self.db
            if config.model is None:
                config.model = self.model
        else:
            config = UserProfileConfig(
                db=self.db,
                model=self.model,
                mode=LearningMode.ALWAYS,
            )

        return UserProfileStore(config=config, debug_mode=self.debug_mode)

    def _create_user_memory_store(self, config: Any) -> LearningStore:
        """Create UserMemoryStore with resolved config."""
        from agno.learn.stores import UserMemoryStore

        if isinstance(config, UserMemoryConfig):
            if config.db is None:
                config.db = self.db
            if config.model is None:
                config.model = self.model
        else:
            config = UserMemoryConfig(
                db=self.db,
                model=self.model,
                mode=LearningMode.ALWAYS,
            )

        return UserMemoryStore(config=config, debug_mode=self.debug_mode)

    def _create_session_context_store(self, config: Any) -> LearningStore:
        """Create SessionContextStore with resolved config."""
        from agno.learn.stores import SessionContextStore

        if isinstance(config, SessionContextConfig):
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

    def _create_entity_memory_store(self, config: Any) -> LearningStore:
        """Create EntityMemoryStore with resolved config."""
        from agno.learn.stores import EntityMemoryStore

        if isinstance(config, EntityMemoryConfig):
            if config.db is None:
                config.db = self.db
            if config.model is None:
                config.model = self.model
        else:
            config = EntityMemoryConfig(
                db=self.db,
                model=self.model,
                namespace=self.namespace,
                mode=LearningMode.ALWAYS,
            )

        return EntityMemoryStore(config=config, debug_mode=self.debug_mode)

    def _create_learned_knowledge_store(self, config: Any) -> LearningStore:
        """Create LearnedKnowledgeStore with resolved config."""
        from agno.learn.stores import LearnedKnowledgeStore

        if isinstance(config, LearnedKnowledgeConfig):
            if config.model is None:
                config.model = self.model
            if config.knowledge is None and self.knowledge is not None:
                config.knowledge = self.knowledge
        else:
            config = LearnedKnowledgeConfig(
                model=self.model,
                knowledge=self.knowledge,
                mode=LearningMode.AGENTIC,
            )

        return LearnedKnowledgeStore(config=config, debug_mode=self.debug_mode)

    def _create_decision_log_store(self, config: Any) -> LearningStore:
        """Create DecisionLogStore with resolved config."""
        from agno.learn.stores import DecisionLogStore

        if isinstance(config, DecisionLogConfig):
            if config.db is None:
                config.db = self.db
            if config.model is None:
                config.model = self.model
        else:
            config = DecisionLogConfig(
                db=self.db,
                model=self.model,
                mode=LearningMode.AGENTIC,  # Default to AGENTIC for explicit logging
            )

        return DecisionLogStore(config=config, debug_mode=self.debug_mode)

    # =========================================================================
    # Store Accessors (Type-Safe)
    # =========================================================================

    @property
    def user_profile_store(self) -> Optional[LearningStore]:
        """Get user profile store if enabled."""
        return self.stores.get("user_profile")

    @property
    def user_memory_store(self) -> Optional[LearningStore]:
        """Get user memory store if enabled."""
        return self.stores.get("user_memory")

    @property
    def session_context_store(self) -> Optional[LearningStore]:
        """Get session context store if enabled."""
        return self.stores.get("session_context")

    @property
    def entity_memory_store(self) -> Optional[LearningStore]:
        """Get entity memory store if enabled."""
        return self.stores.get("entity_memory")

    @property
    def learned_knowledge_store(self) -> Optional[LearningStore]:
        """Get learned knowledge store if enabled."""
        return self.stores.get("learned_knowledge")

    @property
    def decision_log_store(self) -> Optional[LearningStore]:
        """Get decision log store if enabled."""
        return self.stores.get("decision_log")

    @property
    def was_updated(self) -> bool:
        """True if any store was updated in the last operation."""
        return any(getattr(store, "was_updated", False) for store in self.stores.values())

    # =========================================================================
    # Main API
    # =========================================================================

    def build_context(
        self,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        message: Optional[str] = None,
        entity_id: Optional[str] = None,
        entity_type: Optional[str] = None,
        namespace: Optional[str] = None,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
        **kwargs,
    ) -> str:
        """Build memory context for the agent's system prompt.

        Call before generating a response to give the agent relevant context.

        Args:
            user_id: User identifier (for user profile lookup).
            session_id: Session identifier (for session context lookup).
            message: Current message (for semantic search of learnings).
            entity_id: Entity to retrieve (for entity memory).
            entity_type: Type of entity to retrieve.
            namespace: Namespace filter for entity_memory and learned_knowledge.
            agent_id: Optional agent context.
            team_id: Optional team context.

        Returns:
            Context string to inject into the agent's system prompt.
        """
        results = self.recall(
            user_id=user_id,
            session_id=session_id,
            message=message,
            entity_id=entity_id,
            entity_type=entity_type,
            namespace=namespace or self.namespace,
            agent_id=agent_id,
            team_id=team_id,
            **kwargs,
        )

        return self._format_results(results=results)

    async def abuild_context(
        self,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        message: Optional[str] = None,
        entity_id: Optional[str] = None,
        entity_type: Optional[str] = None,
        namespace: Optional[str] = None,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
        **kwargs,
    ) -> str:
        """Async version of build_context."""
        results = await self.arecall(
            user_id=user_id,
            session_id=session_id,
            message=message,
            entity_id=entity_id,
            entity_type=entity_type,
            namespace=namespace or self.namespace,
            agent_id=agent_id,
            team_id=team_id,
            **kwargs,
        )

        return self._format_results(results=results)

    def get_tools(
        self,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        namespace: Optional[str] = None,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
        **kwargs,
    ) -> List[Callable]:
        """Get learning tools to expose to the agent.

        Returns tools based on which stores are enabled:
        - user_profile: update_user_memory
        - entity_memory: search_entities, create_entity, update_entity, add_fact, etc.
        - learned_knowledge: search_learnings, save_learning

        Args:
            user_id: User identifier (required for user profile tools).
            session_id: Session identifier.
            namespace: Default namespace for entity/learning operations.
            agent_id: Optional agent context.
            team_id: Optional team context.

        Returns:
            List of callable tools.
        """
        tools = []
        context = {
            "user_id": user_id,
            "session_id": session_id,
            "namespace": namespace or self.namespace,
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
        namespace: Optional[str] = None,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
        **kwargs,
    ) -> List[Callable]:
        """Async version of get_tools."""
        tools = []
        context = {
            "user_id": user_id,
            "session_id": session_id,
            "namespace": namespace or self.namespace,
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
        namespace: Optional[str] = None,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
        **kwargs,
    ) -> None:
        """Extract and save learnings from a conversation.

        Call after a conversation to extract learnings. Each store
        processes based on its mode (ALWAYS stores extract automatically).

        Args:
            messages: Conversation messages to analyze.
            user_id: User identifier (for user profile extraction).
            session_id: Session identifier (for session context extraction).
            namespace: Namespace for entity/learning saves.
            agent_id: Optional agent context.
            team_id: Optional team context.
        """
        context = {
            "messages": messages,
            "user_id": user_id,
            "session_id": session_id,
            "namespace": namespace or self.namespace,
            "agent_id": agent_id,
            "team_id": team_id,
            **kwargs,
        }

        for name, store in self.stores.items():
            try:
                store.process(**context)
                if getattr(store, "was_updated", False):
                    log_debug(f"Store {name} was updated")
            except Exception as e:
                log_warning(f"Error processing through {name}: {e}")

    async def aprocess(
        self,
        messages: List[Any],
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        namespace: Optional[str] = None,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
        **kwargs,
    ) -> None:
        """Async version of process."""
        context = {
            "messages": messages,
            "user_id": user_id,
            "session_id": session_id,
            "namespace": namespace or self.namespace,
            "agent_id": agent_id,
            "team_id": team_id,
            **kwargs,
        }

        for name, store in self.stores.items():
            try:
                await store.aprocess(**context)
                if getattr(store, "was_updated", False):
                    log_debug(f"Store {name} was updated")
            except Exception as e:
                log_warning(f"Error processing through {name}: {e}")

    # =========================================================================
    # Lower-Level API
    # =========================================================================

    def recall(
        self,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        message: Optional[str] = None,
        entity_id: Optional[str] = None,
        entity_type: Optional[str] = None,
        namespace: Optional[str] = None,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
        **kwargs,
    ) -> Dict[str, Any]:
        """Retrieve raw data from all stores.

        Most users should use `build_context()` instead.

        Returns:
            Dict mapping store names to their recalled data.
        """
        results = {}
        context = {
            "user_id": user_id,
            "session_id": session_id,
            "message": message,
            "query": message,  # For learned_knowledge
            "entity_id": entity_id,
            "entity_type": entity_type,
            "namespace": namespace or self.namespace,
            "agent_id": agent_id,
            "team_id": team_id,
            **kwargs,
        }

        for name, store in self.stores.items():
            try:
                result = store.recall(**context)
                results[name] = result
                try:
                    log_debug(f"Recalled from {name}: {result}")
                except Exception:
                    pass
            except Exception as e:
                log_warning(f"Error recalling from {name}: {e}")

        return results

    async def arecall(
        self,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        message: Optional[str] = None,
        entity_id: Optional[str] = None,
        entity_type: Optional[str] = None,
        namespace: Optional[str] = None,
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
            "query": message,
            "entity_id": entity_id,
            "entity_type": entity_type,
            "namespace": namespace or self.namespace,
            "agent_id": agent_id,
            "team_id": team_id,
            **kwargs,
        }

        for name, store in self.stores.items():
            try:
                result = await store.arecall(**context)
                results[name] = result
                try:
                    log_debug(f"Recalled from {name}: {result}")
                except Exception:
                    pass
            except Exception as e:
                log_warning(f"Error recalling from {name}: {e}")

        return results

    def _format_results(self, results: Dict[str, Any]) -> str:
        """Format recalled data into context string."""
        parts = []

        for name, data in results.items():
            store = self.stores.get(name)
            if store:
                try:
                    formatted = store.build_context(data=data)
                    if formatted:
                        parts.append(formatted)
                except Exception as e:
                    log_warning(f"Error building context from {name}: {e}")

        return "\n\n".join(parts)

    # =========================================================================
    # Curation
    # =========================================================================

    @property
    def curator(self) -> "Curator":
        """Get the curator for memory maintenance.

        Lazily creates the curator on first access.

        Example:
            >>> learning.curator.prune(user_id="alice", max_age_days=90)
            >>> learning.curator.deduplicate(user_id="alice")
        """
        if self._curator is None:
            from agno.learn.curate import Curator

            self._curator = Curator(machine=self)
        return self._curator

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
    # Serialization
    # =========================================================================

    def to_dict(self) -> Dict[str, Any]:
        """Serialize the LearningMachine configuration to a dictionary.

        Preserves which stores are enabled and the namespace so that
        from_dict() can reconstruct an equivalent instance. Does not
        serialize db, model, or knowledge (those are injected at init).
        """
        d: Dict[str, Any] = {}
        if self.user_profile:
            d["user_profile"] = True
        if self.user_memory:
            d["user_memory"] = True
        if self.session_context:
            d["session_context"] = True
        if self.entity_memory:
            d["entity_memory"] = True
        if self.learned_knowledge:
            d["learned_knowledge"] = True
        if self.decision_log:
            d["decision_log"] = True
        if self.namespace != "global":
            d["namespace"] = self.namespace
        if self.debug_mode:
            d["debug_mode"] = True
        return d

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "LearningMachine":
        """Reconstruct a LearningMachine from a serialized dictionary.

        db and model must be injected separately (e.g. during agent/team init).
        """
        return cls(
            user_profile=data.get("user_profile", False),
            user_memory=data.get("user_memory", False),
            session_context=data.get("session_context", False),
            entity_memory=data.get("entity_memory", False),
            learned_knowledge=data.get("learned_knowledge", False),
            decision_log=data.get("decision_log", False),
            namespace=data.get("namespace", "global"),
            debug_mode=data.get("debug_mode", False),
        )

    # =========================================================================
    # Representation
    # =========================================================================

    def __repr__(self) -> str:
        """String representation for debugging."""
        store_names = list(self.stores.keys()) if self._stores is not None else "[not initialized]"
        db_name = self.db.__class__.__name__ if self.db else None
        model_name = self.model.id if self.model and hasattr(self.model, "id") else None
        has_knowledge = self.knowledge is not None

        return (
            f"LearningMachine("
            f"stores={store_names}, "
            f"db={db_name}, "
            f"model={model_name}, "
            f"knowledge={has_knowledge}, "
            f"namespace={self.namespace!r})"
        )
