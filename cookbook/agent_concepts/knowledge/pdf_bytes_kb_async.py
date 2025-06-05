import asyncio

from agno.agent import Agent
from agno.knowledge.pdf import PDFBytesKnowledgeBase
from agno.vectordb.lancedb import LanceDb


vector_db = LanceDb(
    table_name="recipes_async",
    uri="tmp/lancedb",
)

with open("data/pdfs/ThaiRecipes.pdf", "rb") as f:
    pdf_bytes = f.read()

knowledge_base = PDFBytesKnowledgeBase(
    pdfs=[pdf_bytes],
    vector_db=vector_db,
)

agent = Agent(
    knowledge=knowledge_base,
    search_knowledge=True,
)

if __name__ == "__main__":
    # Comment out after first run
    asyncio.run(knowledge_base.aload(recreate=False))

    # Create and use the agent
    asyncio.run(agent.aprint_response("How to make Tom Kha Gai?", markdown=True))
