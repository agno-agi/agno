"""
LiteLLM Reranker Example with PgVector
======================================

Demonstrates the LiteLLM reranker with PgVector for retrieval augmented generation.

LiteLLM routes to the provider named in the model string, so the key you need is
the provider's own. A "cohere/..." rerank model requires COHERE_API_KEY; the
embedder below routes to OpenAI and requires OPENAI_API_KEY.

Requirements:
- pip install litellm
- export OPENAI_API_KEY=...    (for the embedder)
- export COHERE_API_KEY=...    (for the rerank model below)
- PostgreSQL with pgvector running
"""

from agno.agent import Agent
from agno.knowledge.embedder.litellm import LiteLLMEmbedder
from agno.knowledge.knowledge import Knowledge
from agno.knowledge.reranker.litellm import LiteLLMReranker
from agno.models.openai import OpenAIResponses
from agno.vectordb.pgvector import PgVector

# ---------------------------------------------------------------------------
# Create Knowledge Base
# ---------------------------------------------------------------------------
knowledge = Knowledge(
    vector_db=PgVector(
        table_name="litellm_rerank_demo",
        db_url="postgresql+psycopg://ai:ai@localhost:5532/ai",
        embedder=LiteLLMEmbedder(
            id="openai/text-embedding-3-small",
            dimensions=1536,
        ),
        reranker=LiteLLMReranker(
            model="cohere/rerank-multilingual-v3.0",
            top_n=5,
        ),
    ),
)


# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
agent = Agent(
    model=OpenAIResponses(id="gpt-5.6-luna"),
    knowledge=knowledge,
    search_knowledge=True,
    instructions=[
        "Always search your knowledge base before answering.",
        "Include sources in your response.",
    ],
    markdown=True,
)


# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
def main() -> None:
    knowledge.insert(name="Agno Docs", url="https://docs.agno.com/agents/overview.md")
    agent.print_response("What is the purpose of an Agno Agent?")


if __name__ == "__main__":
    main()
