import asyncio
from pathlib import Path

from agno.agent import Agent
from agno.knowledge.csv import CSVKnowledgeBase
from agno.vectordb.qdrant import Qdrant

COLLECTION_NAME = "csv-reader"

vector_db = Qdrant(collection=COLLECTION_NAME, url="http://localhost:6333")


knowledge_base = CSVKnowledgeBase(
    path=Path("data/csv"),
    vector_db=vector_db,
    num_documents=5,  # Number of documents to return on search
)

# Initialize the Agent with the knowledge_base
agent = Agent(
    knowledge=knowledge_base,
    search_knowledge=True,
)

if __name__ == "__main__":
    # Comment out after first run
    asyncio.run(knowledge_base.aload(recreate=False))

    # Create and use the agent
    asyncio.run(agent.aprint_response("What is the csv file about", markdown=True))
