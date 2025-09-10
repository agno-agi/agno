import asyncio

from agno.agent import Agent
from agno.knowledge.knowledge import Knowledge
from agno.vectordb.pgvector import PgVector

db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"

# Create a knowledge base with the PDFs from the data/pdfs directory
knowledge = Knowledge(
    vector_db=PgVector(
        table_name="pdf_documents",
        db_url=db_url,
    )
)

# Create an agent with the knowledge base
agent = Agent(
    knowledge=knowledge,
    search_knowledge=True,
)

if __name__ == "__main__":
    asyncio.run(
        knowledge.add_content_async(
            path="cookbook/knowledge/testing_resources/cv_1.pdf",
        )
    )
    # Create and use the agent
    asyncio.run(
        agent.aprint_response(
            "What skills does an applicant require to apply for the Software Engineer position?",
            markdown=True,
        )
    )
