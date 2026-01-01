"""
LearningMachine
===============
Unified learning system for Agno agents.

Ties together three types of learning (Phase 1):
- User Profile: Long-term memory about users
- Session Context: State and summary for current session
- Learned Knowledge: Reusable insights with semantic search

Future phases:
- Decision Logs: Why decisions were made (Phase 2)
- Behavioral Feedback: What worked, what didn't (Phase 2)
- Self-Improvement: Evolved instructions (Phase 4)
"""

from dataclasses import dataclass, field
from textwrap import dedent
from typing import Any, Callable, Dict, List, Optional, Type, Union

from agno.learn.config import (
    KnowledgeConfig,
    LearningMode,
    SessionContextConfig,
    UserProfileConfig,
)
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
            agent = Agent(
                model=model,
                db=db,
                learning=LearningMachine(
                    db=db,
                    model=model,
                    knowledge=kb,
                    user_profile=True,
                    session_context=True,
                    learned_knowledge=True,
                ),
            )
    ```

        3. Full Control:
    ```python
            agent = Agent(
                model=model,
                db=db,
                learning=LearningMachine(
                    db=db,
                    model=model,
                    knowledge=kb,
                    user_profile=UserProfileConfig(
                        mode=LearningMode.BACKGROUND,
                        extraction=ExtractionConfig(timing=ExtractionTiming.PARALLEL),
                        enable_tool=True,
                    ),
                    session_context=SessionContextConfig(enable_planning=True),
                    learned_knowledge=KnowledgeConfig(mode=LearningMode.PROPOSE),
                ),
            )
    ```

        Args:
            db: Database connection for user profile and session context.
            model: LLM model for extraction.
            knowledge: Knowledge base for learned knowledge (vector search).
            instructions: Custom instructions (appended to defaults).
            user_profile: User Profile config. True=defaults, False=disabled.
            session_context: Session Context config. True=defaults, False=disabled.
            learned_knowledge: Learned Knowledge config. True=defaults, False=disabled.
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

    # Phase 2+ (disabled by default)
    decision_logs: Union[bool, None] = False
    behavioral_feedback: Union[bool, None] = False
    self_improvement: Union[bool, None] = False

    # Internal: resolved configs (set in __post_init__)
    _user_profile_config: Optional[UserProfileConfig] = field(default=None, init=False)
    _session_context_config: Optional[SessionContextConfig] = field(default=None, init=False)
    _knowledge_config: Optional[KnowledgeConfig] = field(default=None, init=False)

    # Internal: stores (initialized lazily)
    _user_profile_store: Optional[Any] = field(default=None, init=False)
    _session_context_store: Optional[Any] = field(default=None, init=False)
    _knowledge_store: Optional[Any] = field(default=None, init=False)
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
            # Inject db/model if not set
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
            from agno.learn.stores.user_profile import UserProfileStore

            self._user_profile_store = UserProfileStore(config=self._user_profile_config)

        # Session Context Store
        if self._session_context_config and self._session_context_config.db:
            from agno.learn.stores.session_context import SessionContextStore

            self._session_context_store = SessionContextStore(config=self._session_context_config)

        # Knowledge Store
        if self._knowledge_config and self._knowledge_config.knowledge:
            from agno.learn.stores.knowledge import KnowledgeStore

            self._knowledge_store = KnowledgeStore(config=self._knowledge_config)

        self._stores_initialized = True

    # --- Properties ---

    @property
    def user_profile_store(self):
        """Get the user profile store (lazy init)."""
        self._init_stores()
        return self._user_profile_store

    @property
    def session_context_store(self):
        """Get the session context store (lazy init)."""
        self._init_stores()
        return self._session_context_store

    @property
    def knowledge_store(self):
        """Get the knowledge store (lazy init)."""
        self._init_stores()
        return self._knowledge_store

    # -------------------------------------------------------------------------
    # Public API
    # -------------------------------------------------------------------------

    def get_tools(
        self,
        user_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
    ) -> List[Callable]:
        """Get tools to expose to the agent.

        Args:
            user_id: User ID for user profile tool.
            agent_id: Optional agent context.
            team_id: Optional team context.

        Returns:
            List of tool functions.
        """
        tools = []

        # User Profile tool
        if self._user_profile_config and self._user_profile_config.enable_tool and self.user_profile_store and user_id:
            tools.append(
                self.user_profile_store.get_agent_tool(
                    user_id=user_id,
                    agent_id=agent_id,
                    team_id=team_id,
                )
            )

        # Knowledge tool
        if self._knowledge_config and self._knowledge_config.enable_tool and self.knowledge_store:
            tools.append(
                self.knowledge_store.get_agent_tool(
                    agent_id=agent_id,
                    team_id=team_id,
                )
            )

        return tools

    async def aget_tools(
        self,
        user_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
    ) -> List[Callable]:
        """Async version of get_tools."""
        tools = []

        if self._user_profile_config and self._user_profile_config.enable_tool and self.user_profile_store and user_id:
            tools.append(
                await self.user_profile_store.aget_agent_tool(
                    user_id=user_id,
                    agent_id=agent_id,
                    team_id=team_id,
                )
            )

        if self._knowledge_config and self._knowledge_config.enable_tool and self.knowledge_store:
            tools.append(
                await self.knowledge_store.aget_agent_tool(
                    agent_id=agent_id,
                    team_id=team_id,
                )
            )

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
    ) -> Dict[str, Any]:
        """Retrieve relevant learnings before agent runs.

        Args:
            user_id: User ID for user profile retrieval.
            session_id: Session ID for session context retrieval.
            message: Current message for semantic search.
            agent_id: Optional agent context.
            team_id: Optional team context.

        Returns:
            Dictionary with retrieved learnings by type.
        """
        results: Dict[str, Any] = {}

        # User Profile
        if self.user_profile_store and user_id:
            profile = self.user_profile_store.get(
                user_id=user_id,
                agent_id=agent_id,
                team_id=team_id,
            )
            if profile:
                results["user_profile"] = profile

        # Session Context
        if self.session_context_store and session_id:
            context = self.session_context_store.get(session_id=session_id)
            if context:
                results["session_context"] = context

        # Learned Knowledge (semantic search)
        if self.knowledge_store and message:
            learnings = self.knowledge_store.search(
                query=message,
                agent_id=agent_id,
                team_id=team_id,
            )
            if learnings:
                results["learned_knowledge"] = learnings

        return results

    async def arecall(
        self,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        message: Optional[str] = None,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Async version of recall."""
        results: Dict[str, Any] = {}

        if self.user_profile_store and user_id:
            profile = await self.user_profile_store.aget(
                user_id=user_id,
                agent_id=agent_id,
                team_id=team_id,
            )
            if profile:
                results["user_profile"] = profile

        if self.session_context_store and session_id:
            context = await self.session_context_store.aget(session_id=session_id)
            if context:
                results["session_context"] = context

        if self.knowledge_store and message:
            learnings = await self.knowledge_store.asearch(
                query=message,
                agent_id=agent_id,
                team_id=team_id,
            )
            if learnings:
                results["learned_knowledge"] = learnings

        return results

    def process(
        self,
        messages: List[Any],
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
    ) -> None:
        """Extract and save learnings after agent runs.

        Called in background based on timing config.

        Args:
            messages: Conversation messages to analyze.
            user_id: User ID for user profile extraction.
            session_id: Session ID for session context extraction.
            agent_id: Optional agent context.
            team_id: Optional team context.
        """
        if not messages:
            return

        # User Profile extraction (BACKGROUND mode only)
        if (
            self.user_profile_store
            and user_id
            and self._user_profile_config
            and self._user_profile_config.mode == LearningMode.BACKGROUND
        ):
            try:
                self.user_profile_store.extract_and_save(
                    messages=messages,
                    user_id=user_id,
                    agent_id=agent_id,
                    team_id=team_id,
                )
            except Exception as e:
                log_warning(f"Error in user profile extraction: {e}")

        # Session Context extraction (always BACKGROUND)
        if self.session_context_store and session_id:
            try:
                self.session_context_store.extract_and_save(
                    messages=messages,
                    session_id=session_id,
                )
            except Exception as e:
                log_warning(f"Error in session context extraction: {e}")

    async def aprocess(
        self,
        messages: List[Any],
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
    ) -> None:
        """Async version of process."""
        if not messages:
            return

        # User Profile extraction
        if (
            self.user_profile_store
            and user_id
            and self._user_profile_config
            and self._user_profile_config.mode == LearningMode.BACKGROUND
        ):
            try:
                await self.user_profile_store.aextract_and_save(
                    messages=messages,
                    user_id=user_id,
                    agent_id=agent_id,
                    team_id=team_id,
                )
            except Exception as e:
                log_warning(f"Error in user profile extraction: {e}")

        # Session Context extraction
        if self.session_context_store and session_id:
            try:
                await self.session_context_store.aextract_and_save(
                    messages=messages,
                    session_id=session_id,
                )
            except Exception as e:
                log_warning(f"Error in session context extraction: {e}")

    def format_recall_for_context(self, recall_results: Dict[str, Any]) -> str:
        """Format recall results for inclusion in system prompt.

        Args:
            recall_results: Results from recall().

        Returns:
            Formatted string for system prompt.
        """
        parts = []

        # User Profile
        if "user_profile" in recall_results:
            profile = recall_results["user_profile"]
            memories_text = None

            if hasattr(profile, "get_memories_text"):
                memories_text = profile.get_memories_text()
            elif hasattr(profile, "memories") and profile.memories:
                memories_text = "\n".join(f"- {m.get('content', str(m))}" for m in profile.memories)

            if memories_text:
                parts.append(
                    dedent(f"""\
                    <user_profile>
                    What you know about this user:
                    {memories_text}

                    Use this to personalize responses. Current conversation takes precedence.
                    </user_profile>
                """)
                )

        # Session Context
        if "session_context" in recall_results:
            context = recall_results["session_context"]
            context_text = None

            if hasattr(context, "get_context_text"):
                context_text = context.get_context_text()
            elif hasattr(context, "summary") and context.summary:
                context_text = f"Summary: {context.summary}"

            if context_text:
                parts.append(
                    dedent(f"""\
                    <session_context>
                    Earlier in this session:
                    {context_text}

                    Use this for continuity. Current conversation takes precedence.
                    </session_context>
                """)
                )

        # Learned Knowledge
        if "learned_knowledge" in recall_results:
            learnings = recall_results["learned_knowledge"]
            if learnings:
                learnings_parts = []
                for i, learning in enumerate(learnings, 1):
                    if hasattr(learning, "to_text"):
                        learnings_parts.append(f"{i}. {learning.to_text()}")
                    elif hasattr(learning, "title") and hasattr(learning, "learning"):
                        learnings_parts.append(f"{i}. **{learning.title}**: {learning.learning}")
                    else:
                        learnings_parts.append(f"{i}. {learning}")

                learnings_text = "\n".join(learnings_parts)

                parts.append(
                    dedent(f"""\
                    <relevant_learnings>
                    Insights from past interactions:
                    {learnings_text}

                    Apply where appropriate.
                    </relevant_learnings>
                """)
                )

        return "\n".join(parts)

    # -------------------------------------------------------------------------
    # State Tracking
    # -------------------------------------------------------------------------

    @property
    def profile_updated(self) -> bool:
        """Check if user profile was updated in last extraction."""
        if self.user_profile_store:
            return self.user_profile_store.profile_updated
        return False

    @property
    def context_updated(self) -> bool:
        """Check if session context was updated in last extraction."""
        if self.session_context_store:
            return self.session_context_store.context_updated
        return False

    @property
    def learning_saved(self) -> bool:
        """Check if a learning was saved in last operation."""
        if self.knowledge_store:
            return self.knowledge_store.learning_saved
        return False

    # -------------------------------------------------------------------------
    # Private Methods
    # -------------------------------------------------------------------------

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


# -------------------------------------------------------------------------
# Convenience Factory
# -------------------------------------------------------------------------


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
    """
    return LearningMachine(
        db=db,
        model=model,
        knowledge=knowledge,
        **kwargs,
    )
