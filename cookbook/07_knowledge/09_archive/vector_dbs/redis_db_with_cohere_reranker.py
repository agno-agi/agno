"""
Redis With Cohere Reranker
==========================

Demonstrates Redis vector retrieval with Cohere reranking.
"""

from agno.agent import Agent
from agno.knowledge.embedder.openai import OpenAIEmbedder
from agno.knowledge.knowledge import Knowledge
from agno.knowledge.reranker.cohere import CohereReranker
from agno.models.openai import OpenAIChat
from agno.vectordb.redis import RedisDB

# ---------------------------------------------------------------------------
# Create Knowledge Base
# ---------------------------------------------------------------------------
knowledge = Knowledge(
    vector_db=RedisDB(
        index_name="agno_docs",
        redis_url="redis://localhost:6379",
        embedder=OpenAIEmbedder(id="text-embedding-3-small"),
        reranker=CohereReranker(model="rerank-multilingual-v3.0"),
    ),
)


# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
agent = Agent(
    model=OpenAIChat(id="gpt-5.2"),
    knowledge=knowledge,
    markdown=True,
)


# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
def main() -> None:
    knowledge.insert(name="Agno Docs", url="https://docs.agno.com/introduction.md")
    agent.print_response("What are Agno's key features?")


if __name__ == "__main__":
    main()
