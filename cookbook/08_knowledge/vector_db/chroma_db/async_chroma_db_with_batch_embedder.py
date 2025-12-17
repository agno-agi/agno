# install chromadb - `pip install chromadb`

import asyncio

from agno.agent import Agent
from agno.knowledge.embedder.openai import OpenAIEmbedder
from agno.knowledge.knowledge import Knowledge
from agno.vectordb.chroma import ChromaDb

# Initialize ChromaDB
vector_db = ChromaDb(
    collection="recipes",
    path="tmp/chromadb",
    persistent_client=True,
    embedder=OpenAIEmbedder(enable_batch=True),
)

# Create knowledge base
knowledge = Knowledge(
    vector_db=vector_db,
)

# Create and use the agent
agent = Agent(knowledge=knowledge)

if __name__ == "__main__":
    # Comment out after first run
    asyncio.run(
        knowledge.add_content_async(
            path="cookbook/knowledge/testing_resources/cv_1.pdf"
        )
    )

    # Create and use the agent
    asyncio.run(
        agent.aprint_response("What is the purpose of an Agno Agent?", markdown=True)
    )
