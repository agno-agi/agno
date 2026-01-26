import asyncio
import time
from os import getenv

from agno.agent import Agent
from agno.knowledge.knowledge import Knowledge
from agno.knowledge.reader.wikipedia_reader import WikipediaReader
from agno.vectordb.lightrag import LightRag

vector_db = LightRag(
    server_url=getenv("LIGHTRAG_SERVER_URL", "http://localhost:9621"),
    api_key=getenv("LIGHTRAG_API_KEY"),
)

knowledge = Knowledge(
    name="LightRAG Knowledge Base",
    description="Knowledge base using LightRAG for graph-based retrieval",
    vector_db=vector_db,
)


asyncio.run(
    knowledge.ainsert(
        name="Recipes",
        path="cookbook/07_knowledge/testing_resources/cv_1.pdf",
        metadata={"doc_type": "recipe_book"},
    )
)

asyncio.run(
    knowledge.ainsert(
        name="Recipes",
        topics=["Manchester United"],
        reader=WikipediaReader(),
    )
)

asyncio.run(
    knowledge.ainsert(
        name="Recipes",
        path="cookbook/07_knowledge/testing_resources/cv_2.pdf",
    )
)

# Wait for LightRAG to index documents
time.sleep(60)

agent = Agent(
    knowledge=knowledge,
    search_knowledge=True,
    read_chat_history=False,
)


asyncio.run(
    agent.aprint_response("What skills does Jordan Mitchell have?", markdown=True)
)

asyncio.run(
    agent.aprint_response(
        "In what year did Manchester United change their name?", markdown=True
    )
)

# Search results include references to source documents
results = asyncio.run(vector_db.async_search("What skills does Jordan Mitchell have?"))
if results:
    doc = results[0]
    print(f"References: {doc.meta_data.get('references', [])}")
