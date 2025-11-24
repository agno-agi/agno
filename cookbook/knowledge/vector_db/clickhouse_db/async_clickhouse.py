import asyncio

from agno.agent import Agent
from agno.knowledge.knowledge import Knowledge
from agno.vectordb.clickhouse import Clickhouse

agent = Agent(
    knowledge=Knowledge(
        vector_db=Clickhouse(
            table_name="documentss",
            host="localhost",
            port=8123,
            username="ai",
            password="ai",
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
            url="https://docs.agno.com/basics/agents/overview.md"
        )
    )

    # Create and use the agent
    asyncio.run(
        agent.aprint_response("What is the purpose of an Agno Agent?", markdown=True)
    )
