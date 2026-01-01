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
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, List, Optional, Union

from agno.learn.config import KnowledgeConfig, LearningMode
from agno.learn.schemas import BaseLearning
from agno.learn.stores.base import BaseLearningStore, to_dict_safe
from agno.models.message import Message
from agno.tools.function import Function
from agno.utils.log import log_debug, log_warning


@dataclass
class KnowledgeStore(BaseLearningStore):
    """Storage backend for Learned Knowledge learning type.

    Uses a Knowledge base with vector embeddings for semantic search.
    Learnings are stored and retrieved based on relevance to queries.

    Key differences from other stores:
    - No user_id/session_id scoping - knowledge is shared
    - Semantic search instead of direct lookup
    - Agent tool for saving learnings in AGENTIC mode

    Args:
        config: KnowledgeConfig with all settings including knowledge base.
    """

    config: KnowledgeConfig = field(default_factory=KnowledgeConfig)

    # State tracking (internal)
    learning_saved: bool = False

    def __post_init__(self):
        self.schema = self.config.schema or BaseLearning

    # --- Properties for cleaner access ---

    @property
    def knowledge(self):
        """The knowledge base (vector store)."""
        return self.config.knowledge

    @property
    def model(self):
        return self.config.model

    # --- Agent Tool ---

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

    # --- Search Operations ---

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
                learning = self._parse_result(result)
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
                learning = self._parse_result(result)
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

    # --- Save Operations ---

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
            text_content = self._to_text_content(learning_obj)

            # Add to knowledge base
            self.knowledge.load_text(
                text=text_content,
                id=f"learning_{title.lower().replace(' ', '_')[:50]}",
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
            text_content = self._to_text_content(learning_obj)

            if hasattr(self.knowledge, "aload_text"):
                await self.knowledge.aload_text(
                    text=text_content,
                    id=f"learning_{title.lower().replace(' ', '_')[:50]}",
                )
            else:
                self.knowledge.load_text(
                    text=text_content,
                    id=f"learning_{title.lower().replace(' ', '_')[:50]}",
                )

            log_debug(f"Saved learning: {title}")
            return True

        except Exception as e:
            log_warning(f"Error saving learning: {e}")
            return False

    # --- Delete Operations ---

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
            learning_id = f"learning_{title.lower().replace(' ', '_')[:50]}"
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
            learning_id = f"learning_{title.lower().replace(' ', '_')[:50]}"
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

    # --- Utility Methods ---

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

        if not learnings:
            return ""

        parts = ["Relevant knowledge from past learnings:"]
        for learning in learnings:
            parts.append(self._format_learning(learning))

        return "\n\n".join(parts)

    async def aget_relevant_context(
        self,
        query: str,
        limit: int = 3,
    ) -> str:
        """Async version of get_relevant_context."""
        learnings = await self.asearch(query=query, limit=limit)

        if not learnings:
            return ""

        parts = ["Relevant knowledge from past learnings:"]
        for learning in learnings:
            parts.append(self._format_learning(learning))

        return "\n\n".join(parts)

    # --- Private Helpers ---

    def _parse_result(self, result: Any) -> Optional[Any]:
        """Parse a search result into a learning object."""
        try:
            import json

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
                return self.schema(**content)

            return None

        except Exception as e:
            log_warning(f"Failed to parse search result: {e}")
            return None

    def _to_text_content(self, learning: Any) -> str:
        """Convert a learning object to text content for storage."""
        import json

        learning_dict = to_dict_safe(learning)
        return json.dumps(learning_dict, ensure_ascii=False)

    def _format_learning(self, learning: Any) -> str:
        """Format a learning for prompt injection."""
        parts = []

        if hasattr(learning, "title") and learning.title:
            parts.append(f"**{learning.title}**")

        if hasattr(learning, "learning") and learning.learning:
            parts.append(learning.learning)

        if hasattr(learning, "context") and learning.context:
            parts.append(f"_Context: {learning.context}_")

        return "\n".join(parts)

    def _determine_tools_for_model(self, tools: List[Callable]) -> List[Union[Function, dict]]:
        """Convert callables to Functions for model."""
        _function_names: List[str] = []
        _functions: List[Union[Function, dict]] = []

        for tool in tools:
            try:
                function_name = tool.__name__
                if function_name in _function_names:
                    continue
                _function_names.append(function_name)
                func = Function.from_callable(tool, strict=True)
                func.strict = True
                _functions.append(func)
                log_debug(f"Added function {func.name}")
            except Exception as e:
                log_warning(f"Could not add function {tool}: {e}")

        return _functions
