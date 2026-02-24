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
- ALWAYS: Automatic extraction with duplicate detection
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
            log_warning("LearnedKnowledgeStore does not support HITL mode. Use PROPOSE mode for soft approval.")

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
        query: Optional[str] = None,
        message: Optional[str] = None,
        user_id: Optional[str] = None,
        namespace: Optional[str] = None,
        limit: int = 5,
        **kwargs,
    ) -> Optional[List[Any]]:
        """Retrieve relevant learnings via semantic search.

        Args:
            query: Search query (searches title, learning, context).
            message: Current user message to find relevant learnings for (alternative).
            user_id: User ID for "user" namespace scoping.
            namespace: Filter by namespace (None = all accessible).
            limit: Maximum number of results.
            **kwargs: Additional context (ignored).

        Returns:
            List of relevant learnings, or None if no query.
        """
        search_query = query or message
        if not search_query:
            return None

        effective_namespace = namespace or self.config.namespace
        if effective_namespace == "user" and not user_id:
            log_warning("LearnedKnowledgeStore.recall: namespace='user' requires user_id")
            return None

        results = self.search(
            query=search_query,
            user_id=user_id,
            namespace=effective_namespace,
            limit=limit,
        )
        return results if results else None

    async def arecall(
        self,
        query: Optional[str] = None,
        message: Optional[str] = None,
        user_id: Optional[str] = None,
        namespace: Optional[str] = None,
        limit: int = 5,
        **kwargs,
    ) -> Optional[List[Any]]:
        """Async version of recall."""
        search_query = query or message
        if not search_query:
            return None

        effective_namespace = namespace or self.config.namespace
        if effective_namespace == "user" and not user_id:
            log_warning("LearnedKnowledgeStore.arecall: namespace='user' requires user_id")
            return None

        results = await self.asearch(
            query=search_query,
            user_id=user_id,
            namespace=effective_namespace,
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
        # Reset state for this operation
        self.learning_saved = False

        # process only supported in ALWAYS mode
        # for programmatic extraction, use extract_and_save directly
        if self.config.mode != LearningMode.ALWAYS:
            return

        if not messages:
            return

        self.extract_and_save(
            messages=messages,
            user_id=user_id,
            agent_id=agent_id,
            team_id=team_id,
            namespace=namespace,
            run_response=kwargs.get("run_response"),
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
        # Reset state for this operation
        self.learning_saved = False

        if self.config.mode != LearningMode.ALWAYS:
            return

        if not messages:
            return

        await self.aextract_and_save(
            messages=messages,
            user_id=user_id,
            agent_id=agent_id,
            team_id=team_id,
            namespace=namespace,
            run_response=kwargs.get("run_response"),
        )

    def build_context(self, data: Any) -> str:
        """Build context for the agent.

        Args:
            data: List of learning objects from recall() (may be None).

        Returns:
            Context string to inject into the agent's system prompt.
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
            <learning_system>
            You have a knowledge base of reusable learnings from past interactions.

            ## CRITICAL RULES - ALWAYS FOLLOW

            **RULE 1: ALWAYS search before answering substantive questions.**
            When the user asks for advice, recommendations, how-to guidance, or best practices:
            → First call `search_learnings` with relevant keywords
            → Then incorporate any relevant findings into your response

            **RULE 2: ALWAYS search before saving.**
            Before saving anything, first call `search_learnings` to check if similar knowledge exists.
            Only save if it's genuinely new (not a duplicate or minor variation).

            **RULE 3: ALWAYS save when explicitly asked.**
            When the user says "remember", "save", "note", "keep in mind", or similar:
            → These are explicit directives - save what they asked (after searching for duplicates)

            **RULE 4: ALWAYS save team/org goals, constraints, and policies.**
            When the user shares organizational context:
            → "We're trying to..." / "Our goal is..." (team goals)
            → "We can't use..." / "We need to avoid..." (constraints)
            → "Our policy is..." / "We always..." (policies)
            → "Our priority is..." / "We prefer..." at org level (priorities)
            These are shared context - save them so other users benefit too.

            ## Tools

            `search_learnings(query)` - Search for relevant prior insights. Use liberally.
            `save_learning(title, learning, context, tags)` - Save new insights or context.

            ## When to Search

            Search when the user:
            - Asks for recommendations or best practices
            - Asks how to approach a problem
            - Asks about trade-offs or considerations
            - Mentions a technology, domain, or problem area
            - Asks you to save something (check for duplicates first)

            ## When to Save (Self-Discovered Insights)

            For insights you discover yourself (not explicit requests or org context), only save if:
            - Non-obvious (required investigation to discover)
            - Reusable (applies to a category of problems)
            - Actionable (specific enough to apply directly)

            Do NOT save:
            - Raw facts or common knowledge
            - Individual user preferences (use user memory instead)
            - Duplicates of existing learnings
            </learning_system>\
        """)

        if data:
            learnings = data if isinstance(data, list) else [data]
            if learnings:
                formatted = self._format_learnings_for_context(learnings=learnings)
                instructions += f"\n\n<relevant_learnings>\nPrior insights that may help with this task:\n\n{formatted}\n\nApply these naturally if relevant. Current context takes precedence.\n</relevant_learnings>"

        return instructions

    def _build_propose_mode_context(self, data: Any) -> str:
        """Build context for PROPOSE mode."""
        instructions = dedent("""\
            <learning_system>
            You have a knowledge base of reusable learnings. In PROPOSE mode, saving requires user approval.

            ## CRITICAL RULES - ALWAYS FOLLOW

            **RULE 1: ALWAYS search before answering substantive questions.**
            When the user asks for advice, recommendations, how-to guidance, or best practices:
            → First call `search_learnings` with relevant keywords
            → Then incorporate any relevant findings into your response

            **RULE 2: Propose learnings, don't save directly.**
            If you discover something worth preserving, propose it at the end of your response:

            ---
            **Proposed Learning**
            **Title:** [Concise title]
            **Context:** [When this applies]
            **Insight:** [The learning - specific and actionable]

            Save this to the knowledge base? (yes/no)
            ---

            **RULE 3: Only save after explicit approval.**
            Call `save_learning` ONLY after the user says "yes" to your proposal.
            Before saving, search first to check for duplicates.

            ## Tools

            `search_learnings(query)` - Search for relevant prior insights. Use liberally.
            `save_learning(title, learning, context, tags)` - Save ONLY after user approval.

            ## What to Propose

            Only propose insights that are:
            - Non-obvious (required investigation to discover)
            - Reusable (applies to a category of problems)
            - Actionable (specific enough to apply directly)

            Do NOT propose:
            - Raw facts or common knowledge
            - User-specific preferences
            - Things the user already knew
            </learning_system>\
        """)

        if data:
            learnings = data if isinstance(data, list) else [data]
            if learnings:
                formatted = self._format_learnings_for_context(learnings=learnings)
                instructions += f"\n\n<relevant_learnings>\nPrior insights that may help:\n\n{formatted}\n\nApply these naturally if relevant.\n</relevant_learnings>"

        return instructions

    def _build_background_mode_context(self, data: Any) -> str:
        """Build context for ALWAYS mode (just show relevant learnings)."""
        if not data:
            return ""

        learnings = data if isinstance(data, list) else [data]
        if not learnings:
            return ""

        formatted = self._format_learnings_for_context(learnings=learnings)
        return dedent(f"""\
            <relevant_learnings>
            Prior insights that may help with this task:

            {formatted}

            Apply these naturally if they're relevant to the current request.
            Your current analysis and the user's specific context take precedence.
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

        if self.config.agent_can_search:
            tools.append(
                self._create_search_learnings_tool(namespace=namespace or self.config.namespace, user_id=user_id)
            )

        if self.config.agent_can_save:
            tools.append(
                self._create_save_learning_tool(
                    namespace=namespace or self.config.namespace,
                    user_id=user_id,
                    agent_id=agent_id,
                    team_id=team_id,
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

        if self.config.agent_can_search:
            tools.append(
                self._create_async_search_learnings_tool(namespace=namespace or self.config.namespace, user_id=user_id)
            )

        if self.config.agent_can_save:
            tools.append(
                self._create_async_save_learning_tool(
                    namespace=namespace or self.config.namespace,
                    user_id=user_id,
                    agent_id=agent_id,
                    team_id=team_id,
                )
            )

        return tools

    # =========================================================================
    # Tool: save_learning
    # =========================================================================

    def _create_save_learning_tool(
        self,
        namespace: str,
        user_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
    ) -> Callable:
        """Create the save_learning tool for the agent."""

        def save_learning(
            title: str,
            learning: str,
            context: Optional[str] = None,
            tags: Optional[List[str]] = None,
        ) -> str:
            """Save a reusable insight or organizational context to the knowledge base.

            IMPORTANT: You MUST call search_learnings first to check for duplicates.

            Args:
                title: Concise, searchable title.
                learning: The insight or context - specific and actionable.
                context: When/where this applies.
                tags: Categories for organization.

            Returns:
                Confirmation message.
            """
            success = self.save(
                title=title,
                learning=learning,
                context=context,
                tags=tags,
                user_id=user_id,
                agent_id=agent_id,
                team_id=team_id,
                namespace=namespace,
            )
            if success:
                self.learning_saved = True
                return f"Learning saved: {title} (namespace: {namespace})"
            return "Failed to save learning"

        return save_learning

    def _create_async_save_learning_tool(
        self,
        namespace: str,
        user_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
    ) -> Callable:
        """Create the async save_learning tool for the agent."""

        async def save_learning(
            title: str,
            learning: str,
            context: Optional[str] = None,
            tags: Optional[List[str]] = None,
        ) -> str:
            """Save a reusable insight or organizational context to the knowledge base.

            IMPORTANT: You MUST call search_learnings first to check for duplicates.

            Args:
                title: Concise, searchable title.
                learning: The insight or context - specific and actionable.
                context: When/where this applies.
                tags: Categories for organization.

            Returns:
                Confirmation message.
            """
            success = await self.asave(
                title=title,
                learning=learning,
                context=context,
                tags=tags,
                user_id=user_id,
                agent_id=agent_id,
                team_id=team_id,
                namespace=namespace,
            )
            if success:
                self.learning_saved = True
                return f"Learning saved: {title} (namespace: {namespace})"
            return "Failed to save learning"

        return save_learning

    # =========================================================================
    # Tool: search_learnings
    # =========================================================================

    def _create_search_learnings_tool(
        self,
        namespace: str,
        user_id: Optional[str] = None,
    ) -> Callable:
        """Create the search_learnings tool for the agent."""

        def search_learnings(
            query: str,
            limit: int = 5,
        ) -> str:
            """Search for relevant insights in the knowledge base.

            ALWAYS call this:
            1. Before answering questions about best practices, recommendations, or how-to
            2. Before saving a new learning (to check for duplicates)

            Args:
                query: Keywords describing what you're looking for.
                       Examples: "cloud costs", "API rate limiting", "team goals"
                limit: Maximum results (default: 5)

            Returns:
                List of relevant learnings, or message if none found.
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
        namespace: str,
        user_id: Optional[str] = None,
    ) -> Callable:
        """Create the async search_learnings tool for the agent."""

        async def search_learnings(
            query: str,
            limit: int = 5,
        ) -> str:
            """Search for relevant insights in the knowledge base.

            ALWAYS call this:
            1. Before answering questions about best practices, recommendations, or how-to
            2. Before saving a new learning (to check for duplicates)

            Args:
                query: Keywords describing what you're looking for.
                       Examples: "cloud costs", "API rate limiting", "team goals"
                limit: Maximum results (default: 5)

            Returns:
                List of relevant learnings, or message if none found.
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
            if filters:
                results = self.knowledge.search(query=query, max_results=limit, filters=filters)
            else:
                results = self.knowledge.search(query=query, max_results=limit)

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
                if filters:
                    results = await self.knowledge.asearch(query=query, max_results=limit, filters=filters)
                else:
                    results = await self.knowledge.asearch(query=query, max_results=limit)
            else:
                if filters:
                    results = self.knowledge.search(query=query, max_results=limit, filters=filters)
                else:
                    results = self.knowledge.search(query=query, max_results=limit)

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

        effective_namespace = namespace or self.config.namespace

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

            # Build metadata for filtering
            # Metadata must be passed separately to insert for filters to work
            filter_metadata: dict[str, Any] = {
                "namespace": effective_namespace,
            }
            if effective_namespace == "user" and user_id:
                filter_metadata["user_id"] = user_id
            if agent_id:
                filter_metadata["agent_id"] = agent_id
            if team_id:
                filter_metadata["team_id"] = team_id
            if tags:
                filter_metadata["tags"] = tags

            self.knowledge.insert(
                name=learning_data["title"],
                text_content=text_content,
                reader=TextReader(),
                skip_if_exists=True,
                metadata=filter_metadata,  # Pass metadata for filtering
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

        effective_namespace = namespace or self.config.namespace

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

            # Build metadata for filtering
            # Metadata must be passed separately to insert for filters to work
            filter_metadata: dict[str, Any] = {
                "namespace": effective_namespace,
            }
            if effective_namespace == "user" and user_id:
                filter_metadata["user_id"] = user_id
            if agent_id:
                filter_metadata["agent_id"] = agent_id
            if team_id:
                filter_metadata["team_id"] = team_id
            if tags:
                filter_metadata["tags"] = tags

            if hasattr(self.knowledge, "ainsert"):
                await self.knowledge.ainsert(
                    name=learning_data["title"],
                    text_content=text_content,
                    reader=TextReader(),
                    skip_if_exists=True,
                    metadata=filter_metadata,  # Pass metadata for filtering
                )
            else:
                self.knowledge.insert(
                    name=learning_data["title"],
                    text_content=text_content,
                    reader=TextReader(),
                    skip_if_exists=True,
                    metadata=filter_metadata,  # Pass metadata for filtering
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
    # Background Extraction (ALWAYS mode)
    # =========================================================================

    def extract_and_save(
        self,
        messages: List[Any],
        user_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
        namespace: Optional[str] = None,
        run_response: Optional[Any] = None,
    ) -> None:
        """Extract learnings from messages (sync)."""
        if not self.model or not self.knowledge:
            return

        try:
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

            if run_response is not None and response.response_usage is not None:
                from agno.metrics import ModelType, accumulate_model_metrics

                accumulate_model_metrics(response, model_copy, ModelType.LEARNING_MODEL, run_response)

            if response.tool_executions:
                self.learning_saved = True
                log_debug("LearnedKnowledgeStore: Extraction saved new learning(s)")

        except Exception as e:
            log_warning(f"LearnedKnowledgeStore.extract_and_save failed: {e}")

    async def aextract_and_save(
        self,
        messages: List[Any],
        user_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
        namespace: Optional[str] = None,
        run_response: Optional[Any] = None,
    ) -> None:
        """Extract learnings from messages (async)."""
        if not self.model or not self.knowledge:
            return

        try:
            conversation_text = self._messages_to_text(messages=messages)

            # Search for existing learnings to avoid duplicates
            existing = await self.asearch(query=conversation_text[:500], limit=5)
            existing_summary = self._summarize_existing(learnings=existing)

            extraction_messages = self._build_extraction_messages(
                conversation_text=conversation_text,
                existing_summary=existing_summary,
            )

            tools = self._aget_extraction_tools(
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

            if run_response is not None and response.response_usage is not None:
                from agno.metrics import ModelType, accumulate_model_metrics

                accumulate_model_metrics(response, model_copy, ModelType.LEARNING_MODEL, run_response)

            if response.tool_executions:
                self.learning_saved = True
                log_debug("LearnedKnowledgeStore: Extraction saved new learning(s)")

        except Exception as e:
            log_warning(f"LearnedKnowledgeStore.aextract_and_save failed: {e}")

    def _build_extraction_messages(
        self,
        conversation_text: str,
        existing_summary: str,
    ) -> List[Any]:
        """Build messages for extraction."""
        from agno.models.message import Message

        system_prompt = dedent("""\
            You are a Learning Extractor. Your job is to identify knowledge worth preserving
            from conversations for future use.

            ## What to Save

            **1. Discovered Insights** - Knowledge that emerged through the conversation:
            - Non-obvious (required reasoning or investigation)
            - Reusable (applies to a category of problems)
            - Actionable (specific enough to apply directly)
            - Durable (won't become outdated quickly)

            **2. Organizational Context** - Explicit directives shared by the user:
            - Explicit save requests: "remember that...", "note that...", "keep in mind..."
            - Team/org goals: "we're trying to...", "our goal is...", "our priority is..."
            - Constraints: "we can't use...", "we need to avoid..."
            - Policies: "our policy is...", "we always...", "we never..."

            ## What NOT to Save

            - Raw facts (use search for retrieval)
            - Individual user preferences (belongs in user memory)
            - Common knowledge (everyone knows this)
            - One-off answers (not generalizable)
            - Summaries without insight
            - Uncertain conclusions

            ## Examples

            Good - Discovered insight:
            > **Title:** Debugging intermittent PostgreSQL connection timeouts
            > **Learning:** Check for connection pool exhaustion before investigating network issues.
            > **Context:** Diagnosing database connectivity issues

            Good - Organizational context:
            > **Title:** Team goal: reduce cloud egress costs
            > **Learning:** Factor egress costs into architecture decisions.
            > **Context:** Infrastructure and vendor decisions

            Bad (don't save):
            - "The error was a typo on line 42" (one-off)
            - "React is popular" (common knowledge)
            - "We discussed options" (summary, no insight)

        """)

        if existing_summary:
            system_prompt += f"""## Already Saved (DO NOT DUPLICATE)

These insights are already in the knowledge base. Do not save variations of these:

{existing_summary}

"""

        system_prompt += dedent("""\
            ## Your Task

            Review the conversation below. Save anything that fits the criteria above:
            - Discovered insights worth preserving
            - Organizational context the user shared (goals, constraints, policies)

            **Important:**
            - Most conversations will NOT produce a learning. That's expected.
            - When in doubt, don't save. Quality over quantity.
            - It's fine to do nothing if there's nothing worth saving.\
        """)

        return [
            Message(role="system", content=system_prompt),
            Message(role="user", content=f"Review this conversation for reusable insights:\n\n{conversation_text}"),
        ]

    def _get_extraction_tools(
        self,
        user_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
        namespace: Optional[str] = None,
    ) -> List[Callable]:
        """Get sync extraction tools."""
        effective_namespace = namespace or self.config.namespace

        def save_learning(
            title: str,
            learning: str,
            context: Optional[str] = None,
            tags: Optional[List[str]] = None,
        ) -> str:
            """Save a reusable insight or organizational context.

            Args:
                title: Concise, searchable title.
                learning: The insight or context - specific and actionable.
                context: When/where this applies.
                tags: Categories for organization.

            Returns:
                Confirmation message.
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

    def _aget_extraction_tools(
        self,
        user_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
        namespace: Optional[str] = None,
    ) -> List[Callable]:
        """Get async extraction tools."""
        effective_namespace = namespace or self.config.namespace

        async def save_learning(
            title: str,
            learning: str,
            context: Optional[str] = None,
            tags: Optional[List[str]] = None,
        ) -> str:
            """Save a reusable insight or organizational context.

            Args:
                title: Concise, searchable title.
                learning: The insight or context - specific and actionable.
                context: When/where this applies.
                tags: Categories for organization.

            Returns:
                Confirmation message.
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

    def print(
        self,
        query: str,
        *,
        user_id: Optional[str] = None,
        namespace: Optional[str] = None,
        limit: int = 10,
        raw: bool = False,
    ) -> None:
        """Print formatted learned knowledge search results.

        Args:
            query: Search query to find relevant learnings.
            user_id: User ID for "user" namespace scoping.
            namespace: Namespace to filter by.
            limit: Maximum number of learnings to display.
            raw: If True, print raw list using pprint instead of formatted panel.

        Example:
            >>> store.print(query="API design")
            ╭───────────── Learned Knowledge ──────────────╮
            │ 1. PostgreSQL JSONB indexing                 │
            │    For frequently queried nested JSONB...    │
            │    Context: When query performance degrades  │
            │    Tags: postgresql, performance             │
            │                                              │
            │ 2. Handling rate limits in async clients     │
            │    Implement exponential backoff with...     │
            │    Context: When building API clients        │
            │    Tags: api, async, rate-limiting           │
            ╰──────────────── query: API ──────────────────╯
        """
        from agno.learn.utils import print_panel

        learnings = self.search(
            query=query,
            user_id=user_id,
            namespace=namespace,
            limit=limit,
        )

        lines = []

        for i, learning in enumerate(learnings, 1):
            if i > 1:
                lines.append("")  # Separator between learnings

            # Title
            title = getattr(learning, "title", None)
            if title:
                lines.append(f"[bold]{i}. {title}[/bold]")
            else:
                lines.append(f"[bold]{i}. (untitled)[/bold]")

            # Learning content
            content = getattr(learning, "learning", None)
            if content:
                # Truncate long content for display
                if len(content) > 200:
                    content = content[:200] + "..."
                lines.append(f"   {content}")

            # Context
            context = getattr(learning, "context", None)
            if context:
                lines.append(f"   [dim]Context: {context}[/dim]")

            # Tags
            tags = getattr(learning, "tags", None)
            if tags:
                tags_str = ", ".join(tags)
                lines.append(f"   [dim]Tags: {tags_str}[/dim]")

            # Namespace (if not global)
            ns = getattr(learning, "namespace", None)
            if ns and ns != "global":
                lines.append(f"   [dim]Namespace: {ns}[/dim]")

        print_panel(
            title="Learned Knowledge",
            subtitle=f"query: {query[:30]}{'...' if len(query) > 30 else ''}",
            lines=lines,
            empty_message="No learnings found",
            raw_data=learnings,
            raw=raw,
        )
