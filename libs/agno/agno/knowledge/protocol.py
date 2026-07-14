"""
Knowledge Protocol
==================
Defines the minimal interface that knowledge implementations must implement.

This protocol enables:
- Custom knowledge bases to be used with agents
- Each implementation defines its own tools and context
- Flexible tool naming (not forced to use 'search')
- Type safety with Protocol typing
"""

from typing import Callable, List, Protocol, runtime_checkable

from agno.knowledge.document import Document


@runtime_checkable
class KnowledgeProtocol(Protocol):
    """Minimal protocol for knowledge implementations.

    Enables custom knowledge bases to be used with agents.
    Each implementation defines what tools it exposes and what
    context/instructions it provides to the agent.

    Required methods:
    - build_context(): Return instructions for the agent's system prompt
    - get_tools(): Return tools to expose to the agent
    - aget_tools(): Async version of get_tools

    Optional methods:
    - retrieve(): Default retrieval for context injection (add_knowledge_to_context)
    - aretrieve(): Async version of retrieve

    Example:
        ```python
        from agno.knowledge.protocol import KnowledgeProtocol
        from agno.knowledge.document import Document

        class MyKnowledge:
            def build_context(self, **kwargs) -> str:
                return "Use search_docs to find information."

            def get_tools(self, **kwargs) -> List[Callable]:
                return [self.search_docs]

            async def aget_tools(self, **kwargs) -> List[Callable]:
                return [self.search_docs]

            def search_docs(self, query: str) -> str:
                # Your search implementation
                return "Results for: " + query

            # Optional: for add_knowledge_to_context feature
            def retrieve(self, query: str, **kwargs) -> List[Document]:
                results = self._internal_search(query)
                return [Document(content=r) for r in results]

        # MyKnowledge satisfies KnowledgeProtocol
        agent = Agent(knowledge=MyKnowledge())
        ```
    """

    def build_context(self, **kwargs) -> str:
        """Build context string for the agent's system prompt.

        Returns instructions about how to use this knowledge,
        what tools are available, and any usage guidelines.

        Args:
            **kwargs: Context including enable_agentic_filters, etc.

        Returns:
            Formatted context string to inject into system prompt.
        """
        ...

    def get_tools(self, **kwargs) -> List[Callable]:
        """Get tools to expose to the agent.

        Returns callable tools that the agent can use to interact
        with this knowledge. Each implementation decides what
        tools make sense (e.g., search, grep, list_files, query_db).

        Args:
            **kwargs: Context including run_response, run_context,
                     async_mode, enable_agentic_filters, agent, etc.

        Returns:
            List of callable tools.
        """
        ...

    async def aget_tools(self, **kwargs) -> List[Callable]:
        """Async version of get_tools.

        Args:
            **kwargs: Same as get_tools.

        Returns:
            List of callable tools.
        """
        ...

    # Optional methods - used by add_knowledge_to_context feature
    # Implementations that don't support context injection can omit these

    def retrieve(self, query: str, **kwargs) -> List[Document]:
        """Retrieve documents for context injection.

        Used by the add_knowledge_to_context feature to pre-fetch
        relevant documents into the user message. This is optional;
        if not implemented, add_knowledge_to_context will be skipped.

        Args:
            query: The query string.
            **kwargs: Additional parameters (max_results, filters, etc.)

        Returns:
            List of Document objects.
        """
        ...

    async def aretrieve(self, query: str, **kwargs) -> List[Document]:
        """Async version of retrieve.

        Args:
            query: The query string.
            **kwargs: Additional parameters.

        Returns:
            List of Document objects.
        """
        ...
