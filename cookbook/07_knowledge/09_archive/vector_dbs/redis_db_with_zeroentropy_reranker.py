"""
Redis With ZeroEntropy Reranker
===============================

Demonstrates Redis vector retrieval with ZeroEntropy reranking.
"""

from agno.agent import Agent
from agno.knowledge.embedder.openai import OpenAIEmbedder
from agno.knowledge.knowledge import Knowledge
from agno.knowledge.reranker.zeroentropy import ZeroEntropyReranker
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
        reranker=ZeroEntropyReranker(
            model="zerank-2",
            top_n=5,
        ),
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
