import asyncio
from os import getenv

from agno.agent import Agent
from agno.knowledge.embedder.openai import OpenAIEmbedder
from agno.knowledge.knowledge import Knowledge
from agno.models.openai import OpenAIChat
from agno.vectordb.weaviate import Weaviate

agent = Agent(
    model=OpenAIChat(
        id="gpt-4o-mini",
    ),
    knowledge=Knowledge(
        vector_db=Weaviate(
            wcd_url=getenv("WEAVIATE_URL", "http://localhost:8081"),
            wcd_api_key=getenv("WEAVIATE_API_KEY", ""),
            collection="documents",
            embedder=OpenAIEmbedder(enable_batch=True),
        ),
    ),
    # Enable the agent to search the knowledge base
    search_knowledge=True,
    # Enable the agent to read the chat history
    read_chat_history=True,
)

if __name__ == "__main__":
    # Comment out after first run
    asyncio.run(
        agent.knowledge.add_content_async(
            path="cookbook/knowledge/testing_resources/cv_1.pdf"
        )
    )

    # Create and use the agent
    asyncio.run(
        agent.aprint_response(
            "What can you tell me about the candidate and what are his skills?",
            markdown=True,
        )
    )
