"""
Custom Retriever
=============================

Use knowledge_retriever to provide a custom retrieval function.

Instead of using a Knowledge instance, you can supply your own callable
that returns documents. The agent will use it as its search_knowledge_base tool.
"""

from typing import List, Optional

from agno.agent import Agent
from agno.models.openai import OpenAIResponses

# ---------------------------------------------------------------------------
# Custom Retriever Function
# ---------------------------------------------------------------------------
# A simple in-memory retriever for demonstration.
# In production, this could call an external API, database, or search engine.
DOCUMENTS = [
    {
        "title": "Python Basics",
        "content": "Python is a high-level programming language known for its readability.",
    },
    {
        "title": "TypeScript Intro",
        "content": "TypeScript adds static typing to JavaScript.",
    },
    {
        "title": "Rust Overview",
        "content": "Rust is a systems language focused on safety and performance.",
    },
]


def my_retriever(
    query: str, num_documents: Optional[int] = None, **kwargs
) -> Optional[List[dict]]:
    """Search documents by simple keyword matching."""
    query_lower = query.lower()
    results = [
        doc
        for doc in DOCUMENTS
        if query_lower in doc["content"].lower() or query_lower in doc["title"].lower()
    ]
    if num_documents:
        results = results[:num_documents]
    return results if results else None


# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
agent = Agent(
    model=OpenAIResponses(id="gpt-5.2"),
    # Use a custom retriever instead of a Knowledge instance
    knowledge_retriever=my_retriever,
    # search_knowledge is True by default when knowledge_retriever is set
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    agent.print_response(
        "Tell me about Python.",
        stream=True,
    )
