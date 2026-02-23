"""
Knowledge Protocol: Custom Knowledge Sources
==============================================
KnowledgeProtocol is an interface for building custom knowledge sources
that don't use the standard Knowledge class.

Implement this when you need:
- Knowledge from a non-standard source (file system, API, database)
- Custom search logic that doesn't fit the vector DB model
- Integration with existing retrieval systems

The protocol requires implementing search() and asearch() methods.
"""

from typing import List, Optional

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

    def search(
        self,
        query: str,
        limit: int = 5,
        filters: Optional[dict] = None,
    ) -> List[Document]:
        # Simple substring matching (replace with your search logic)
        results = []
        for doc in self.documents:
            if doc.content and query.lower() in doc.content.lower():
                results.append(doc)
        return results[:limit] or self.documents[:limit]

    async def asearch(
        self,
        query: str,
        limit: int = 5,
        filters: Optional[dict] = None,
    ) -> List[Document]:
        return self.search(query, limit, filters)


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
