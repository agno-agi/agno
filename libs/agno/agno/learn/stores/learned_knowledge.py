"""
Learned Knowledge Store
=======================
Storage backend for Learned Knowledge learning type.

Stores reusable insights that apply across users and agents.
Think of it as:
- UserProfile = what you know about a person
- SessionContext = what happened in this meeting
- LearnedKnowledge = reusable insights that apply anywhere

Key Features:
- TWO agent tools: save_learning and search_learnings
- Semantic search for relevant learnings
- Shared across all agents using the same knowledge base
- Supports namespace-based scoping for privacy/sharing control:
    - namespace="user": Private per user (scoped by user_id)
    - namespace="global": Shared with everyone (default)
    - namespace="<custom>": Custom grouping (literal string, e.g., "engineering")

Supported Modes:
- AGENTIC: Agent calls save_learning directly when it discovers insights
- PROPOSE: Agent proposes learnings, user approves before saving
- BACKGROUND: Automatic extraction with duplicate detection
"""

from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime, timezone
from os import getenv
from textwrap import dedent
from typing import Any, Callable, List, Optional

from agno.learn.config import LearnedKnowledgeConfig, LearningMode
from agno.learn.schemas import LearnedKnowledge
from agno.learn.stores.protocol import LearningStore
from agno.learn.utils import to_dict_safe
from agno.utils.log import (
    log_debug,
    log_warning,
    set_log_level_to_debug,
    set_log_level_to_info,
)


