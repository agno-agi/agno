import asyncio
from os import getenv

from agno.agent import Agent
from agno.knowledge.knowledge import Knowledge
from agno.knowledge.reader.wikipedia_reader import WikipediaReader
from agno.vectordb.lightrag import LightRag

vector_db = LightRag(
    api_key=getenv("LIGHTRAG_API_KEY"),
)

knowledge = Knowledge(
    name="My Pinecone Knowledge Base",
    description="This is a knowledge base that uses a Pinecone Vector DB",
    vector_db=vector_db,
)


asyncio.run(
    knowledge.add_content_async(
        name="Recipes",
        path="cookbook/knowledge/testing_resources/cv_1.pdf",
        metadata={"doc_type": "recipe_book"},
    )
)

asyncio.run(
    knowledge.add_content_async(
        name="Recipes",
        topics=["Manchester United"],
        reader=WikipediaReader(),
    )
)

asyncio.run(
    knowledge.add_content_async(
        name="Recipes",
        url="https://en.wikipedia.org/wiki/Manchester_United_F.C.",
    )
)


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
