"""
LearningMachine
===============
Unified learning system for Agno agents.

Ties together multiple learning types into one cohesive system:
- User Profile: Long-term memory about users
- Session Context: State and summary for current session
- Learned Knowledge: Reusable insights with semantic search
- Custom stores: Developer-defined learning types

Future phases:
- Decision Logs: Why decisions were made (Phase 2)
- Behavioral Feedback: What worked, what didn't (Phase 2)
- Self-Improvement: Evolved instructions (Phase 3)

Three DX levels:
1. Dead Simple: Agent(model=model, db=db, learning=True)
2. Pick What You Want: LearningMachine(db=db, user_profile=True, session_context=True)
3. Full Control: LearningMachine(db=db, user_profile=UserProfileConfig(...), ...)
"""

from dataclasses import dataclass, field
from textwrap import dedent
from typing import Any, Callable, Dict, List, Optional, Union

from agno.learn.config import (
    KnowledgeConfig,
    LearningMode,
    SessionContextConfig,
    UserProfileConfig,
)
from agno.learn.stores.base import LearningStore
from agno.utils.log import log_debug, log_warning


@dataclass
class LearningMachine:
    """Unified learning system for agents.

    LearningMachine consolidates multiple learning types into one
    configurable system with consistent patterns for storage,
    retrieval, and lifecycle management.

    Three levels of DX:

    1. Dead Simple:
    ```python
        agent = Agent(model=model, db=db, learning=True)
    ```

    2. Pick What You Want:
    ```python
        learning = LearningMachine(
            db=db,
            model=model,
            knowledge=kb,
            user_profile=True,
            session_context=True,
            learned_knowledge=True,
        )
    ```

    3. Full Control:
    ```python
        learning = LearningMachine(
            db=db,
            model=model,
            knowledge=kb,
            user_profile=UserProfileConfig(
                mode=LearningMode.BACKGROUND,
                enable_tool=True,
            ),
            session_context=SessionContextConfig(enable_planning=True),
            learned_knowledge=KnowledgeConfig(mode=LearningMode.PROPOSE),
        )
    ```

    4. Custom Stores:
    ```python
        learning = LearningMachine(
            db=db,
            model=model,
            custom_stores={
                "project": ProjectContextStore(config=...),
                "style": ConversationStyleStore(config=...),
            },
        )

        # Or register dynamically
        learning.register("project", ProjectContextStore(config=...))
    ```

    Args:
        db: Database connection for user profile and session context.
        model: LLM model for extraction.
        knowledge: Knowledge base for learned knowledge (vector search).
        instructions: Custom instructions (appended to defaults).
        user_profile: User Profile config. True=defaults, False=disabled.
        session_context: Session Context config. True=defaults, False=disabled.
        learned_knowledge: Learned Knowledge config. True=defaults, False=disabled.
        custom_stores: Dict of custom learning stores to register.
    """

    # Core dependencies
    db: Optional[Any] = None
    model: Optional[Any] = None
    knowledge: Optional[Any] = None

    # Custom instructions
    instructions: Optional[str] = None

    # Learning type configs (bool or config object)
    user_profile: Union[bool, UserProfileConfig] = True
    session_context: Union[bool, SessionContextConfig] = True
    learned_knowledge: Union[bool, KnowledgeConfig] = True

    # Custom stores (developer-defined)
    custom_stores: Dict[str, LearningStore] = field(default_factory=dict)

    # Phase 2+ (disabled by default)
    decision_logs: Union[bool, None] = False
    behavioral_feedback: Union[bool, None] = False
    self_improvement: Union[bool, None] = False

    # Internal: resolved configs (set in __post_init__)
    _user_profile_config: Optional[UserProfileConfig] = field(default=None, init=False)
    _session_context_config: Optional[SessionContextConfig] = field(default=None, init=False)
    _knowledge_config: Optional[KnowledgeConfig] = field(default=None, init=False)

    # Internal: all stores (built-in + custom)
    _stores: Dict[str, LearningStore] = field(default_factory=dict, init=False)
    _stores_initialized: bool = field(default=False, init=False)

    def __post_init__(self):
        """Initialize and resolve configs."""
        self._resolve_configs()

    def _resolve_configs(self) -> None:
        """Convert bool/config inputs to fully resolved configs with dependencies."""

        # User Profile
        if self.user_profile is True:
            self._user_profile_config = UserProfileConfig(
                db=self.db,
                model=self.model,
            )
        elif self.user_profile is False or self.user_profile is None:
            self._user_profile_config = None
        elif isinstance(self.user_profile, UserProfileConfig):
            self._user_profile_config = self.user_profile
            if self._user_profile_config.db is None:
                self._user_profile_config.db = self.db
            if self._user_profile_config.model is None:
                self._user_profile_config.model = self.model

        # Session Context
        if self.session_context is True:
            self._session_context_config = SessionContextConfig(
                db=self.db,
                model=self.model,
            )
        elif self.session_context is False or self.session_context is None:
            self._session_context_config = None
        elif isinstance(self.session_context, SessionContextConfig):
            self._session_context_config = self.session_context
            if self._session_context_config.db is None:
                self._session_context_config.db = self.db
            if self._session_context_config.model is None:
                self._session_context_config.model = self.model

        # Learned Knowledge
        if self.learned_knowledge is True:
            self._knowledge_config = KnowledgeConfig(
                knowledge=self.knowledge,
                model=self.model,
            )
        elif self.learned_knowledge is False or self.learned_knowledge is None:
            self._knowledge_config = None
        elif isinstance(self.learned_knowledge, KnowledgeConfig):
            self._knowledge_config = self.learned_knowledge
            if self._knowledge_config.knowledge is None:
                self._knowledge_config.knowledge = self.knowledge
            if self._knowledge_config.model is None:
                self._knowledge_config.model = self.model

    def _init_stores(self) -> None:
        """Initialize storage backends (lazy initialization)."""
        if self._stores_initialized:
            return

        # User Profile Store
        if self._user_profile_config and self._user_profile_config.db:
            from agno.learn.stores.user import UserProfileStore

            self._stores["user_profile"] = UserProfileStore(config=self._user_profile_config)

        # Session Context Store
        if self._session_context_config and self._session_context_config.db:
            from agno.learn.stores.session import SessionContextStore

            self._stores["session_context"] = SessionContextStore(config=self._session_context_config)

        # Knowledge Store
        if self._knowledge_config and self._knowledge_config.knowledge:
            from agno.learn.stores.knowledge import KnowledgeStore

            self._stores["learned_knowledge"] = KnowledgeStore(config=self._knowledge_config)

        # Register custom stores
        for name, store in self.custom_stores.items():
            self._stores[name] = store

        self._stores_initialized = True

    # =========================================================================
    # Store Access
    # =========================================================================

    @property
    def stores(self) -> Dict[str, LearningStore]:
        """Get all registered stores."""
        self._init_stores()
        return self._stores

    @property
    def user_profile_store(self) -> Optional[LearningStore]:
        """Get the user profile store (lazy init)."""
        self._init_stores()
        return self._stores.get("user_profile")

    @property
    def session_context_store(self) -> Optional[LearningStore]:
        """Get the session context store (lazy init)."""
        self._init_stores()
        return self._stores.get("session_context")

    @property
    def knowledge_store(self) -> Optional[LearningStore]:
        """Get the knowledge store (lazy init)."""
        self._init_stores()
        return self._stores.get("learned_knowledge")

    # Config properties
    @property
    def user_profile_config(self) -> Optional[UserProfileConfig]:
        """Get resolved user profile config."""
        return self._user_profile_config

    @property
    def session_context_config(self) -> Optional[SessionContextConfig]:
        """Get resolved session context config."""
        return self._session_context_config

    @property
    def knowledge_config(self) -> Optional[KnowledgeConfig]:
        """Get resolved knowledge config."""
        return self._knowledge_config

    # =========================================================================
    # Custom Store Registration
    # =========================================================================

    def register(self, name: str, store: LearningStore) -> "LearningMachine":
        """Register a custom learning store.

        Args:
            name: Unique name for this learning type.
            store: The store instance.

        Returns:
            Self for chaining.

        Example:
        ```python
            learning = LearningMachine(db=db, model=model)
            learning.register("project", ProjectContextStore(config=...))
            learning.register("style", ConversationStyleStore(config=...))
        ```
        """
        self._init_stores()
        self._stores[name] = store
        self.custom_stores[name] = store
        return self

    def get_store(self, name: str) -> Optional[LearningStore]:
        """Get a store by name.

        Args:
            name: The store name (e.g., "user_profile", "project").

        Returns:
            The store instance, or None if not found.
        """
        self._init_stores()
        return self._stores.get(name)

    # =========================================================================
    # Public API
    # =========================================================================

    def get_tools(
        self,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
        **kwargs,
    ) -> List[Callable]:
        """Get tools from ALL stores.

        Args:
            user_id: User ID for user profile tool.
            session_id: Session ID (not used, session has no tool).
            agent_id: Optional agent context.
            team_id: Optional team context.
            **kwargs: Additional context for custom stores.

        Returns:
            List of tool functions.
        """
        self._init_stores()
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
                tools.extend(store_tools)
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
        self._init_stores()
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
                tools.extend(store_tools)
            except Exception as e:
                log_warning(f"Error getting tools from {name}: {e}")

        return tools

    def get_system_prompt_injection(self) -> str:
        """Get instructions to inject into system prompt.

        Returns:
            XML-formatted learning instructions.
        """
        instructions = self._build_instructions()
        if not instructions:
            return ""
        return f"<learning_instructions>\n{instructions}\n</learning_instructions>\n"

    def recall(
        self,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        message: Optional[str] = None,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
        **kwargs,
    ) -> Dict[str, Any]:
        """Retrieve relevant learnings from ALL stores before agent runs.

        Args:
            user_id: User ID for user profile retrieval.
            session_id: Session ID for session context retrieval.
            message: Current message for semantic search.
            agent_id: Optional agent context.
            team_id: Optional team context.
            **kwargs: Additional context for custom stores.

        Returns:
            Dictionary with retrieved learnings by store name.
        """
        self._init_stores()
        results: Dict[str, Any] = {}

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
                data = store.recall(**context)
                if data:
                    results[name] = data
            except Exception as e:
                log_warning(f"Error in recall from {name}: {e}")

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
        self._init_stores()
        results: Dict[str, Any] = {}

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
                data = await store.arecall(**context)
                if data:
                    results[name] = data
            except Exception as e:
                log_warning(f"Error in recall from {name}: {e}")

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
        """Extract and save learnings from ALL stores after agent runs.

        Called in background based on timing config.

        Args:
            messages: Conversation messages to analyze.
            user_id: User ID for user profile extraction.
            session_id: Session ID for session context extraction.
            agent_id: Optional agent context.
            team_id: Optional team context.
            **kwargs: Additional context for custom stores.
        """
        self._init_stores()

        if not messages:
            return

        context = {
            "user_id": user_id,
            "session_id": session_id,
            "agent_id": agent_id,
            "team_id": team_id,
            **kwargs,
        }

        for name, store in self._stores.items():
            try:
                # Only process if mode is BACKGROUND (for built-in stores)
                should_process = True

                if name == "user_profile" and self._user_profile_config:
                    should_process = self._user_profile_config.mode == LearningMode.BACKGROUND
                elif name == "learned_knowledge" and self._knowledge_config:
                    should_process = self._knowledge_config.mode == LearningMode.BACKGROUND
                # Session context is always BACKGROUND

                if should_process:
                    store.process(messages, **context)
            except Exception as e:
                log_warning(f"Error in process for {name}: {e}")

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
        self._init_stores()

        if not messages:
            return

        context = {
            "user_id": user_id,
            "session_id": session_id,
            "agent_id": agent_id,
            "team_id": team_id,
            **kwargs,
        }

        for name, store in self._stores.items():
            try:
                should_process = True

                if name == "user_profile" and self._user_profile_config:
                    should_process = self._user_profile_config.mode == LearningMode.BACKGROUND
                elif name == "learned_knowledge" and self._knowledge_config:
                    should_process = self._knowledge_config.mode == LearningMode.BACKGROUND

                if should_process:
                    await store.aprocess(messages, **context)
            except Exception as e:
                log_warning(f"Error in process for {name}: {e}")

    def format_recall_for_context(self, recall_results: Dict[str, Any]) -> str:
        """Format recall results for inclusion in system prompt.

        Uses each store's format_for_prompt() method.

        Args:
            recall_results: Results from recall().

        Returns:
            Formatted string for system prompt.
        """
        self._init_stores()
        parts = []

        for name, data in recall_results.items():
            store = self._stores.get(name)
            if store and data:
                try:
                    formatted = store.format_for_prompt(data)
                    if formatted:
                        parts.append(formatted)
                except Exception as e:
                    log_warning(f"Error formatting {name}: {e}")

        return "\n".join(parts)

    # =========================================================================
    # State Tracking
    # =========================================================================

    @property
    def profile_updated(self) -> bool:
        """Check if user profile was updated in last extraction."""
        store = self.user_profile_store
        return store.was_updated if store else False

    @property
    def context_updated(self) -> bool:
        """Check if session context was updated in last extraction."""
        store = self.session_context_store
        return store.was_updated if store else False

    @property
    def learning_saved(self) -> bool:
        """Check if a learning was saved in last operation."""
        store = self.knowledge_store
        return store.was_updated if store else False

    # =========================================================================
    # Private Methods
    # =========================================================================

    def _build_instructions(self) -> str:
        """Build learning instructions for the system prompt."""
        sections = []

        # Check what's enabled
        has_user_profile = self._user_profile_config is not None
        has_session_context = self._session_context_config is not None
        has_knowledge = self._knowledge_config is not None

        if not (has_user_profile or has_session_context or has_knowledge):
            return ""

        sections.append("You are a learning agent that improves over time.")

        # Tools section
        tool_lines = []

        if has_user_profile and self._user_profile_config.enable_tool:
            tool_lines.append(
                "- `update_user_memory(task)`: Update information about the user. "
                "Use to save, update, or forget user details like preferences and context."
            )

        if has_knowledge and self._knowledge_config.enable_tool:
            tool_lines.append(
                "- `save_learning(title, learning, context, tags)`: Save a reusable insight. "
                "Only call after user confirms a proposed learning."
            )

        if tool_lines:
            sections.append("## Learning Tools\n" + "\n".join(tool_lines))

        # PROPOSE mode instructions
        if has_knowledge and self._knowledge_config.mode == LearningMode.PROPOSE:
            sections.append(self._get_propose_instructions())

        # Custom instructions
        if self.instructions:
            sections.append(self.instructions)

        return "\n\n".join(sections)

    def _get_propose_instructions(self) -> str:
        """Get instructions for PROPOSE mode."""
        return dedent("""\
            ## Proposing Learnings

            When you discover a reusable insight, propose it to the user:

            ---
            **Proposed Learning**

            Title: [concise title]
            Learning: [the insight - specific and actionable]
            Context: [when to apply this]
            Tags: [relevant tags]

            Save this? (yes/no)
            ---

            Only call `save_learning` AFTER the user confirms.

            What makes a good learning:
            - **Specific**: "Check expense ratio AND tracking error" not "Look at metrics"
            - **Actionable**: Can be directly applied in future
            - **Generalizable**: Useful beyond this specific question

            Most conversations won't produce a learning. That's expected.
        """)


# =============================================================================
# Convenience Factory
# =============================================================================


def create_learning_machine(
    db=None,
    model=None,
    knowledge=None,
    **kwargs,
) -> LearningMachine:
    """Create a LearningMachine with sensible defaults.

    Args:
        db: Database connection.
        model: LLM model for extraction.
        knowledge: Knowledge base for learned knowledge.
        **kwargs: Additional config overrides.

    Returns:
        Configured LearningMachine instance.

    Example:
    ```python
        learning = create_learning_machine(
            db=my_db,
            model=my_model,
            user_profile=True,
            session_context=True,
        )
    ```
    """
    return LearningMachine(
        db=db,
        model=model,
        knowledge=knowledge,
        **kwargs,
    )