@dataclass
class LearnedKnowledgeStore(LearningStore):
    """Storage backend for Learned Knowledge learning type.

    Uses a Knowledge base with vector embeddings for semantic search.
    Supports namespace-based scoping for privacy/sharing control.

    Namespace Scoping:
    - namespace="global": Shared with everyone (default)
    - namespace="user": Private per user (requires user_id)
    - namespace="<custom>": Custom grouping (e.g., "engineering", "sales")

    Provides TWO tools to the agent (when enable_agent_tools=True):
    1. search_learnings - Find relevant learnings via semantic search
    2. save_learning - Save reusable insights

    Args:
        config: LearnedKnowledgeConfig with all settings including knowledge base.
        debug_mode: Enable debug logging.
    """

    config: LearnedKnowledgeConfig = field(default_factory=LearnedKnowledgeConfig)
    debug_mode: bool = False

    # State tracking (internal)
    learning_saved: bool = field(default=False, init=False)
    _schema: Any = field(default=None, init=False)

    def __post_init__(self):
        self._schema = self.config.schema or LearnedKnowledge

        if self.config.mode == LearningMode.HITL:
            log_warning(
                "LearnedKnowledgeStore does not support HITL mode. "
                "Use PROPOSE mode for human-in-the-loop approval. "
                "Falling back to PROPOSE mode."
            )

    # =========================================================================
    # LearningStore Protocol Implementation
    # =========================================================================

    @property
    def learning_type(self) -> str:
        """Unique identifier for this learning type."""
        return "learned_knowledge"

    @property
    def schema(self) -> Any:
        """Schema class used for learnings."""
        return self._schema

    def recall(
        self,
        message: Optional[str] = None,
        query: Optional[str] = None,
        user_id: Optional[str] = None,
        namespace: Optional[str] = None,
        limit: int = 5,
        **kwargs,
    ) -> Optional[List[Any]]:
        """Retrieve relevant learnings via semantic search.

        Args:
            message: Current user message to find relevant learnings for.
            query: Alternative query string (if message not provided).
            user_id: User ID for "user" namespace scoping.
            namespace: Filter by namespace (None = all accessible).
            limit: Maximum number of results.
            **kwargs: Additional context (ignored).

        Returns:
            List of relevant learnings, or None if no query.
        """
        search_query = message or query
        if not search_query:
            return None

        results = self.search(
            query=search_query,
            user_id=user_id,
            namespace=namespace,
            limit=limit,
        )
        return results if results else None

    async def arecall(
        self,
        message: Optional[str] = None,
        query: Optional[str] = None,
        user_id: Optional[str] = None,
        namespace: Optional[str] = None,
        limit: int = 5,
        **kwargs,
    ) -> Optional[List[Any]]:
        """Async version of recall."""
        search_query = message or query
        if not search_query:
            return None

        results = await self.asearch(
            query=search_query,
            user_id=user_id,
            namespace=namespace,
            limit=limit,
        )
        return results if results else None

    def process(
        self,
        messages: List[Any],
        user_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
        namespace: Optional[str] = None,
        **kwargs,
    ) -> None:
        """Extract learned knowledge from messages.

        Args:
            messages: Conversation messages to analyze.
            user_id: User context (for "user" namespace scoping).
            agent_id: Agent context (stored for audit).
            team_id: Team context (stored for audit).
            namespace: Namespace to save learnings to (default: "global").
            **kwargs: Additional context (ignored).
        """
        if self.config.mode != LearningMode.BACKGROUND:
            return

        if not messages:
            return

        self._extract_and_save(
            messages=messages,
            user_id=user_id,
            agent_id=agent_id,
            team_id=team_id,
            namespace=namespace,
        )

    async def aprocess(
        self,
        messages: List[Any],
        user_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
        namespace: Optional[str] = None,
        **kwargs,
    ) -> None:
        """Async version of process."""
        if self.config.mode != LearningMode.BACKGROUND:
            return

        if not messages or not self.model or not self.knowledge:
            return

        await self._aextract_and_save(
            messages=messages,
            user_id=user_id,
            agent_id=agent_id,
            team_id=team_id,
            namespace=namespace,
        )

    def build_context(self, data: Any) -> str:
        """Build context with tool usage instructions for the agent.

        Args:
            data: List of learning objects from recall() (may be None).

        Returns:
            Formatted context string with tool instructions.
        """
        mode = self.config.mode

        if mode == LearningMode.PROPOSE:
            return self._build_propose_mode_context(data=data)
        elif mode == LearningMode.AGENTIC:
            return self._build_agentic_mode_context(data=data)
        else:
            return self._build_background_mode_context(data=data)

    def _build_agentic_mode_context(self, data: Any) -> str:
        """Build context for AGENTIC mode."""
        instructions = dedent("""\
            <learnings_system>
            ## Knowledge Tools

            You have access to a knowledge base of reusable learnings:

            | Tool | Purpose |
            |------|---------|
            | `search_learnings` | Find relevant prior insights before answering |
            | `save_learning` | Store a new reusable insight |

            ## Workflow

            1. **Search First** — Before complex tasks, call `search_learnings` with key concepts.
               Apply any relevant learnings naturally.

            2. **Work** — Complete the task using available tools and information.

            3. **Reflect** — After answering, consider: did this reveal a genuinely reusable insight?
               Most queries will NOT produce a learning. That's expected.

            4. **Save** — If you discovered something worth preserving, call `save_learning` directly.

            ## What Makes a Good Learning

            Save if it's:
            - **Specific**: "When comparing ETFs, check expense ratio AND tracking error" not "Look at metrics"
            - **Actionable**: Can be directly applied to future similar tasks
            - **Generalizable**: Useful beyond this specific question

            Do NOT save: Raw facts, one-off answers, summaries, obvious information, or user-specific details.
            </learnings_system>\
        """)

        if data:
            learnings = data if isinstance(data, list) else [data]
            if learnings:
                formatted = self._format_learnings_for_context(learnings=learnings)
                instructions += f"\n\n<prior_learnings>\n{formatted}\n</prior_learnings>"

        return instructions

    def _build_propose_mode_context(self, data: Any) -> str:
        """Build context for PROPOSE mode."""
        instructions = dedent("""\
            <learnings_system>
            ## Knowledge Tools

            You have access to a knowledge base of reusable learnings:

            | Tool | Purpose |
            |------|---------|
            | `search_learnings` | Find relevant prior insights before answering |
            | `save_learning` | Store a new insight (REQUIRES user approval first) |

            ## Workflow

            1. **Search First** — Before complex tasks, call `search_learnings` with key concepts.

            2. **Work** — Complete the task using available tools and information.

            3. **Reflect** — After answering, consider: did this reveal a genuinely reusable insight?

            4. **Propose** — If you have a genuine insight, propose it at the end of your response:

            ---
            **Proposed Learning**

            **Title:** [concise, descriptive title]
            **Context:** [when this applies]
            **Learning:** [the insight — specific and actionable]

            Save this learning? (yes/no)
            ---

            5. **Wait for Approval** — Only call `save_learning` AFTER the user says "yes".

            ## What Makes a Good Learning

            Propose if it's:
            - **Specific**: "When comparing ETFs, check expense ratio AND tracking error" not "Look at metrics"
            - **Actionable**: Can be directly applied to future similar tasks
            - **Generalizable**: Useful beyond this specific question

            Do NOT propose: Raw facts, one-off answers, summaries, obvious information, or user-specific details.
            </learnings_system>\
        """)

        if data:
            learnings = data if isinstance(data, list) else [data]
            if learnings:
                formatted = self._format_learnings_for_context(learnings=learnings)
                instructions += f"\n\n<prior_learnings>\n{formatted}\n</prior_learnings>"

        return instructions

    def _build_background_mode_context(self, data: Any) -> str:
        """Build context for BACKGROUND mode (just show relevant learnings)."""
        if not data:
            return ""

        learnings = data if isinstance(data, list) else [data]
        if not learnings:
            return ""

        formatted = self._format_learnings_for_context(learnings=learnings)
        return dedent(f"""\
            <relevant_learnings>
            Previously learned insights that may be relevant:

            {formatted}

            Use these if helpful. Current conversation takes precedence.
            </relevant_learnings>\
        """)

    def _format_learnings_for_context(self, learnings: List[Any]) -> str:
        """Format learnings for inclusion in context."""
        parts = []
        for i, learning in enumerate(learnings, 1):
            formatted = self._format_single_learning(learning=learning)
            if formatted:
                parts.append(f"{i}. {formatted}")
        return "\n".join(parts)

    def get_tools(
        self,
        user_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
        namespace: Optional[str] = None,
        **kwargs,
    ) -> List[Callable]:
        """Get tools to expose to agent.

        Args:
            user_id: User context (for "user" namespace scoping).
            agent_id: Agent context (stored for audit on saves).
            team_id: Team context (stored for audit on saves).
            namespace: Default namespace for saves (default: "global").
            **kwargs: Additional context (ignored).

        Returns:
            List of callable tools (empty if enable_agent_tools=False).
        """
        if not self.config.enable_agent_tools:
            return []
        return self.get_agent_tools(
            user_id=user_id,
            agent_id=agent_id,
            team_id=team_id,
            namespace=namespace,
        )

    async def aget_tools(
        self,
        user_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
        namespace: Optional[str] = None,
        **kwargs,
    ) -> List[Callable]:
        """Async version of get_tools."""
        if not self.config.enable_agent_tools:
            return []
        return await self.aget_agent_tools(
            user_id=user_id,
            agent_id=agent_id,
            team_id=team_id,
            namespace=namespace,
        )

    @property
    def was_updated(self) -> bool:
        """Check if a learning was saved in last operation."""
        return self.learning_saved

    # =========================================================================
    # Properties
    # =========================================================================

    @property
    def knowledge(self):
        """The knowledge base (vector store)."""
        return self.config.knowledge

    @property
    def model(self):
        """Model for extraction (if needed)."""
        return self.config.model

    # =========================================================================
    # Debug/Logging
    # =========================================================================

    def set_log_level(self):
        """Set log level based on debug_mode or environment variable."""
        if self.debug_mode or getenv("AGNO_DEBUG", "false").lower() == "true":
            self.debug_mode = True
            set_log_level_to_debug()
        else:
            set_log_level_to_info()

    # =========================================================================
    # Agent Tools
    # =========================================================================

    def get_agent_tools(
        self,
        user_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
        namespace: Optional[str] = None,
    ) -> List[Callable]:
        """Get the tools to expose to the agent.

        Returns TWO tools (based on config settings):
        1. search_learnings - Find relevant learnings
        2. save_learning - Save reusable insights

        Args:
            user_id: User context (for "user" namespace scoping).
            agent_id: Agent context (stored for audit on saves).
            team_id: Team context (stored for audit on saves).
            namespace: Default namespace for saves (default: "global").

        Returns:
            List of callable tools.
        """
        tools = []

        if self.config.enable_search:
            tools.append(self._create_search_learnings_tool(user_id=user_id))

        if self.config.enable_save:
            tools.append(
                self._create_save_learning_tool(
                    user_id=user_id,
                    agent_id=agent_id,
                    team_id=team_id,
                    default_namespace=namespace,
                )
            )

        return tools

    async def aget_agent_tools(
        self,
        user_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
        namespace: Optional[str] = None,
    ) -> List[Callable]:
        """Async version of get_agent_tools."""
        tools = []

        if self.config.enable_search:
            tools.append(self._create_async_search_learnings_tool(user_id=user_id))

        if self.config.enable_save:
            tools.append(
                self._create_async_save_learning_tool(
                    user_id=user_id,
                    agent_id=agent_id,
                    team_id=team_id,
                    default_namespace=namespace,
                )
            )

        return tools

    # =========================================================================
    # Tool: save_learning
    # =========================================================================

    def _create_save_learning_tool(
        self,
        user_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
        default_namespace: Optional[str] = None,
    ) -> Callable:
        """Create the save_learning tool for the agent."""

        def save_learning(
            title: str,
            learning: str,
            context: Optional[str] = None,
            tags: Optional[List[str]] = None,
            namespace: Optional[str] = None,
        ) -> str:
            """Save a reusable insight or learning to the knowledge base.

            Use this when you discover something that would be useful to
            remember for future conversations - patterns, best practices,
            solutions to problems, or insights from the current interaction.

            Good learnings are:
            - Reusable across different contexts
            - Specific and actionable
            - Not user-specific (use user memory for that)

            Args:
                title: Short descriptive title (e.g., "Python async best practices")
                learning: The actual insight or knowledge to save.
                context: When/where this applies (optional).
                tags: Categories for this learning (optional).
                namespace: Scope for this learning (optional).
                    - "global": Shared with everyone (default)
                    - "user": Private to current user
                    - "<custom>": Custom grouping (e.g., "engineering")

            Returns:
                Confirmation message.
            """
            effective_namespace = namespace or default_namespace or "global"

            success = self.save(
                title=title,
                learning=learning,
                context=context,
                tags=tags,
                user_id=user_id,
                agent_id=agent_id,
                team_id=team_id,
                namespace=effective_namespace,
            )
            if success:
                self.learning_saved = True
                return f"Learning saved: {title} (namespace: {effective_namespace})"
            return "Failed to save learning"

        return save_learning

    def _create_async_save_learning_tool(
        self,
        user_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
        default_namespace: Optional[str] = None,
    ) -> Callable:
        """Create the async save_learning tool for the agent."""

        async def save_learning(
            title: str,
            learning: str,
            context: Optional[str] = None,
            tags: Optional[List[str]] = None,
            namespace: Optional[str] = None,
        ) -> str:
            """Save a reusable insight or learning to the knowledge base.

            Use this when you discover something that would be useful to
            remember for future conversations - patterns, best practices,
            solutions to problems, or insights from the current interaction.

            Good learnings are:
            - Reusable across different contexts
            - Specific and actionable
            - Not user-specific (use user memory for that)

            Args:
                title: Short descriptive title (e.g., "Python async best practices")
                learning: The actual insight or knowledge to save.
                context: When/where this applies (optional).
                tags: Categories for this learning (optional).
                namespace: Scope for this learning (optional).
                    - "global": Shared with everyone (default)
                    - "user": Private to current user
                    - "<custom>": Custom grouping (e.g., "engineering")

            Returns:
                Confirmation message.
            """
            effective_namespace = namespace or default_namespace or "global"

            success = await self.asave(
                title=title,
                learning=learning,
                context=context,
                tags=tags,
                user_id=user_id,
                agent_id=agent_id,
                team_id=team_id,
                namespace=effective_namespace,
            )
            if success:
                self.learning_saved = True
                return f"Learning saved: {title} (namespace: {effective_namespace})"
            return "Failed to save learning"

        return save_learning

    # =========================================================================
    # Tool: search_learnings
    # =========================================================================

    def _create_search_learnings_tool(
        self,
        user_id: Optional[str] = None,
    ) -> Callable:
        """Create the search_learnings tool for the agent."""

        def search_learnings(
            query: str,
            limit: int = 5,
            namespace: Optional[str] = None,
        ) -> str:
            """Search for relevant learnings in the knowledge base.

            Use this when you need to recall insights, patterns, or solutions
            that may have been learned in previous conversations. The search
            uses semantic similarity to find relevant learnings.

            Args:
                query: What you're looking for (e.g., "database performance tips")
                limit: Maximum number of results to return (default: 5)
                namespace: Filter by namespace (optional).
                    - None: Search all accessible learnings
                    - "global": Only shared learnings
                    - "user": Only user's private learnings
                    - "<custom>": Only learnings in custom namespace

            Returns:
                Formatted list of relevant learnings, or message if none found.
            """
            results = self.search(
                query=query,
                user_id=user_id,
                namespace=namespace,
                limit=limit,
            )

            if not results:
                return "No relevant learnings found."

            formatted = self._format_learnings_list(learnings=results)
            return f"Found {len(results)} relevant learning(s):\n\n{formatted}"

        return search_learnings

    def _create_async_search_learnings_tool(
        self,
        user_id: Optional[str] = None,
    ) -> Callable:
        """Create the async search_learnings tool for the agent."""

        async def search_learnings(
            query: str,
            limit: int = 5,
            namespace: Optional[str] = None,
        ) -> str:
            """Search for relevant learnings in the knowledge base.

            Use this when you need to recall insights, patterns, or solutions
            that may have been learned in previous conversations. The search
            uses semantic similarity to find relevant learnings.

            Args:
                query: What you're looking for (e.g., "database performance tips")
                limit: Maximum number of results to return (default: 5)
                namespace: Filter by namespace (optional).
                    - None: Search all accessible learnings
                    - "global": Only shared learnings
                    - "user": Only user's private learnings
                    - "<custom>": Only learnings in custom namespace

            Returns:
                Formatted list of relevant learnings, or message if none found.
            """
            results = await self.asearch(
                query=query,
                user_id=user_id,
                namespace=namespace,
                limit=limit,
            )

            if not results:
                return "No relevant learnings found."

            formatted = self._format_learnings_list(learnings=results)
            return f"Found {len(results)} relevant learning(s):\n\n{formatted}"

        return search_learnings

    # =========================================================================
    # Search Operations
    # =========================================================================

    def search(
        self,
        query: str,
        user_id: Optional[str] = None,
        namespace: Optional[str] = None,
        limit: int = 5,
    ) -> List[Any]:
        """Search for relevant learnings based on query.

        Uses semantic search to find learnings most relevant to the query.

        Args:
            query: The search query.
            user_id: User ID for "user" namespace access.
            namespace: Filter by namespace (None = all accessible).
            limit: Maximum number of results to return.

        Returns:
            List of learning objects matching the query.
        """
        if not self.knowledge:
            log_warning("LearnedKnowledgeStore.search: no knowledge base configured")
            return []

        try:
            # Build filters based on namespace
            filters = self._build_search_filters(user_id=user_id, namespace=namespace)

            # Search with filters if supported
            if (
                filters
                and hasattr(self.knowledge, "search")
                and "filters" in self.knowledge.search.__code__.co_varnames
            ):
                results = self.knowledge.search(query=query, num_documents=limit, filters=filters)
            else:
                results = self.knowledge.search(query=query, num_documents=limit)

            learnings = []
            for result in results or []:
                learning = self._parse_result(result=result)
                if learning:
                    # Post-filter by namespace if KB doesn't support filtering
                    if self._matches_namespace_filter(learning, user_id=user_id, namespace=namespace):
                        learnings.append(learning)

            log_debug(f"LearnedKnowledgeStore.search: found {len(learnings)} learnings for query: {query[:50]}...")
            return learnings[:limit]

        except Exception as e:
            log_warning(f"LearnedKnowledgeStore.search failed: {e}")
            return []

    async def asearch(
        self,
        query: str,
        user_id: Optional[str] = None,
        namespace: Optional[str] = None,
        limit: int = 5,
    ) -> List[Any]:
        """Async version of search."""
        if not self.knowledge:
            log_warning("LearnedKnowledgeStore.asearch: no knowledge base configured")
            return []

        try:
            # Build filters based on namespace
            filters = self._build_search_filters(user_id=user_id, namespace=namespace)

            # Search with filters if supported
            if hasattr(self.knowledge, "asearch"):
                if filters and "filters" in self.knowledge.asearch.__code__.co_varnames:
                    results = await self.knowledge.asearch(query=query, num_documents=limit, filters=filters)
                else:
                    results = await self.knowledge.asearch(query=query, num_documents=limit)
            else:
                if (
                    filters
                    and hasattr(self.knowledge, "search")
                    and "filters" in self.knowledge.search.__code__.co_varnames
                ):
                    results = self.knowledge.search(query=query, num_documents=limit, filters=filters)
                else:
                    results = self.knowledge.search(query=query, num_documents=limit)

            learnings = []
            for result in results or []:
                learning = self._parse_result(result=result)
                if learning:
                    # Post-filter by namespace if KB doesn't support filtering
                    if self._matches_namespace_filter(learning, user_id=user_id, namespace=namespace):
                        learnings.append(learning)

            log_debug(f"LearnedKnowledgeStore.asearch: found {len(learnings)} learnings for query: {query[:50]}...")
            return learnings[:limit]

        except Exception as e:
            log_warning(f"LearnedKnowledgeStore.asearch failed: {e}")
            return []

    def _build_search_filters(
        self,
        user_id: Optional[str] = None,
        namespace: Optional[str] = None,
    ) -> Optional[dict]:
        """Build search filters for namespace scoping.

        Returns filter dict for knowledge base, or None if no filtering needed.
        """
        if not namespace:
            return None

        if namespace == "user":
            if not user_id:
                log_warning("LearnedKnowledgeStore: 'user' namespace requires user_id")
                return None
            return {"namespace": "user", "user_id": user_id}

        return {"namespace": namespace}

    def _matches_namespace_filter(
        self,
        learning: Any,
        user_id: Optional[str] = None,
        namespace: Optional[str] = None,
    ) -> bool:
        """Check if a learning matches the namespace filter (for post-filtering)."""
        if not namespace:
            return True

        learning_namespace = getattr(learning, "namespace", None) or "global"
        learning_user_id = getattr(learning, "user_id", None)

        if namespace == "user":
            return learning_namespace == "user" and learning_user_id == user_id

        return learning_namespace == namespace

    # =========================================================================
    # Save Operations
    # =========================================================================

    def save(
        self,
        title: str,
        learning: str,
        context: Optional[str] = None,
        tags: Optional[List[str]] = None,
        user_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
        namespace: Optional[str] = None,
    ) -> bool:
        """Save a learning to the knowledge base.

        Args:
            title: Short descriptive title.
            learning: The actual insight.
            context: When/why this applies.
            tags: Tags for categorization.
            user_id: User ID (required for "user" namespace).
            agent_id: Agent that created this (stored as metadata for audit).
            team_id: Team context (stored as metadata for audit).
            namespace: Namespace for scoping (default: "global").

        Returns:
            True if saved successfully, False otherwise.
        """
        if not self.knowledge:
            log_warning("LearnedKnowledgeStore.save: no knowledge base configured")
            return False

        effective_namespace = namespace or "global"

        # Validate "user" namespace has user_id
        if effective_namespace == "user" and not user_id:
            log_warning("LearnedKnowledgeStore.save: 'user' namespace requires user_id")
            return False

        try:
            from agno.knowledge.reader.text_reader import TextReader

            learning_data = {
                "title": title.strip(),
                "learning": learning.strip(),
                "context": context.strip() if context else None,
                "tags": tags or [],
                "namespace": effective_namespace,
                "user_id": user_id if effective_namespace == "user" else None,
                "agent_id": agent_id,
                "team_id": team_id,
                "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            }

            learning_obj = self.schema(**learning_data)
            text_content = self._to_text_content(learning=learning_obj)

            self.knowledge.add_content(
                name=learning_data["title"],
                text_content=text_content,
                reader=TextReader(),
                skip_if_exists=True,
            )

            log_debug(f"LearnedKnowledgeStore.save: saved learning '{title}' (namespace: {effective_namespace})")
            return True

        except Exception as e:
            log_warning(f"LearnedKnowledgeStore.save failed: {e}")
            return False

    async def asave(
        self,
        title: str,
        learning: str,
        context: Optional[str] = None,
        tags: Optional[List[str]] = None,
        user_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
        namespace: Optional[str] = None,
    ) -> bool:
        """Async version of save."""
        if not self.knowledge:
            log_warning("LearnedKnowledgeStore.asave: no knowledge base configured")
            return False

        effective_namespace = namespace or "global"

        # Validate "user" namespace has user_id
        if effective_namespace == "user" and not user_id:
            log_warning("LearnedKnowledgeStore.asave: 'user' namespace requires user_id")
            return False

        try:
            from agno.knowledge.reader.text_reader import TextReader

            learning_data = {
                "title": title.strip(),
                "learning": learning.strip(),
                "context": context.strip() if context else None,
                "tags": tags or [],
                "namespace": effective_namespace,
                "user_id": user_id if effective_namespace == "user" else None,
                "agent_id": agent_id,
                "team_id": team_id,
                "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            }

            learning_obj = self.schema(**learning_data)
            text_content = self._to_text_content(learning=learning_obj)

            if hasattr(self.knowledge, "aadd_content"):
                await self.knowledge.aadd_content(
                    name=learning_data["title"],
                    text_content=text_content,
                    reader=TextReader(),
                    skip_if_exists=True,
                )
            else:
                self.knowledge.add_content(
                    name=learning_data["title"],
                    text_content=text_content,
                    reader=TextReader(),
                    skip_if_exists=True,
                )

            log_debug(f"LearnedKnowledgeStore.asave: saved learning '{title}' (namespace: {effective_namespace})")
            return True

        except Exception as e:
            log_warning(f"LearnedKnowledgeStore.asave failed: {e}")
            return False

    # =========================================================================
    # Delete Operations
    # =========================================================================

    def delete(self, title: str) -> bool:
        """Delete a learning by title.

        Args:
            title: The title of the learning to delete.

        Returns:
            True if deleted, False otherwise.
        """
        if not self.knowledge:
            log_warning("LearnedKnowledgeStore.delete: no knowledge base configured")
            return False

        try:
            if hasattr(self.knowledge, "delete_content"):
                self.knowledge.delete_content(name=title)
                log_debug(f"LearnedKnowledgeStore.delete: deleted learning '{title}'")
                return True
            else:
                log_warning("LearnedKnowledgeStore.delete: knowledge base does not support deletion")
                return False

        except Exception as e:
            log_warning(f"LearnedKnowledgeStore.delete failed: {e}")
            return False

    async def adelete(self, title: str) -> bool:
        """Async version of delete."""
        if not self.knowledge:
            log_warning("LearnedKnowledgeStore.adelete: no knowledge base configured")
            return False

        try:
            if hasattr(self.knowledge, "adelete_content"):
                await self.knowledge.adelete_content(name=title)
            elif hasattr(self.knowledge, "delete_content"):
                self.knowledge.delete_content(name=title)
            else:
                log_warning("LearnedKnowledgeStore.adelete: knowledge base does not support deletion")
                return False

            log_debug(f"LearnedKnowledgeStore.adelete: deleted learning '{title}'")
            return True

        except Exception as e:
            log_warning(f"LearnedKnowledgeStore.adelete failed: {e}")
            return False

    # =========================================================================
    # Background Extraction (BACKGROUND mode)
    # =========================================================================

    def _extract_and_save(
        self,
        messages: List[Any],
        user_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
        namespace: Optional[str] = None,
    ) -> None:
        """Extract learnings from messages (sync)."""
        if not self.model or not self.knowledge:
            return

        try:
            from agno.models.message import Message

            conversation_text = self._messages_to_text(messages=messages)

            # Search for existing learnings to avoid duplicates
            existing = self.search(query=conversation_text[:500], limit=5)
            existing_summary = self._summarize_existing(learnings=existing)

            extraction_messages = self._build_extraction_messages(
                conversation_text=conversation_text,
                existing_summary=existing_summary,
            )

            tools = self._get_extraction_tools(
                user_id=user_id,
                agent_id=agent_id,
                team_id=team_id,
                namespace=namespace,
            )
            functions = self._build_functions_for_model(tools=tools)

            model_copy = deepcopy(self.model)
            response = model_copy.response(
                messages=extraction_messages,
                tools=functions,
            )

            if response.tool_executions:
                self.learning_saved = True
                log_debug("LearnedKnowledgeStore: Extraction saved new learning(s)")

        except Exception as e:
            log_warning(f"LearnedKnowledgeStore._extract_and_save failed: {e}")

    async def _aextract_and_save(
        self,
        messages: List[Any],
        user_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
        namespace: Optional[str] = None,
    ) -> None:
        """Extract learnings from messages (async)."""
        if not self.model or not self.knowledge:
            return

        try:
            from agno.models.message import Message

            conversation_text = self._messages_to_text(messages=messages)

            # Search for existing learnings to avoid duplicates
            existing = await self.asearch(query=conversation_text[:500], limit=5)
            existing_summary = self._summarize_existing(learnings=existing)

            extraction_messages = self._build_extraction_messages(
                conversation_text=conversation_text,
                existing_summary=existing_summary,
            )

            tools = self._get_async_extraction_tools(
                user_id=user_id,
                agent_id=agent_id,
                team_id=team_id,
                namespace=namespace,
            )
            functions = self._build_functions_for_model(tools=tools)

            model_copy = deepcopy(self.model)
            response = await model_copy.aresponse(
                messages=extraction_messages,
                tools=functions,
            )

            if response.tool_executions:
                self.learning_saved = True
                log_debug("LearnedKnowledgeStore: Extraction saved new learning(s)")

        except Exception as e:
            log_warning(f"LearnedKnowledgeStore._aextract_and_save failed: {e}")

    def _build_extraction_messages(
        self,
        conversation_text: str,
        existing_summary: str,
    ) -> List[Any]:
        """Build messages for extraction."""
        from agno.models.message import Message

        system_prompt = dedent("""\
            You are a Learning Extractor. Review conversations for genuinely reusable insights.

            ## What Makes a Good Learning

            Save if it's:
            - **Novel**: Not already captured in existing learnings
            - **Specific**: Concrete guidance, not vague principles
            - **Actionable**: Can be directly applied
            - **Generalizable**: Useful beyond this specific situation

            ## What NOT to Save

            - Raw facts or data
            - User-specific information (belongs in user memory)
            - Obvious or common knowledge
            - One-time answers
            - If unsure, don't save.

        """)

        if existing_summary:
            system_prompt += f"""## Existing Learnings (DO NOT DUPLICATE)
{existing_summary}

"""

        system_prompt += dedent("""\
            ## Instructions
            - Only call save_learning if you find a genuinely novel, reusable insight
            - It's perfectly fine to do nothing if there's nothing worth saving
            - Quality over quantity - one good learning beats many weak ones\
        """)

        return [
            Message(role="system", content=system_prompt),
            Message(role="user", content=f"Review this conversation for reusable learnings:\n\n{conversation_text}"),
        ]

    def _get_extraction_tools(
        self,
        user_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
        namespace: Optional[str] = None,
    ) -> List[Callable]:
        """Get sync extraction tools."""
        effective_namespace = namespace or "global"

        def save_learning(
            title: str,
            learning: str,
            context: Optional[str] = None,
            tags: Optional[List[str]] = None,
        ) -> str:
            """Save a reusable learning.

            Args:
                title: Short descriptive title.
                learning: The actual insight.
                context: When this applies.
                tags: Categories.

            Returns:
                Confirmation.
            """
            success = self.save(
                title=title,
                learning=learning,
                context=context,
                tags=tags,
                user_id=user_id,
                agent_id=agent_id,
                team_id=team_id,
                namespace=effective_namespace,
            )
            return f"Saved: {title}" if success else "Failed to save"

        return [save_learning]

    def _get_async_extraction_tools(
        self,
        user_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
        namespace: Optional[str] = None,
    ) -> List[Callable]:
        """Get async extraction tools."""
        effective_namespace = namespace or "global"

        async def save_learning(
            title: str,
            learning: str,
            context: Optional[str] = None,
            tags: Optional[List[str]] = None,
        ) -> str:
            """Save a reusable learning.

            Args:
                title: Short descriptive title.
                learning: The actual insight.
                context: When this applies.
                tags: Categories.

            Returns:
                Confirmation.
            """
            success = await self.asave(
                title=title,
                learning=learning,
                context=context,
                tags=tags,
                user_id=user_id,
                agent_id=agent_id,
                team_id=team_id,
                namespace=effective_namespace,
            )
            return f"Saved: {title}" if success else "Failed to save"

        return [save_learning]

    def _build_functions_for_model(self, tools: List[Callable]) -> List[Any]:
        """Convert callables to Functions for model."""
        from agno.tools.function import Function

        functions = []
        seen_names = set()

        for tool in tools:
            try:
                name = tool.__name__
                if name in seen_names:
                    continue
                seen_names.add(name)

                func = Function.from_callable(tool, strict=True)
                func.strict = True
                functions.append(func)
            except Exception as e:
                log_warning(f"Could not add function {tool}: {e}")

        return functions

    def _messages_to_text(self, messages: List[Any]) -> str:
        """Convert messages to text for extraction."""
        parts = []
        for msg in messages:
            if msg.role == "user":
                content = msg.get_content_string() if hasattr(msg, "get_content_string") else str(msg.content)
                if content and content.strip():
                    parts.append(f"User: {content}")
            elif msg.role in ["assistant", "model"]:
                content = msg.get_content_string() if hasattr(msg, "get_content_string") else str(msg.content)
                if content and content.strip():
                    parts.append(f"Assistant: {content}")
        return "\n".join(parts)

    def _summarize_existing(self, learnings: List[Any]) -> str:
        """Summarize existing learnings to help avoid duplicates."""
        if not learnings:
            return ""

        parts = []
        for learning in learnings[:5]:
            if hasattr(learning, "title") and hasattr(learning, "learning"):
                parts.append(f"- {learning.title}: {learning.learning[:100]}...")
        return "\n".join(parts)

    # =========================================================================
    # Private Helpers
    # =========================================================================

    def _build_learning_id(self, title: str) -> str:
        """Build a unique learning ID from title."""
        return f"learning_{title.lower().replace(' ', '_')[:32]}"

    def _parse_result(self, result: Any) -> Optional[Any]:
        """Parse a search result into a learning object."""
        import json

        try:
            content = None

            if isinstance(result, dict):
                content = result.get("content") or result.get("text") or result
            elif hasattr(result, "content"):
                content = result.content
            elif hasattr(result, "text"):
                content = result.text
            elif isinstance(result, str):
                content = result

            if not content:
                return None

            if isinstance(content, str):
                try:
                    content = json.loads(content)
                except json.JSONDecodeError:
                    return self.schema(title="Learning", learning=content)

            if isinstance(content, dict):
                from dataclasses import fields

                field_names = {f.name for f in fields(self.schema)}
                filtered = {k: v for k, v in content.items() if k in field_names}
                return self.schema(**filtered)

            return None

        except Exception as e:
            log_warning(f"LearnedKnowledgeStore._parse_result failed: {e}")
            return None

    def _to_text_content(self, learning: Any) -> str:
        """Convert a learning object to text content for storage."""
        import json

        learning_dict = to_dict_safe(learning)
        return json.dumps(learning_dict, ensure_ascii=False)

    def _format_single_learning(self, learning: Any) -> str:
        """Format a single learning for display."""
        parts = []

        if hasattr(learning, "title") and learning.title:
            parts.append(f"**{learning.title}**")

        if hasattr(learning, "learning") and learning.learning:
            parts.append(learning.learning)

        if hasattr(learning, "context") and learning.context:
            parts.append(f"_Context: {learning.context}_")

        if hasattr(learning, "tags") and learning.tags:
            tags_str = ", ".join(learning.tags)
            parts.append(f"_Tags: {tags_str}_")

        if hasattr(learning, "namespace") and learning.namespace and learning.namespace != "global":
            parts.append(f"_Namespace: {learning.namespace}_")

        return "\n   ".join(parts)

    def _format_learnings_list(self, learnings: List[Any]) -> str:
        """Format a list of learnings for tool output."""
        parts = []
        for i, learning in enumerate(learnings, 1):
            formatted = self._format_single_learning(learning=learning)
            if formatted:
                parts.append(f"{i}. {formatted}")
        return "\n".join(parts)

    # =========================================================================
    # Representation
    # =========================================================================

    def __repr__(self) -> str:
        """String representation for debugging."""
        has_knowledge = self.knowledge is not None
        has_model = self.model is not None
        return (
            f"LearnedKnowledgeStore("
            f"mode={self.config.mode.value}, "
            f"knowledge={has_knowledge}, "
            f"model={has_model}, "
            f"enable_agent_tools={self.config.enable_agent_tools})"
        )
