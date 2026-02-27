"""
Custom Retriever: Bypass the Knowledge Class
==============================================
Sometimes you need full control over retrieval logic. Instead of using
the Knowledge class, you can provide a custom retriever function.

The function receives (query, num_documents, **kwargs) and returns
a list of dicts. This is useful for:
- Non-vector retrieval (SQL queries, API calls, file lookups)
- Custom ranking logic
- Combining multiple data sources with custom logic

See also: ../01_getting_started/02_agentic_rag.py for standard Knowledge-based RAG.
"""

from typing import Optional

from agno.agent import Agent
from agno.models.openai import OpenAIResponses

# ---------------------------------------------------------------------------
# Custom Retriever
# ---------------------------------------------------------------------------

# Simulated knowledge base
_DOCUMENTS = {
    "engineering": {
        "name": "Engineering",
        "content": "The engineering team uses Python and TypeScript. "
        "They follow trunk-based development with CI/CD.",
    },
    "sales": {
        "name": "Sales",
        "content": "Q4 revenue was $2.3M, up 40% year-over-year. "
        "The sales team closed 145 deals in Q4.",
    },
    "hr": {
        "name": "HR Policy",
        "content": "PTO policy: 25 days per year. Remote work is allowed "
        "3 days per week. All employees get learning stipends.",
    },
}


def company_retriever(
    query: str, num_documents: Optional[int] = None, **kwargs
) -> list[dict]:
    """Custom retriever that returns relevant documents based on the query.

    The signature must be (query, num_documents=None, **kwargs) and the
    return type must be list[dict].

    In production, this could query a SQL database, call an API, or
    implement any custom retrieval logic.
    """
    # Simple keyword matching (replace with your logic)
    results = []
    for doc in _DOCUMENTS.values():
        if any(term in query.lower() for term in doc["name"].lower().split()):
            results.append(doc)

    all_results = results or list(_DOCUMENTS.values())
    if num_documents is not None:
        all_results = all_results[:num_documents]
    return all_results


# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

agent = Agent(
    model=OpenAIResponses(id="gpt-5.2"),
    knowledge_retriever=company_retriever,
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run Demo
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("\n" + "=" * 60)
    print("Custom retriever: query-specific document selection")
    print("=" * 60 + "\n")

    agent.print_response("What is the PTO policy?", stream=True)

    print("\n" + "=" * 60)
    print("Different query returns different documents")
    print("=" * 60 + "\n")

    agent.print_response("How did Q4 sales go?", stream=True)
