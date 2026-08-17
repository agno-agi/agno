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
from typing import Any, Callable, ClassVar, Dict, List, Optional, Union

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


def _filter_store_kwargs(callee: Callable, kwargs: Dict[str, Any]) -> Dict[str, Any]:
    """Filter kwargs to what the callee accepts (signature-aware dispatch).

    Third-party custom_stores satisfy a Protocol, and a store written as
    ``def recall(self, user_id=None)`` with no ``**kwargs`` would raise
    TypeError the moment new context kwargs (message, run_context, ...) arrive.
    Built-in stores take ``**kwargs`` and see everything; narrow custom stores
    keep working untouched. Same inspect.signature approach as
    invoke_callable_factory.
    """
    import inspect

    try:
        parameters = inspect.signature(callee).parameters
    except (TypeError, ValueError):
        return kwargs
    kinds = {p.kind for p in parameters.values()}
    if inspect.Parameter.VAR_KEYWORD in kinds:
        return kwargs
    if inspect.Parameter.VAR_POSITIONAL in kinds:
        # A *args-only callee cannot take these as keywords; pass everything
        # through so the mismatch fails loudly instead of silently dropping data.
        return kwargs
    return {key: value for key, value in kwargs.items() if key in parameters}


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
    decision_log: DecisionLogInput = False

    # Namespace for entity_memory and learned_knowledge
    namespace: str = "global"

    # Global default for max_updates_per_run (applied to all stores unless overridden)
    max_updates_per_run: int = 10

    # Custom stores
    custom_stores: Optional[Dict[str, LearningStore]] = None

    # Debug mode
    debug_mode: bool = False

    # Internal state (lazy initialization)
    _stores: Optional[Dict[str, LearningStore]] = field(default=None, init=False)
    _curator: Optional[Any] = field(default=None, init=False)
    # Manual-door tracking: instructions() called by the developer marks the
    # machine as hand-placed; if the framework then also injects it (learning=),
    # the blocks would render twice - warn once.
    _placed_by_hand: bool = field(default=False, init=False)
    _double_render_warned: bool = field(default=False, init=False)
    _missing_user_id_warned: bool = field(default=False, init=False)
    _missing_model_warned: bool = field(default=False, init=False)
    # Strong refs to fire-and-forget capture tasks (acapture_hook), so the event
    # loop cannot garbage-collect them mid-flight.
    _capture_tasks: set = field(default_factory=set, init=False)

    # =========================================================================
    # Initialization (Lazy)
    # =========================================================================

    @property
    def stores(self) -> Dict[str, LearningStore]:
        """All registered stores, keyed by name. Lazily initialized.

        Stores take the machine's model at construction, but the model usually
        arrives *after* them: ``learning=`` hands over the agent's model during
        Agent init, which is later than any earlier read of this property — a
        test, an inspection, or the manual door. Backfill on access so a store
        built before the model was bound picks it up, instead of keeping
        ``model=None`` for the life of the process and silently declining to
        capture.
        """
        if self._stores is None:
            self._initialize_stores()
        if self.model is not None:
            for store in self._stores.values():  # type: ignore[union-attr]
                config = getattr(store, "config", None)
                if config is not None and getattr(config, "model", "unused") is None:
                    config.model = self.model
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

        # Decision Log
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
        # Already a store instance. The Protocol gained instructions() in 2.8.4;
        # the duck-typed fallback keeps third-party stores written before that
        # working (they simply contribute no guidance text).
        if isinstance(input_value, LearningStore):
            return input_value
        if not isinstance(input_value, bool) and all(
            callable(getattr(input_value, method, None)) for method in ("recall", "process", "build_context")
        ):
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
            if config.max_updates_per_run is None:
                config.max_updates_per_run = self.max_updates_per_run
        else:
            config = UserProfileConfig(
                db=self.db,
                model=self.model,
                mode=LearningMode.ALWAYS,
                max_updates_per_run=self.max_updates_per_run,
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
            if config.max_updates_per_run is None:
                config.max_updates_per_run = self.max_updates_per_run
        else:
            config = UserMemoryConfig(
                db=self.db,
                model=self.model,
                mode=LearningMode.ALWAYS,
                max_updates_per_run=self.max_updates_per_run,
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
            if config.max_updates_per_run is None:
                config.max_updates_per_run = self.max_updates_per_run
        else:
            config = SessionContextConfig(
                db=self.db,
                model=self.model,
                enable_planning=False,
                max_updates_per_run=self.max_updates_per_run,
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
            if config.max_updates_per_run is None:
                config.max_updates_per_run = self.max_updates_per_run
            # A config still on the class default inherits the machine namespace;
            # an explicit config namespace wins over it at every call site.
            if config.namespace == "global" and self.namespace != "global":
                config.namespace = self.namespace
        else:
            config = EntityMemoryConfig(
                db=self.db,
                model=self.model,
                namespace=self.namespace,
                mode=LearningMode.AGENTIC,
                max_updates_per_run=self.max_updates_per_run,
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
            if config.max_updates_per_run is None:
                config.max_updates_per_run = self.max_updates_per_run
            if config.namespace == "global" and self.namespace != "global":
                config.namespace = self.namespace
        else:
            config = LearnedKnowledgeConfig(
                model=self.model,
                knowledge=self.knowledge,
                mode=LearningMode.AGENTIC,
                max_updates_per_run=self.max_updates_per_run,
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
            if config.max_updates_per_run is None:
                config.max_updates_per_run = self.max_updates_per_run
        else:
            config = DecisionLogConfig(
                db=self.db,
                model=self.model,
                mode=LearningMode.AGENTIC,  # Default to AGENTIC for explicit logging
                max_updates_per_run=self.max_updates_per_run,
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

    @property
    def requires_history(self) -> bool:
        # PROPOSE and HITL modes need chat history for multi-turn confirmation
        modes_needing_history = {LearningMode.PROPOSE, LearningMode.HITL}
        for cfg in (
            self.learned_knowledge,
            self.user_profile,
            self.user_memory,
            self.session_context,
            self.entity_memory,
            self.decision_log,
        ):
            mode = getattr(cfg, "mode", None) or getattr(getattr(cfg, "config", None), "mode", None)
            if mode in modes_needing_history:
                return True
        return False

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
            namespace=namespace,
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
            namespace=namespace,
            agent_id=agent_id,
            team_id=team_id,
            **kwargs,
        )

        return self._format_results(results=results)

    def instructions(self) -> str:
        """The guidance block: how and when to use the learning tools.

        Mode-aware and aggregated across enabled stores, which is why this is
        an instance method and not a static string - the text depends on which
        stores are enabled and what mode each is in. Pairs with build_context()
        (the data block): the automatic path concatenates the two at the
        injection site, and the manual door places each by hand.

        Calling this marks the machine as hand-placed; if the same machine is
        ALSO passed to Agent(learning=...), the framework warns once about the
        double render.
        """
        self._placed_by_hand = True
        return self._instructions_text()

    def _warn_if_user_id_missing(self, user_id: Optional[str]) -> None:
        """Per-user stores silently drop their tools and capture without a
        user_id (an unauthenticated /mcp run is the common way to get here).
        Make the degradation visible, once per machine."""
        if user_id or self._missing_user_id_warned:
            return
        per_user = [name for name in ("user_profile", "user_memory") if self.stores.get(name) is not None]
        if per_user:
            self._missing_user_id_warned = True
            log_warning(
                f"This run has no user_id, but per-user learning stores are configured "
                f"({', '.join(per_user)}). Their tools and capture are disabled for this run. "
                f"Pin Agent(user_id=...) or authenticate the request so a user id reaches the stores."
            )

    def _warn_if_model_missing(self) -> None:
        """Capture is a model call, and the manual door injects nothing.

        ``learning=`` hands the agent's model to the machine; a hand-placed
        machine keeps whatever it was constructed with. Without one, the
        capture tools return "No model provided" and entity memory keeps every
        stated fact, both without saying so at the point of use.
        """
        if self._missing_model_warned:
            return
        # Ask the stores, not the machine: `self.model is not None` was the
        # earlier guard here, and it short-circuited exactly the case this
        # check exists to catch — a machine whose model arrived after its
        # stores did. `stores` now backfills those, so a store still without
        # one means the machine genuinely has none.
        without = [name for name, store in self.stores.items() if getattr(store, "model", "unused") is None]
        if not without:
            return
        self._missing_model_warned = True
        log_warning(
            f"LearningMachine has no model, so these stores cannot capture: {', '.join(sorted(without))}. "
            f"Their tools return 'No model provided', and entity memory records every stated fact without "
            f"retiring the ones it contradicts. Pass model= to LearningMachine (the manual door injects "
            f"nothing), or attach the machine with learning= so the agent's model is used."
        )

    def _framework_instructions(self) -> str:
        """The guidance block, fetched by the automatic injection path.

        Detects the double-render case: the same machine placed by hand
        (instructions() was called) AND attached via learning=.
        """
        if self._placed_by_hand and not self._double_render_warned:
            self._double_render_warned = True
            log_warning(
                "This LearningMachine is attached via learning= AND its surfaces are placed by "
                "hand (instructions()/build_context()); its context will render twice. Pick one "
                "door: pass learning= for the automatic path, or place the surfaces yourself "
                "without learning=."
            )
        return self._instructions_text()

    def _instructions_text(self) -> str:
        parts: List[str] = []
        for name, store in self.stores.items():
            instructions_fn = getattr(store, "instructions", None)
            if not callable(instructions_fn):
                continue
            try:
                text = instructions_fn()
                if text:
                    parts.append(text)
            except Exception as e:
                log_warning(f"Error getting instructions from {name}: {str(e)}")
        return "\n\n".join(parts)

    def capture_hook(self) -> Callable:
        """A post_hooks-compatible callable that runs this machine's capture pass.

        The manual door is agentic by nature: with no learning= there is no
        automatic post-run extraction, and the tools are the capture mechanism.
        For the developer who wants hand-placed prompts AND ALWAYS-mode
        extraction, add this to Agent(post_hooks=[...]). An escape hatch, not a
        third shape.

        Extraction is backgrounded on the agent's background executor when one
        is available (the same place learning= runs it), so it stays off the
        response path; without an executor it runs inline. Works on both sync
        and async runs (async post-hook execution calls sync hooks directly).
        """
        machine = self

        def learning_capture(run_output=None, agent=None, session=None, user_id=None, run_context=None) -> None:
            messages = list(getattr(run_output, "messages", None) or [])
            if not messages:
                return
            kwargs = dict(
                messages=messages,
                user_id=user_id,
                session_id=getattr(session, "session_id", None) if session is not None else None,
                agent_id=getattr(agent, "id", None) if agent is not None else None,
                team_id=getattr(agent, "team_id", None) if agent is not None else None,
                run_context=run_context,
                metadata=getattr(run_context, "metadata", None),
                dependencies=getattr(run_context, "dependencies", None),
                session_state=getattr(run_context, "session_state", None),
            )
            executor = getattr(agent, "background_executor", None) if agent is not None else None
            if executor is not None:
                executor.submit(machine.process, **kwargs)
            else:
                machine.process(**kwargs)

        return learning_capture

    def acapture_hook(self) -> Callable:
        """Async version of capture_hook: schedules aprocess as a background task.

        Only for async runs - a sync run() skips async hooks with a warning, so
        pass capture_hook() there instead. The task is fire-and-forget off the
        response path; failures are logged, never raised into the run.
        """
        machine = self

        async def alearning_capture(run_output=None, agent=None, session=None, user_id=None, run_context=None) -> None:
            import asyncio

            messages = list(getattr(run_output, "messages", None) or [])
            if not messages:
                return
            task = asyncio.create_task(
                machine.aprocess(
                    messages=messages,
                    user_id=user_id,
                    session_id=getattr(session, "session_id", None) if session is not None else None,
                    agent_id=getattr(agent, "id", None) if agent is not None else None,
                    team_id=getattr(agent, "team_id", None) if agent is not None else None,
                    run_context=run_context,
                    metadata=getattr(run_context, "metadata", None),
                    dependencies=getattr(run_context, "dependencies", None),
                    session_state=getattr(run_context, "session_state", None),
                )
            )
            machine._capture_tasks.add(task)
            task.add_done_callback(machine._capture_tasks.discard)

        return alearning_capture

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
        - user_profile: update_profile
        - user_memory: update_user_memory
        - entity_memory: remember_about, link_entities, search_entities, forget
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
        self._warn_if_user_id_missing(user_id)
        self._warn_if_model_missing()
        context = {
            "user_id": user_id,
            "session_id": session_id,
            "namespace": namespace,
            "agent_id": agent_id,
            "team_id": team_id,
            **kwargs,
        }

        for name, store in self.stores.items():
            try:
                store_tools = store.get_tools(**_filter_store_kwargs(store.get_tools, context))
                if store_tools:
                    tools.extend(store_tools)
                    log_debug(f"Got {len(store_tools)} tools from {name}")
            except Exception as e:
                log_warning(f"Error getting tools from {name}: {str(e)}")

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
        self._warn_if_user_id_missing(user_id)
        self._warn_if_model_missing()
        context = {
            "user_id": user_id,
            "session_id": session_id,
            "namespace": namespace,
            "agent_id": agent_id,
            "team_id": team_id,
            **kwargs,
        }

        for name, store in self.stores.items():
            try:
                store_tools = await store.aget_tools(**_filter_store_kwargs(store.aget_tools, context))
                if store_tools:
                    tools.extend(store_tools)
                    log_debug(f"Got {len(store_tools)} tools from {name}")
            except Exception as e:
                log_warning(f"Error getting tools from {name}: {str(e)}")

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
            "namespace": namespace,
            "agent_id": agent_id,
            "team_id": team_id,
            **kwargs,
        }

        for name, store in self.stores.items():
            try:
                store.process(**_filter_store_kwargs(store.process, context))
                if getattr(store, "was_updated", False):
                    log_debug(f"Store {name} was updated")
            except Exception as e:
                log_warning(f"Error processing through {name}: {str(e)}")

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
            "namespace": namespace,
            "agent_id": agent_id,
            "team_id": team_id,
            **kwargs,
        }

        for name, store in self.stores.items():
            try:
                await store.aprocess(**_filter_store_kwargs(store.aprocess, context))
                if getattr(store, "was_updated", False):
                    log_debug(f"Store {name} was updated")
            except Exception as e:
                log_warning(f"Error processing through {name}: {str(e)}")

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
            "namespace": namespace,
            "agent_id": agent_id,
            "team_id": team_id,
            **kwargs,
        }

        for name, store in self.stores.items():
            try:
                result = store.recall(**_filter_store_kwargs(store.recall, context))
                results[name] = result
                try:
                    log_debug(f"Recalled from {name}: {result}")
                except Exception:
                    pass
            except Exception as e:
                log_warning(f"Error recalling from {name}: {str(e)}")

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
            "namespace": namespace,
            "agent_id": agent_id,
            "team_id": team_id,
            **kwargs,
        }

        for name, store in self.stores.items():
            try:
                result = await store.arecall(**_filter_store_kwargs(store.arecall, context))
                results[name] = result
                try:
                    log_debug(f"Recalled from {name}: {result}")
                except Exception:
                    pass
            except Exception as e:
                log_warning(f"Error recalling from {name}: {str(e)}")

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
                    log_warning(f"Error building context from {name}: {str(e)}")

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

    _STORE_CONFIG_CLASSES: ClassVar[Dict[str, Any]] = {
        "user_profile": UserProfileConfig,
        "user_memory": UserMemoryConfig,
        "session_context": SessionContextConfig,
        "entity_memory": EntityMemoryConfig,
        "learned_knowledge": LearnedKnowledgeConfig,
        "decision_log": DecisionLogConfig,
    }

    def to_dict(self) -> Dict[str, Any]:
        """Serialize the LearningMachine configuration to a dictionary.

        Lossless for what a platform rebuild needs: per-store mode,
        namespace, enable_* toggles, limits, prompt strings and
        schema-by-import-path all round-trip. db, model and knowledge are
        never serialized (they are injected at init), and callables cannot
        be - a config carrying one round-trips as present-but-not-restorable
        and from_dict logs once. A schema class defined in a __main__ script
        serializes as a __main__ path and only resolves inside the same
        process; define custom schemas in an importable module for a
        cross-process rebuild. Store INSTANCES serialize their config;
        custom_stores serialize as import-path refs (informational - the
        instances cannot be rebuilt from a dict).
        """
        d: Dict[str, Any] = {}
        for store_name in self._STORE_CONFIG_CLASSES:
            value = getattr(self, store_name)
            if not value:
                continue
            d[store_name] = self._serialize_store_input(value)
        if self.namespace != "global":
            d["namespace"] = self.namespace
        if self.max_updates_per_run != 10:
            d["max_updates_per_run"] = self.max_updates_per_run
        if self.custom_stores:
            d["custom_stores"] = {
                name: f"{type(store).__module__}.{type(store).__qualname__}"
                for name, store in self.custom_stores.items()
            }
        if self.debug_mode:
            d["debug_mode"] = True
        return d

    def _serialize_store_input(self, value: Any) -> Any:
        """bool -> True; Config -> field dict; Store instance -> its config's dict."""
        import dataclasses

        if value is True:
            return True
        # A store instance carries its config (stores are dataclasses too, so
        # check for the carried config before the dataclass test).
        inner = getattr(value, "config", None)
        if inner is not None and dataclasses.is_dataclass(inner):
            config = inner
            store_module = type(value).__module__ or ""
            if not store_module.startswith("agno.learn.stores"):
                log_warning(
                    f"LearningMachine.to_dict: store {type(value).__name__} is serialized by its "
                    f"config only; the subclass itself cannot be rebuilt from a dict."
                )
        elif dataclasses.is_dataclass(value) and not isinstance(value, type):
            config = value
        else:
            return True

        serialized: Dict[str, Any] = {}
        for f in dataclasses.fields(config):
            if f.name in ("db", "model", "knowledge"):
                continue
            field_value = getattr(config, f.name)
            if field_value is None:
                continue
            if isinstance(field_value, LearningMode):
                serialized["mode"] = field_value.value
            elif isinstance(field_value, type):
                serialized[f.name] = f"{field_value.__module__}.{field_value.__qualname__}"
            elif callable(field_value):
                serialized[f.name] = {"__callable__": getattr(field_value, "__name__", "callable")}
            elif isinstance(field_value, (str, int, float, bool, list, dict)):
                import json

                try:
                    json.dumps(field_value)
                except (TypeError, ValueError):
                    log_warning(
                        f"LearningMachine.to_dict: dropping non-JSON-serializable config value {f.name!r}; "
                        f"set it programmatically after rebuild."
                    )
                    continue
                serialized[f.name] = field_value
        return serialized

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "LearningMachine":
        """Reconstruct a LearningMachine from a serialized dictionary.

        db and model must be injected separately (e.g. during agent/team
        init). Accepts both the lossless per-store dicts and the old
        boolean-only payloads. Unrestorable entries (callables, custom-store
        refs) are logged once, never silently dropped to a different default.
        """
        kwargs: Dict[str, Any] = {}
        for store_name, config_cls in cls._STORE_CONFIG_CLASSES.items():
            value = data.get(store_name, False)
            if isinstance(value, dict):
                kwargs[store_name] = cls._deserialize_store_config(store_name, config_cls, value)
            else:
                kwargs[store_name] = bool(value)

        if data.get("custom_stores"):
            log_warning(
                f"LearningMachine.from_dict: custom stores {sorted(data['custom_stores'])} cannot be "
                f"rebuilt from a serialized config; re-attach them programmatically."
            )

        return cls(
            namespace=data.get("namespace", "global"),
            max_updates_per_run=data.get("max_updates_per_run", 10),
            debug_mode=data.get("debug_mode", False),
            **kwargs,
        )

    @classmethod
    def _deserialize_store_config(cls, store_name: str, config_cls: Any, payload: Dict[str, Any]) -> Any:
        import dataclasses
        import importlib

        field_names = {f.name for f in dataclasses.fields(config_cls)}
        kwargs: Dict[str, Any] = {}
        for key, value in payload.items():
            if key not in field_names:
                continue
            if key == "mode":
                try:
                    kwargs["mode"] = LearningMode(value)
                except ValueError:
                    # AGENTIC, not the class default: several stores default to
                    # ALWAYS, and an unrecognized mode must never turn into a
                    # surprise per-run extraction pass.
                    log_warning(f"LearningMachine.from_dict: unknown mode {value!r} on {store_name}; using AGENTIC.")
                    kwargs["mode"] = LearningMode.AGENTIC
                continue
            if key == "schema" and isinstance(value, str):
                module_path, _, attr_path = value.rpartition(".")
                try:
                    target: Any = importlib.import_module(module_path)
                    for part in attr_path.split("."):
                        target = getattr(target, part)
                    kwargs["schema"] = target
                except Exception as e:
                    if module_path == "__main__":
                        log_warning(
                            f"LearningMachine.from_dict: schema {value!r} on {store_name} was defined "
                            f"in a __main__ script and cannot be imported from another process; "
                            f"define custom schemas in an importable module. The store falls back "
                            f"to its default schema."
                        )
                    else:
                        log_warning(
                            f"LearningMachine.from_dict: could not import schema {value!r} for {store_name}: {e}"
                        )
                continue
            if isinstance(value, dict) and "__callable__" in value:
                log_warning(
                    f"LearningMachine.from_dict: {store_name}.{key} was a callable "
                    f"({value['__callable__']}) and cannot be restored from a serialized config; "
                    f"set it programmatically."
                )
                continue
            kwargs[key] = value
        try:
            return config_cls(**kwargs)
        except Exception as e:
            # Keep every valid field: a payload carrying an invalid mode (e.g. a
            # legacy 'always' for entity memory) must not also lose its
            # namespace and knobs.
            retry_kwargs = {k: v for k, v in kwargs.items() if k != "mode"}
            if retry_kwargs != kwargs:
                try:
                    rebuilt = config_cls(**retry_kwargs)
                    log_warning(
                        f"LearningMachine.from_dict: dropped invalid mode on {store_name} ({e}); "
                        f"other settings preserved."
                    )
                    return rebuilt
                except Exception:
                    pass
            log_warning(f"LearningMachine.from_dict: could not rebuild {store_name} config ({e}); enabling defaults.")
            return True

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
