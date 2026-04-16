"""
Knowledge Protocol: Custom Knowledge Sources
==============================================
KnowledgeProtocol is an interface for building custom knowledge sources
that don't use the standard Knowledge class.

Implement this when you need:
- Knowledge from a non-standard source (file system, API, database)
- Custom search logic that doesn't fit the vector DB model
- Integration with existing retrieval systems

The protocol requires implementing build_context(), get_tools(), and aget_tools().
Optionally implement retrieve()/aretrieve() for the search_knowledge feature.
"""

from typing import Callable, List

from agno.agent import Agent
from agno.knowledge.document import Document
from agno.knowledge.protocol import KnowledgeProtocol
from agno.models.openai import OpenAIResponses

# ---------------------------------------------------------------------------
# Custom Knowledge Implementation
# ---------------------------------------------------------------------------


class InMemoryKnowledge(KnowledgeProtocol):
    """A simple in-memory knowledge source for demonstration.

    In production, this could wrap a SQL database, REST API,
    or any custom data source.
    """

    def __init__(self):
        self.documents: list[Document] = []

    def add(self, name: str, content: str) -> None:
        self.documents.append(Document(name=name, content=content))

    def _search(self, query: str, limit: int = 5) -> List[Document]:
        """Simple substring matching (replace with your search logic)."""
        results = []
        for doc in self.documents:
            if doc.content and query.lower() in doc.content.lower():
                results.append(doc)
        return results[:limit] or self.documents[:limit]

    # --- Required protocol methods ---

    def build_context(self, **kwargs) -> str:
        return "Use the search tool to find information in the knowledge base."

    def get_tools(self, **kwargs) -> List[Callable]:
        return []

    async def aget_tools(self, **kwargs) -> List[Callable]:
        return []

    # --- Optional: enables search_knowledge feature ---

    def retrieve(self, query: str, **kwargs) -> List[Document]:
        max_results = kwargs.get("max_results", 5)
        return self._search(query, limit=max_results)

    async def aretrieve(self, query: str, **kwargs) -> List[Document]:
        return self.retrieve(query, **kwargs)


# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------

custom_knowledge = InMemoryKnowledge()
custom_knowledge.add("Python", "Python is a high-level programming language.")
custom_knowledge.add("TypeScript", "TypeScript adds static types to JavaScript.")
custom_knowledge.add(
    "Rust", "Rust is a systems language focused on safety and performance."
)

agent = Agent(
    model=OpenAIResponses(id="gpt-5.2"),
    knowledge=custom_knowledge,
    search_knowledge=True,
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run Demo
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("\n" + "=" * 60)
    print("Custom KnowledgeProtocol implementation")
    print("=" * 60 + "\n")

    agent.print_response("Tell me about Python", stream=True)
