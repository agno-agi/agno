"""
Knowledge Store
===============
Storage backend for Learned Knowledge learning type.

Uses the Knowledge base (vector store) for semantic search.
"""

import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Type

from pydantic import BaseModel

from agno.learn.config import KnowledgeConfig
from agno.learn.schemas import DefaultLearning
from agno.utils.log import log_debug, log_error, log_warning


class KnowledgeStore:
    """Storage backend for Learned Knowledge learning type.

    Uses a Knowledge base with vector embeddings for semantic search.
    Learnings are stored and retrieved based on relevance to queries.

    Args:
        knowledge: Knowledge instance with vector DB configured.
        config: KnowledgeConfig with settings.
    """

    def __init__(
        self,
        knowledge,  # agno.knowledge.Knowledge
        config: Optional[KnowledgeConfig] = None,
    ):
        self.knowledge = knowledge
        self.config = config or KnowledgeConfig()
        self.schema: Type[BaseModel] = config.schema if config and config.schema else DefaultLearning

    def search(
        self,
        query: str,
        limit: int = 5,
    ) -> List[BaseModel]:
        """Search for relevant learnings based on query.

        Uses semantic search to find learnings most relevant to the query.

        Args:
            query: The search query.
            limit: Maximum number of results to return.

        Returns:
            List of learning objects matching the query.
        """
        if not self.knowledge:
            log_warning("KnowledgeStore: No knowledge base configured")
            return []

        try:
            # Search the knowledge base
            results = self.knowledge.search(query=query, num_documents=limit)

            learnings = []
            for result in results or []:
                learning = self._parse_result(result)
                if learning:
                    learnings.append(learning)

            log_debug(f"Found {len(learnings)} relevant learnings for query: {query[:50]}...")
            return learnings

        except Exception as e:
            log_error(f"Error searching knowledge base: {e}")
            return []

    async def asearch(
        self,
        query: str,
        limit: int = 5,
    ) -> List[BaseModel]:
        """Async version of search."""
        if not self.knowledge:
            log_warning("KnowledgeStore: No knowledge base configured")
            return []

        try:
            # Check if knowledge base has async search
            if hasattr(self.knowledge, 'asearch'):
                results = await self.knowledge.asearch(query=query, num_documents=limit)
            else:
                results = self.knowledge.search(query=query, num_documents=limit)

            learnings = []
            for result in results or []:
                learning = self._parse_result(result)
                if learning:
                    learnings.append(learning)

            log_debug(f"Found {len(learnings)} relevant learnings for query: {query[:50]}...")
            return learnings

        except Exception as e:
            log_error(f"Error searching knowledge base: {e}")
            return []

    def save(
        self,
        title: str,
        learning: str,
        context: Optional[str] = None,
        tags: Optional[List[str]] = None,
    ) -> bool:
        """Save a learning to the knowledge base.

        Args:
            title: Short descriptive title.
            learning: The actual insight.
            context: When/why this applies.
            tags: Tags for categorization.

        Returns:
            True if saved successfully, False otherwise.
        """
        if not self.knowledge:
            log_warning("KnowledgeStore: No knowledge base configured")
            return False

        try:
            # Build the learning object
            learning_data = {
                "title": title.strip(),
                "learning": learning.strip(),
                "context": context.strip() if context else None,
                "tags": tags or [],
                "created_at": datetime.now(timezone.utc).isoformat(),
            }

            # Validate against schema
            learning_obj = self.schema.model_validate(learning_data)

            # Convert to text for storage
            text_content = self._to_text_content(learning_obj)

            # Add to knowledge base
            self.knowledge.add_content(
                name=title,
                text_content=text_content,
                skip_if_exists=True,
            )

            log_debug(f"Saved learning: {title}")
            return True

        except Exception as e:
            log_error(f"Error saving learning: {e}")
            return False

    async def asave(
        self,
        title: str,
        learning: str,
        context: Optional[str] = None,
        tags: Optional[List[str]] = None,
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
                "created_at": datetime.now(timezone.utc).isoformat(),
            }

            learning_obj = self.schema.model_validate(learning_data)
            text_content = self._to_text_content(learning_obj)

            # Check for async method
            if hasattr(self.knowledge, 'aadd_content'):
                await self.knowledge.aadd_content(
                    name=title,
                    text_content=text_content,
                    skip_if_exists=True,
                )
            else:
                self.knowledge.add_content(
                    name=title,
                    text_content=text_content,
                    skip_if_exists=True,
                )

            log_debug(f"Saved learning: {title}")
            return True

        except Exception as e:
            log_error(f"Error saving learning: {e}")
            return False

    def _parse_result(self, result: Any) -> Optional[BaseModel]:
        """Parse a search result into a learning object."""
        try:
            # Handle different result formats
            content = None

            if isinstance(result, dict):
                content = result.get('content') or result.get('text') or result
            elif hasattr(result, 'content'):
                content = result.content
            elif hasattr(result, 'text'):
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
                    # Not JSON, treat as plain text learning
                    return self.schema(
                        title="Learning",
                        learning=content,
                    )

            # Validate against schema
            if isinstance(content, dict):
                return self.schema.model_validate(content)

            return None

        except Exception as e:
            log_warning(f"Failed to parse search result: {e}")
            return None

    def _to_text_content(self, learning: BaseModel) -> str:
        """Convert a learning object to text content for storage."""

        # Store as JSON for structured retrieval
        learning_dict = learning.model_dump() if hasattr(learning, 'model_dump') else learning.dict()
        return json.dumps(learning_dict, ensure_ascii=False)

    def get_all(self, limit: int = 100) -> List[BaseModel]:
        """Get all learnings from the knowledge base.

        Args:
            limit: Maximum number of learnings to return.

        Returns:
            List of all learning objects.
        """
        if not self.knowledge:
            return []

        try:
            # Use a broad search to get all
            results = self.knowledge.search(query="", num_documents=limit)

            learnings = []
            for result in results or []:
                learning = self._parse_result(result)
                if learning:
                    learnings.append(learning)

            return learnings

        except Exception as e:
            log_error(f"Error getting all learnings: {e}")
            return []

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
            # Knowledge base may have different delete methods
            if hasattr(self.knowledge, 'delete_content'):
                self.knowledge.delete_content(name=title)
                log_debug(f"Deleted learning: {title}")
                return True
            else:
                log_warning("Knowledge base does not support deletion")
                return False

        except Exception as e:
            log_error(f"Error deleting learning: {e}")
            return False
