import asyncio

from agno.agent import Agent
from agno.knowledge.youtube import YouTubeKnowledgeBase, YouTubeReader
from agno.vectordb.qdrant import Qdrant

COLLECTION_NAME = "youtube-reader"

vector_db = Qdrant(collection=COLLECTION_NAME, url="http://localhost:6333")

knowledge_base = YouTubeKnowledgeBase(
    urls=[
        "https://www.youtube.com/watch?v=CDC3GOuJyZ0",
        "https://www.youtube.com/watch?v=JbF_8g1EXj4",
    ],
    vector_db=vector_db,
    reader=YouTubeReader(chunk=True),
)

agent = Agent(
    knowledge=knowledge_base,
    search_knowledge=True,
)

if __name__ == "__main__":
    # Comment out after first run
    asyncio.run(knowledge_base.aload(recreate=False))

    # Create and use the agent
    asyncio.run(
        agent.aprint_response(
            "What is the major focus of the knowledge provided in both the videos, explain briefly.",
            markdown=True,
        )
    )
