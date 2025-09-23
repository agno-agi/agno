import asyncio

from agno.agent import Agent
from agno.knowledge.knowledge import Knowledge
from agno.vectordb.databend import Databend

agent = Agent(
    knowledge=Knowledge(
        vector_db=Databend(
            table_name="recipe_documents",
            host="localhost",
            port=8000,
            username="default",
            password="",
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
            url="https://docs.agno.com/introduction/agents.md"
        )
    )

    # Create and use the agent
    asyncio.run(
        agent.aprint_response("What is the purpose of an Agno Agent?", markdown=True)
    )
