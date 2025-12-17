from agno.agent import Agent
from agno.knowledge.embedder.openai import OpenAIEmbedder
from agno.knowledge.knowledge import Knowledge
from agno.knowledge.reranker.cohere import CohereReranker
from agno.models.openai import OpenAIChat
from agno.vectordb.redis import RedisDB

knowledge = Knowledge(
    vector_db=RedisDB(
        index_name="agno_docs",
        redis_url="redis://localhost:6379",
        embedder=OpenAIEmbedder(id="text-embedding-3-small"),
        reranker=CohereReranker(model="rerank-multilingual-v3.0"),
    ),
)

knowledge.add_content(name="Agno Docs", url="https://docs.agno.com/introduction.md")

agent = Agent(
    model=OpenAIChat(id="gpt-5-mini"),
    knowledge=knowledge,
    markdown=True,
)

if __name__ == "__main__":
    # Load the knowledge base, comment after first run
    # agent.knowledge.load(recreate=True)
    agent.print_response("What are Agno's key features?")
