import asyncio

from agno.agent import Agent
from agno.knowledge.embedder.openai import OpenAIEmbedder
from agno.knowledge.knowledge import Knowledge
from agno.models.openai import OpenAIChat
from agno.vectordb.milvus import Milvus

agent = Agent(
    model=OpenAIChat(
        id="gpt-4o",
    ),
    knowledge=Knowledge(
        vector_db=Milvus(
            collection="recipe_documents",
            uri="http://localhost:19530",
            embedder=OpenAIEmbedder(enable_batch=True),
        ),
    ),
    # Enable the agent to search the knowledge base
    search_knowledge=True,
    # Enable the agent to read the chat history
    read_chat_history=True,
)


async def main():
    # Insert data
    await agent.knowledge.ainsert(
        path="cookbook/07_knowledge/testing_resources/cv_1.pdf"
    )

    # Create and use the agent
    await agent.aprint_response(
        "What can you tell me about the candidate and what are his skills?",
        markdown=True,
    )


if __name__ == "__main__":
    asyncio.run(main())
