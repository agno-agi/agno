"""
Agentic RAG: Tool-Based Search
================================
The agent gets a search_knowledge_base tool and decides when to query the
knowledge base. This is more flexible than basic RAG - the agent can choose
to search multiple times, refine queries, or skip searching entirely.

This is the default behavior when you set knowledge on an Agent.

Steps:
1. Create a Knowledge base with a vector database
2. Load a document
3. Create an Agent with search_knowledge=True (the default)
4. Ask questions - agent decides when to search

See also: 01_basic_rag.py for automatic context injection.
"""

from agno.agent import Agent
from agno.knowledge.embedder.openai import OpenAIEmbedder
from agno.knowledge.knowledge import Knowledge
from agno.models.openai import OpenAIResponses
from agno.vectordb.pgvector import PgVector, SearchType

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------

db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"

knowledge = Knowledge(
    vector_db=PgVector(
        table_name="agentic_rag",
        db_url=db_url,
        search_type=SearchType.hybrid,
        embedder=OpenAIEmbedder(id="text-embedding-3-small"),
    ),
)

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

# Agentic RAG: the agent gets a search tool and decides when to use it.
# This is the default when knowledge is provided to an Agent.
agent = Agent(
    model=OpenAIResponses(id="gpt-5.2"),
    knowledge=knowledge,
    search_knowledge=True,
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run Demo
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    knowledge.insert(url="https://agno-public.s3.amazonaws.com/recipes/ThaiRecipes.pdf")

    print("\n" + "=" * 60)
    print("Agentic RAG: Agent decides when to search")
    print("=" * 60 + "\n")

    agent.print_response(
        "How do I make chicken and galangal in coconut milk soup",
        stream=True,
    )

    print("\n" + "=" * 60)
    print("Multi-part question: agent may search multiple times")
    print("=" * 60 + "\n")

    agent.print_response(
        "I want to make a 3 course Thai meal. Can you recommend a soup, "
        "a curry for the main course, and a dessert?",
        stream=True,
    )
