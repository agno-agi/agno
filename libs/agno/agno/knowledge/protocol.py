"""
Knowledge Base Protocol
=======================
Defines the interface that knowledge implementations must implement.

This protocol enables:
- Custom knowledge bases to be used with agents
- Consistent API across different knowledge implementations
- Type safety with Protocol typing
"""

from typing import List, Protocol, runtime_checkable

from agno.knowledge.document import Document


@runtime_checkable
class KnowledgeBase(Protocol):
    """Protocol for knowledge base implementations.

    Enables custom knowledge bases to be used with agents.
    Any class implementing search() and asearch() methods
    with the correct signatures will satisfy this protocol.

    Example:
        ```python
        from agno.knowledge.protocol import KnowledgeBase
        from agno.knowledge.document import Document

        class MyKnowledge:
            def search(self, query: str, **kwargs) -> List[Document]:
                results = my_custom_search(query)
                return [Document(content=r) for r in results]

            async def asearch(self, query: str, **kwargs) -> List[Document]:
                results = await my_async_search(query)
                return [Document(content=r) for r in results]

        # MyKnowledge satisfies KnowledgeBase protocol
        agent = Agent(knowledge=MyKnowledge())
        ```
    """

    def search(self, query: str, **kwargs) -> List[Document]:
        """Search for relevant documents.

        Args:
            query: The search query string.
            **kwargs: Additional search parameters (e.g., max_results, filters).

        Returns:
            List of Document objects matching the query.
        """
        ...

    async def asearch(self, query: str, **kwargs) -> List[Document]:
        """Async search for relevant documents.

        Args:
            query: The search query string.
            **kwargs: Additional search parameters (e.g., max_results, filters).

        Returns:
            List of Document objects matching the query.
        """
        ...
