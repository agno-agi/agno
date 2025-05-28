from agno.agent import Agent
from agno.knowledge.light_rag import LightRagKnowledgeBase
from agno.vectordb.pgvector import PgVector
import asyncio

db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"

# Create a knowledge base with the PDFs from the data/pdfs directory

async def main():
    knowledge_base = await LightRagKnowledgeBase.create(
        path="tmp/",
        # vector_db=PgVector(
        #     table_name="pdf_documents",
        #     # Can inspect database via psql e.g. "psql -h localhost -p 5432 -U ai -d ai"
        #     db_url=db_url,
        # ),
        # reader=PDFReader(chunk=True),
    )

    await knowledge_base.load(recreate=False)
    print(await knowledge_base.search("What expertise does the candidate have?"))


# Load the knowledge base

# # Create an agent with the knowledge base
# agent = Agent(
#     knowledge=knowledge_base,
#     search_knowledge=True,
# )

# # Ask the agent about the knowledge base
# agent.print_response("Ask me about something from the knowledge base", markdown=True)


if __name__ == "__main__":
    asyncio.run(main())