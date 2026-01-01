"""
Knowledge Store
===============
Storage backend for Learned Knowledge learning type.

Unlike UserProfileStore (per-user) and SessionContextStore (per-session),
KnowledgeStore uses semantic search to find relevant learnings across
all stored knowledge.

Think of it as:
- UserProfile = what you know about a person
- SessionContext = what happened in this meeting
- Knowledge = reusable insights that apply anywhere

Key Features:
- Semantic search for relevant learnings
- Agent tool for saving new learnings (AGENTIC mode)
- PROPOSE mode for user confirmation before saving
- Shareable across users and agents
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from os import getenv
from textwrap import dedent
from typing import Any, Callable, List, Optional

from agno.learn.config import KnowledgeConfig, LearningMode
from agno.learn.schemas import BaseLearning
from agno.learn.stores.base import LearningStore, to_dict_safe
from agno.utils.log import (
    log_debug,
    log_warning,
    set_log_level_to_debug,
    set_log_level_to_info,
)


@dataclass
class KnowledgeStore(LearningStore):
    """Storage backend for Learned Knowledge learning type.

    Uses a Knowledge base with vector embeddings for semantic search.
    Learnings are stored and retrieved based on relevance to queries.

    Key differences from other stores:
    - No user_id/session_id scoping - knowledge is shared
    - Semantic search instead of direct lookup
    - Agent tool for saving learnings in AGENTIC mode

    Usage:
        >>> store = KnowledgeStore(config=KnowledgeConfig(knowledge=kb))
        >>>
        >>> # Save a learning
        >>> store.save(
        ...     title="Python async best practices",
        ...     learning="Always use asyncio.gather for concurrent tasks",
        ...     context="When optimizing I/O-bound operations",
        ...     tags=["python", "async", "performance"]
        ... )
        >>>
        >>> # Search for relevant learnings
        >>> results = store.search("How do I optimize my async code?")
        >>>
        >>> # Agent tool
        >>> tool = store.get_agent_tool()
        >>> tool("Python decorators", "Use functools.wraps to preserve metadata")

    Args:
        config: KnowledgeConfig with all settings including knowledge base.
        debug_mode: Enable debug logging.
    """

    config: KnowledgeConfig = field(default_factory=KnowledgeConfig)
    debug_mode: bool = False

    # State tracking (internal)
    learning_saved: bool = field(default=False, init=False)
    _schema: Any = field(default=None, init=False)

    def __post_init__(self):
        self._schema = self.config.schema or BaseLearning

    # =========================================================================
    # LearningStore Protocol Implementation
    # =========================================================================

    @property
    def learning_type(self) -> str:
        """String identifier for this learning type."""
        return "learned_knowledge"

    @property
    def schema(self) -> Any:
        """The schema class used for learnings."""
        return self._schema

    def recall(
        self,
        message: Optional[str] = None,
        query: Optional[str] = None,
        limit: int = 5,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
        **kwargs,
    ) -> Optional[List[Any]]:
        """Retrieve relevant learnings via semantic search.

        Args:
            message: Current user message to find relevant learnings for.
            query: Alternative query string (if message not provided).
            limit: Maximum number of results.
            agent_id: Optional filter by agent.
            team_id: Optional filter by team.
            **kwargs: Additional context (ignored).

        Returns:
            List of relevant learnings, or None if no query.
        """
        search_query = message or query
        if not search_query:
            return None

        results = self.search(
            query=search_query,
            limit=limit,
            agent_id=agent_id,
            team_id=team_id,
        )

        return results if results else None

    async def arecall(
        self,
        message: Optional[str] = None,
        query: Optional[str] = None,
        limit: int = 5,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
        **kwargs,
    ) -> Optional[List[Any]]:
        """Async version of recall."""
        search_query = message or query
        if not search_query:
            return None

        results = await self.asearch(
            query=search_query,
            limit=limit,
            agent_id=agent_id,
            team_id=team_id,
        )

        return results if results else None

    def process(
        self,
        messages: List[Any],
        **kwargs,
    ) -> None:
        """Knowledge extraction is typically AGENTIC or PROPOSE, not BACKGROUND.

        This method is a no-op for KnowledgeStore. Learnings are saved
        via the agent tool or explicit save() calls.
        """
        # Knowledge is typically saved via agent tool, not background extraction
        pass

    async def aprocess(
        self,
        messages: List[Any],
        **kwargs,
    ) -> None:
        """Async version of process (no-op for knowledge)."""
        pass

    def format_for_prompt(self, data: Any) -> str:
        """Format learnings for system prompt injection.

        Args:
            data: List of learning objects from recall().

        Returns:
            Formatted XML string.
        """
        if not data:
            return ""

        # Handle single learning or list
        learnings = data if isinstance(data, list) else [data]

        if not learnings:
            return ""

        parts = []
        for i, learning in enumerate(learnings, 1):
            formatted = self._format_single_learning(learning=learning)
            if formatted:
                parts.append(f"{i}. {formatted}")

        if not parts:
            return ""

        learnings_text = "\n".join(parts)

        return (
            dedent(f"""\
            <relevant_learnings>
            Insights from past interactions:
            """)
            + learnings_text
            + dedent("""
            Apply where appropriate.
            </relevant_learnings>""")
        )

    def get_tools(
        self,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
        **kwargs,
    ) -> List[Callable]:
        """Get tools to expose to agent.

        Args:
            agent_id: Optional agent context.
            team_id: Optional team context.
            **kwargs: Additional context (ignored).

        Returns:
            List containing save_learning tool if enabled.
        """
        if not self.config.enable_tool:
            return []
        return [self.get_agent_tool(agent_id=agent_id, team_id=team_id)]

    async def aget_tools(
        self,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
        **kwargs,
    ) -> List[Callable]:
        """Async version of get_tools."""
        if not self.config.enable_tool:
            return []
        return [await self.aget_agent_tool(agent_id=agent_id, team_id=team_id)]

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
    # Agent Tool
    # =========================================================================

    def get_agent_tool(
        self,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
    ) -> Callable:
        """Get the tool to expose to the agent.

        Returns a callable that the agent can use to save learnings.
        Used in AGENTIC mode.
        """

        def save_learning(
            title: str,
            learning: str,
            context: Optional[str] = None,
            tags: Optional[List[str]] = None,
        ) -> str:
            """Save a reusable insight or learning.

            Use this when you discover something that would be useful to
            remember for future conversations - patterns, best practices,
            user preferences that apply broadly, or insights from problem-solving.

            Args:
                title: Short descriptive title (e.g., "Python async best practices")
                learning: The actual insight or knowledge to save.
                context: When/where this applies (optional).
                tags: Categories for this learning (optional).

            Returns:
                Confirmation message.
            """
            success = self.save(
                title=title,
                learning=learning,
                context=context,
                tags=tags,
                agent_id=agent_id,
                team_id=team_id,
            )
            if success:
                self.learning_saved = True
                return f"Learning saved: {title}"
            return "Failed to save learning"

        return save_learning

    async def aget_agent_tool(
        self,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
    ) -> Callable:
        """Get the async tool to expose to the agent."""

        async def save_learning(
            title: str,
            learning: str,
            context: Optional[str] = None,
            tags: Optional[List[str]] = None,
        ) -> str:
            """Save a reusable insight or learning.

            Use this when you discover something that would be useful to
            remember for future conversations - patterns, best practices,
            user preferences that apply broadly, or insights from problem-solving.

            Args:
                title: Short descriptive title (e.g., "Python async best practices")
                learning: The actual insight or knowledge to save.
                context: When/where this applies (optional).
                tags: Categories for this learning (optional).

            Returns:
                Confirmation message.
            """
            success = await self.asave(
                title=title,
                learning=learning,
                context=context,
                tags=tags,
                agent_id=agent_id,
                team_id=team_id,
            )
            if success:
                self.learning_saved = True
                return f"Learning saved: {title}"
            return "Failed to save learning"

        return save_learning

    # =========================================================================
    # Search Operations
    # =========================================================================

    def search(
        self,
        query: str,
        limit: int = 5,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
    ) -> List[Any]:
        """Search for relevant learnings based on query.

        Uses semantic search to find learnings most relevant to the query.

        Args:
            query: The search query.
            limit: Maximum number of results to return.
            agent_id: Optional filter by agent.
            team_id: Optional filter by team.

        Returns:
            List of learning objects matching the query.
        """
        if not self.knowledge:
            log_warning("KnowledgeStore: No knowledge base configured")
            return []

        try:
            results = self.knowledge.search(query=query, num_documents=limit)

            learnings = []
            for result in results or []:
                learning = self._parse_result(result=result)
                if learning:
                    # Filter by agent/team if specified
                    if agent_id and hasattr(learning, "agent_id") and learning.agent_id != agent_id:
                        continue
                    if team_id and hasattr(learning, "team_id") and learning.team_id != team_id:
                        continue
                    learnings.append(learning)

            log_debug(f"Found {len(learnings)} learnings for query: {query[:50]}...")
            return learnings

        except Exception as e:
            log_warning(f"Error searching knowledge base: {e}")
            return []

    async def asearch(
        self,
        query: str,
        limit: int = 5,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
    ) -> List[Any]:
        """Async version of search."""
        if not self.knowledge:
            log_warning("KnowledgeStore: No knowledge base configured")
            return []

        try:
            if hasattr(self.knowledge, "asearch"):
                results = await self.knowledge.asearch(query=query, num_documents=limit)
            else:
                results = self.knowledge.search(query=query, num_documents=limit)

            learnings = []
            for result in results or []:
                learning = self._parse_result(result=result)
                if learning:
                    if agent_id and hasattr(learning, "agent_id") and learning.agent_id != agent_id:
                        continue
                    if team_id and hasattr(learning, "team_id") and learning.team_id != team_id:
                        continue
                    learnings.append(learning)

            log_debug(f"Found {len(learnings)} learnings for query: {query[:50]}...")
            return learnings

        except Exception as e:
            log_warning(f"Error searching knowledge base: {e}")
            return []

    # =========================================================================
    # Save Operations
    # =========================================================================

    def save(
        self,
        title: str,
        learning: str,
        context: Optional[str] = None,
        tags: Optional[List[str]] = None,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
    ) -> bool:
        """Save a learning to the knowledge base.

        Args:
            title: Short descriptive title.
            learning: The actual insight.
            context: When/why this applies.
            tags: Tags for categorization.
            agent_id: Optional agent context.
            team_id: Optional team context.

        Returns:
            True if saved successfully, False otherwise.
        """
        if not self.knowledge:
            log_warning("KnowledgeStore: No knowledge base configured")
            return False

        try:
            learning_data = {
                "title": title.strip(),
                "learning": learning.strip(),
                "context": context.strip() if context else None,
                "tags": tags or [],
                "agent_id": agent_id,
                "team_id": team_id,
                "created_at": datetime.now(timezone.utc).isoformat(),
            }

            # Create schema instance
            learning_obj = self.schema(**learning_data)

            # Convert to text for vector storage
            text_content = self._to_text_content(learning=learning_obj)

            # Build a unique ID
            learning_id = self._build_learning_id(title=title)

            # Add to knowledge base
            self.knowledge.load_text(
                text=text_content,
                id=learning_id,
            )

            log_debug(f"Saved learning: {title}")
            return True

        except Exception as e:
            log_warning(f"Error saving learning: {e}")
            return False

    async def asave(
        self,
        title: str,
        learning: str,
        context: Optional[str] = None,
        tags: Optional[List[str]] = None,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
    ) -> bool:
        """Async version of save."""
        if not self.knowledge:
            log_warning("KnowledgeStore: No knowledge base configured")
            return False

        try:
            learning_data = {
                "title": title.strip(),
                "learning": learning.strip(),
                "context": context.strip() if context else None,
                "tags": tags or [],
                "agent_id": agent_id,
                "team_id": team_id,
                "created_at": datetime.now(timezone.utc).isoformat(),
            }

            learning_obj = self.schema(**learning_data)
            text_content = self._to_text_content(learning=learning_obj)
            learning_id = self._build_learning_id(title=title)

            if hasattr(self.knowledge, "aload_text"):
                await self.knowledge.aload_text(
                    text=text_content,
                    id=learning_id,
                )
            else:
                self.knowledge.load_text(
                    text=text_content,
                    id=learning_id,
                )

            log_debug(f"Saved learning: {title}")
            return True

        except Exception as e:
            log_warning(f"Error saving learning: {e}")
            return False

    # =========================================================================
    # Delete Operations
    # =========================================================================

    def delete(self, title: str) -> bool:
        """Delete a learning by title.

        Args:
            title: The title of the learning to delete.

        Returns:
            True if deleted successfully, False otherwise.
        """
        if not self.knowledge:
            return False

        try:
            learning_id = self._build_learning_id(title=title)
            if hasattr(self.knowledge, "delete"):
                self.knowledge.delete(id=learning_id)
                log_debug(f"Deleted learning: {title}")
                return True
            else:
                log_warning("Knowledge base does not support deletion")
                return False

        except Exception as e:
            log_warning(f"Error deleting learning: {e}")
            return False

    async def adelete(self, title: str) -> bool:
        """Async version of delete."""
        if not self.knowledge:
            return False

        try:
            learning_id = self._build_learning_id(title=title)
            if hasattr(self.knowledge, "adelete"):
                await self.knowledge.adelete(id=learning_id)
                log_debug(f"Deleted learning: {title}")
                return True
            elif hasattr(self.knowledge, "delete"):
                self.knowledge.delete(id=learning_id)
                log_debug(f"Deleted learning: {title}")
                return True
            else:
                log_warning("Knowledge base does not support deletion")
                return False

        except Exception as e:
            log_warning(f"Error deleting learning: {e}")
            return False

    # =========================================================================
    # Utility Methods
    # =========================================================================

    def get_relevant_context(
        self,
        query: str,
        limit: int = 3,
    ) -> str:
        """Get formatted learnings for injection into prompts.

        Args:
            query: The query to find relevant learnings for.
            limit: Maximum number of learnings to include.

        Returns:
            Formatted string suitable for system prompts.
        """
        learnings = self.search(query=query, limit=limit)
        return self.format_for_prompt(data=learnings)

    async def aget_relevant_context(
        self,
        query: str,
        limit: int = 3,
    ) -> str:
        """Async version of get_relevant_context."""
        learnings = await self.asearch(query=query, limit=limit)
        return self.format_for_prompt(data=learnings)

    # =========================================================================
    # Private Helpers
    # =========================================================================

    def _build_learning_id(self, title: str) -> str:
        """Build a unique learning ID from title."""
        return f"learning_{title.lower().replace(' ', '_')[:50]}"

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

            # Try to parse as JSON
            if isinstance(content, str):
                try:
                    content = json.loads(content)
                except json.JSONDecodeError:
                    # Plain text - create minimal learning
                    return self.schema(title="Learning", learning=content)

            if isinstance(content, dict):
                # Filter to valid fields for schema
                from dataclasses import fields

                field_names = {f.name for f in fields(self.schema)}
                filtered = {k: v for k, v in content.items() if k in field_names}
                return self.schema(**filtered)

            return None

        except Exception as e:
            log_warning(f"Failed to parse search result: {e}")
            return None

    def _to_text_content(self, learning: Any) -> str:
        """Convert a learning object to text content for storage."""
        import json

        learning_dict = to_dict_safe(learning)
        return json.dumps(learning_dict, ensure_ascii=False)

    def _format_single_learning(self, learning: Any) -> str:
        """Format a single learning for prompt injection."""
        parts = []

        if hasattr(learning, "title") and learning.title:
            parts.append(f"**{learning.title}**")

        if hasattr(learning, "learning") and learning.learning:
            parts.append(learning.learning)

        if hasattr(learning, "context") and learning.context:
            parts.append(f"_Context: {learning.context}_")

        return "\n".join(parts)
