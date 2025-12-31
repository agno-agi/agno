"""
LearningMachine
===============
Unified learning system for Agno agents.

Ties together six types of learning:
- User Profile: Long-term memory about users
- Session Context: State and summary for current session
- Learned Knowledge: Reusable insights with semantic search
- Decision Logs: Why decisions were made (Phase 2)
- Behavioral Feedback: What worked, what didn't (Phase 2)
- Self-Improvement: Evolved instructions (Phase 4)
"""

from dataclasses import dataclass, field
from textwrap import dedent
from typing import Any, Callable, Dict, List, Optional, Type, Union

from pydantic import BaseModel

from agno.learn.config import (
    BackgroundConfig,
    ExecutionTiming,
    KnowledgeConfig,
    LearningMode,
    SessionContextConfig,
    UserProfileConfig,
)
from agno.learn.schemas import DefaultLearning, DefaultSessionContext, DefaultUserProfile
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
                knowledge=kb,
                user_profile=UserProfileConfig(
                    mode=LearningMode.BACKGROUND,
                    background=BackgroundConfig(timing=ExecutionTiming.PARALLEL),
                    enable_tool=True,
                ),
                session_context=SessionContextConfig(enable_planning=True),
                learned_knowledge=KnowledgeConfig(mode=LearningMode.PROPOSE),
            ),
        )
        ```

    Args:
        db: Database connection for user profile and session context.
        knowledge: Knowledge base for learned knowledge (vector search).
        model: LLM model for extraction (uses agent's model if not provided).
        instructions: Custom instructions (appended to defaults).
        user_profile: User Profile config. True=defaults, False=disabled.
        session_context: Session Context config. True=defaults, False=disabled.
        learned_knowledge: Learned Knowledge config. True=defaults, False=disabled.
        decision_logs: Decision Logs config (Phase 2).
        behavioral_feedback: Behavioral Feedback config (Phase 2).
        self_improvement: Self-Improvement config (Phase 4).
    """

    # Database for user profile and session context
    db: Optional[Any] = None

    # Knowledge base for learned knowledge
    knowledge: Optional[Any] = None

    # Model for extraction (uses agent's model if not provided)
    model: Optional[Any] = None

    # Custom instructions
    instructions: Optional[str] = None

    # Learning type configs
    user_profile: Union[bool, UserProfileConfig] = True
    session_context: Union[bool, SessionContextConfig] = True
    learned_knowledge: Union[bool, KnowledgeConfig] = True

    # Phase 2 (disabled by default)
    decision_logs: Union[bool, None] = False
    behavioral_feedback: Union[bool, None] = False

    # Phase 4 (disabled by default)
    self_improvement: Union[bool, None] = False

    # Internal state (set in __post_init__)
    user_profile_config: Optional[UserProfileConfig] = field(default=None, init=False)
    session_context_config: Optional[SessionContextConfig] = field(default=None, init=False)
    knowledge_config: Optional[KnowledgeConfig] = field(default=None, init=False)

    # Stores (initialized lazily)
    _user_profile_store: Optional[Any] = field(default=None, init=False)
    _session_context_store: Optional[Any] = field(default=None, init=False)
    _knowledge_store: Optional[Any] = field(default=None, init=False)
    _stores_initialized: bool = field(default=False, init=False)

    def __post_init__(self):
        """Initialize configs after dataclass creation."""
        # Normalize configs
        self.user_profile_config = self._normalize_config(
            self.user_profile, UserProfileConfig, UserProfileConfig()
        )
        self.session_context_config = self._normalize_config(
            self.session_context, SessionContextConfig, SessionContextConfig()
        )
        self.knowledge_config = self._normalize_config(
            self.learned_knowledge, KnowledgeConfig, KnowledgeConfig()
        )

    def _normalize_config(
        self,
        value: Union[bool, BaseModel, None],
        config_class: Type[BaseModel],
        default: BaseModel,
    ) -> Optional[BaseModel]:
        """Convert bool to config or return None if disabled."""
        if value is True:
            return default
        elif value is False or value is None:
            return None
        elif isinstance(value, config_class):
            return value
        else:
            raise ValueError(f"Expected bool or {config_class.__name__}, got {type(value)}")

    def _init_stores(self) -> None:
        """Initialize storage backends (lazy initialization)."""
        if self._stores_initialized:
            return

        from agno.learn.stores.knowledge import KnowledgeStore
        from agno.learn.stores.session_context import SessionContextStore
        from agno.learn.stores.user_profile import UserProfileStore

        # User Profile Store
        if self.user_profile_config and self.db:
            self._user_profile_store = UserProfileStore(
                db=self.db,
                config=self.user_profile_config,
            )

        # Session Context Store
        if self.session_context_config and self.db:
            self._session_context_store = SessionContextStore(
                db=self.db,
                config=self.session_context_config,
            )

        # Knowledge Store
        if self.knowledge_config and self.knowledge:
            self._knowledge_store = KnowledgeStore(
                knowledge=self.knowledge,
                config=self.knowledge_config,
            )

        self._stores_initialized = True

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

    def get_tools(self, user_id: Optional[str] = None) -> List[Callable]:
        """Return tools to give to the agent.

        Args:
            user_id: User ID for user memory tool.

        Returns:
            List of tool functions.
        """
        tools = []

        # User Profile tool: save_user_memory
        if (self.user_profile_config and
            self.user_profile_config.enable_tool and
            self.user_profile_store and
            user_id):
            tools.append(self._create_save_user_memory_tool(user_id))

        # Learned Knowledge tool: save_learning
        if (self.knowledge_config and
            self.knowledge_config.enable_tool and
            self.knowledge_store):
            tools.append(self._create_save_learning_tool())

        return tools

    def get_system_prompt_injection(self) -> str:
        """Return instructions to inject into system prompt.

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
    ) -> Dict[str, Any]:
        """Retrieve relevant learnings before agent runs.

        Args:
            user_id: User ID for user profile retrieval.
            session_id: Session ID for session context retrieval.
            message: Current message for semantic search.

        Returns:
            Dictionary with retrieved learnings by type.
        """
        results: Dict[str, Any] = {}

        # User Profile
        if self.user_profile_store and user_id:
            profile = self.user_profile_store.get(user_id)
            if profile:
                results["user_profile"] = profile

        # Session Context
        if self.session_context_store and session_id:
            context = self.session_context_store.get(session_id)
            if context:
                results["session_context"] = context

        # Learned Knowledge (semantic search)
        if self.knowledge_store and message:
            learnings = self.knowledge_store.search(message)
            if learnings:
                results["learned_knowledge"] = learnings

        return results

    async def arecall(
        self,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        message: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Async version of recall."""
        results: Dict[str, Any] = {}

        if self.user_profile_store and user_id:
            profile = await self.user_profile_store.aget(user_id)
            if profile:
                results["user_profile"] = profile

        if self.session_context_store and session_id:
            context = await self.session_context_store.aget(session_id)
            if context:
                results["session_context"] = context

        if self.knowledge_store and message:
            learnings = await self.knowledge_store.asearch(message)
            if learnings:
                results["learned_knowledge"] = learnings

        return results

    def process(
        self,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        messages: Optional[List] = None,
        model: Optional[Any] = None,
    ) -> None:
        """Extract and save learnings after agent runs.

        Called in background based on timing config.

        Args:
            user_id: User ID for user profile extraction.
            session_id: Session ID for session context extraction.
            messages: Conversation messages to analyze.
            model: LLM model for extraction.
        """
        extraction_model = model or self.model
        if not extraction_model:
            log_warning("LearningMachine.process: No model available for extraction")
            return

        if not messages:
            return

        # User Profile extraction (BACKGROUND mode only)
        if (self.user_profile_store and
            user_id and
            self.user_profile_config and
            self.user_profile_config.mode == LearningMode.BACKGROUND):
            try:
                self.user_profile_store.extract_and_save(
                    user_id=user_id,
                    messages=messages,
                    model=extraction_model,
                )
            except Exception as e:
                log_warning(f"Error in user profile extraction: {e}")

        # Session Context extraction (always BACKGROUND)
        if self.session_context_store and session_id and self.session_context_config:
            try:
                self.session_context_store.extract_and_save(
                    session_id=session_id,
                    messages=messages,
                    model=extraction_model,
                    enable_planning=self.session_context_config.enable_planning,
                )
            except Exception as e:
                log_warning(f"Error in session context extraction: {e}")

    async def aprocess(
        self,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        messages: Optional[List] = None,
        model: Optional[Any] = None,
    ) -> None:
        """Async version of process."""
        extraction_model = model or self.model
        if not extraction_model:
            log_warning("LearningMachine.aprocess: No model available for extraction")
            return

        if not messages:
            return

        # User Profile extraction
        if (self.user_profile_store and
            user_id and
            self.user_profile_config and
            self.user_profile_config.mode == LearningMode.BACKGROUND):
            try:
                await self.user_profile_store.aextract_and_save(
                    user_id=user_id,
                    messages=messages,
                    model=extraction_model,
                )
            except Exception as e:
                log_warning(f"Error in user profile extraction: {e}")

        # Session Context extraction
        if self.session_context_store and session_id and self.session_context_config:
            try:
                await self.session_context_store.aextract_and_save(
                    session_id=session_id,
                    messages=messages,
                    model=extraction_model,
                    enable_planning=self.session_context_config.enable_planning,
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
            if hasattr(profile, 'get_memories_text'):
                memories_text = profile.get_memories_text()
            elif hasattr(profile, 'memories') and profile.memories:
                memories_text = "\n".join(
                    f"- {m.get('content', str(m))}" for m in profile.memories
                )
            else:
                memories_text = None

            if memories_text:
                parts.append(dedent(f"""\
                    <user_profile>
                    You have information about this user from previous interactions:
                    {memories_text}

                    Use this to personalize your responses. Prefer information from the current conversation over past memories.
                    </user_profile>
                """))

        # Session Context
        if "session_context" in recall_results:
            context = recall_results["session_context"]
            if hasattr(context, 'get_context_text'):
                context_text = context.get_context_text()
            elif hasattr(context, 'summary') and context.summary:
                context_text = f"Summary: {context.summary}"
            else:
                context_text = None

            if context_text:
                parts.append(dedent(f"""\
                    <session_context>
                    Here is context from earlier in this session:
                    {context_text}

                    Use this to maintain continuity. Current conversation takes precedence.
                    </session_context>
                """))

        # Learned Knowledge
        if "learned_knowledge" in recall_results:
            learnings = recall_results["learned_knowledge"]
            if learnings:
                learnings_text = ""
                for i, learning in enumerate(learnings, 1):
                    if hasattr(learning, 'to_text'):
                        learnings_text += f"\n{i}. {learning.to_text()}"
                    elif hasattr(learning, 'title') and hasattr(learning, 'learning'):
                        learnings_text += f"\n{i}. {learning.title}: {learning.learning}"
                    else:
                        learnings_text += f"\n{i}. {learning}"

                parts.append(dedent(f"""\
                    <relevant_learnings>
                    The following learnings from past interactions may be relevant:
                    {learnings_text}

                    Apply these insights where appropriate.
                    </relevant_learnings>
                """))

        return "\n".join(parts)

    # -------------------------------------------------------------------------
    # Private Methods
    # -------------------------------------------------------------------------

    def _build_instructions(self) -> str:
        """Build default learning instructions for the system prompt."""
        sections = []

        # Only add instructions if we have enabled features
        enabled_features = []
        if self.user_profile_config:
            enabled_features.append("user profile")
        if self.session_context_config:
            enabled_features.append("session context")
        if self.knowledge_config:
            enabled_features.append("learned knowledge")

        if not enabled_features:
            return ""

        sections.append("You are a learning agent that improves over time.")

        # Tools section
        tool_lines = []
        if self.user_profile_config and self.user_profile_config.enable_tool:
            tool_lines.append(
                "- `save_user_memory(memory)`: Save a memory about the current user. "
                "Use this to remember important information like preferences, context, or facts."
            )
        if self.knowledge_config and self.knowledge_config.enable_tool:
            tool_lines.append(
                "- `save_learning(title, learning, context, tags)`: Save a reusable insight. "
                "Only call after user confirms a proposed learning."
            )

        if tool_lines:
            sections.append("## Learning Tools\n" + "\n".join(tool_lines))

        # PROPOSE mode instructions
        if self.knowledge_config and self.knowledge_config.mode == LearningMode.PROPOSE:
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

            Only call `save_learning` AFTER the user confirms with "yes".

            What makes a good learning:
            - **Specific**: "Check expense ratio AND tracking error" not "Look at metrics"
            - **Actionable**: Can be directly applied in future queries
            - **Generalizable**: Useful beyond this specific question

            Most conversations won't produce a learning. That's expected.
        """)

    def _create_save_user_memory_tool(self, user_id: str) -> Callable:
        """Create the save_user_memory tool function."""
        store = self.user_profile_store

        def save_user_memory(memory: str) -> str:
            """Save a memory about the current user.

            Use this to remember important information about the user like:
            - Personal facts (name, occupation, location)
            - Preferences (communication style, interests)
            - Context (current projects, goals)

            Args:
                memory: The memory to save about the user.

            Returns:
                Confirmation message.
            """
            if not memory or not memory.strip():
                return "Cannot save empty memory."

            try:
                store.add_memory(user_id=user_id, memory=memory.strip())
                return f"Memory saved: {memory.strip()}"
            except Exception as e:
                return f"Failed to save memory: {e}"

        return save_user_memory

    def _create_save_learning_tool(self) -> Callable:
        """Create the save_learning tool function."""
        store = self.knowledge_store

        def save_learning(
            title: str,
            learning: str,
            context: Optional[str] = None,
            tags: Optional[List[str]] = None,
        ) -> str:
            """Save a reusable learning to the knowledge base.

            Only call this AFTER the user has confirmed they want to save.

            A learning should be:
            - Specific and actionable
            - Applicable to future similar tasks
            - Based on what actually worked

            Args:
                title: Short descriptive title (e.g., "API rate limit handling")
                learning: The actual insight (be specific!)
                context: When/why this applies (optional)
                tags: Relevant tags for retrieval (optional)

            Returns:
                Confirmation message.
            """
            if not title or not title.strip():
                return "Cannot save: title is required."
            if not learning or not learning.strip():
                return "Cannot save: learning content is required."
            if len(learning.strip()) < 20:
                return "Cannot save: learning is too short. Be more specific."

            try:
                success = store.save(
                    title=title.strip(),
                    learning=learning.strip(),
                    context=context.strip() if context else None,
                    tags=tags or [],
                )
                if success:
                    return f"Learning saved: '{title.strip()}'"
                else:
                    return "Failed to save learning."
            except Exception as e:
                return f"Failed to save learning: {e}"

        return save_learning


# Convenience function for creating LearningMachine with defaults
def create_learning_machine(
    db=None,
    knowledge=None,
    **kwargs,
) -> LearningMachine:
    """Create a LearningMachine with sensible defaults.

    Args:
        db: Database connection.
        knowledge: Knowledge base for learned knowledge.
        **kwargs: Additional config overrides.

    Returns:
        Configured LearningMachine instance.
    """
    return LearningMachine(
        db=db,
        knowledge=knowledge,
        **kwargs,
    )
