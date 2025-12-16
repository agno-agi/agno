import asyncio

from agno.agent import Agent
from agno.knowledge.knowledge import Knowledge
from agno.knowledge.reader.arxiv_reader import ArxivReader
from agno.vectordb.pgvector import PgVector

db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"

knowledge = Knowledge(
    # Table name: ai.arxiv_documents
    vector_db=PgVector(
        table_name="arxiv_documents",
        db_url=db_url,
    ),
)

# Create an agent with the knowledge
agent = Agent(
    knowledge=knowledge,
    search_knowledge=True,
)


def main():
    # Load the knowledge
    asyncio.run(
        knowledge.add_content_async(
            topics=["Generative AI", "Machine Learning"],
            reader=ArxivReader(),
        )
    )

    # Create and use the agent
    asyncio.run(
        agent.aprint_response(
            "What can you tell me about Generative AI?", markdown=True
        )
    )
