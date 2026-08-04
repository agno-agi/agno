"""
KnowledgeTools with Custom Retriever
====================================

Combine the Think -> Search -> Analyze workflow from KnowledgeTools
with a custom knowledge_retriever (same contract as Agent.knowledge_retriever).

This lets you keep structured knowledge reasoning while searching multiple
sources, calling an external service, or applying custom ranking.
"""

from typing import List, Optional

from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.tools.knowledge import KnowledgeTools

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


def custom_retriever(
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


knowledge_tools = KnowledgeTools(
    knowledge_retriever=custom_retriever,
    enable_think=True,
    enable_search=True,
    enable_analyze=True,
)

agent = Agent(
    model=OpenAIResponses(id="gpt-5.5"),
    tools=[knowledge_tools],
    markdown=True,
)

if __name__ == "__main__":
    agent.print_response(
        "Tell me about Python.",
        stream=True,
    )
