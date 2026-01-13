import asyncio
from os import getenv

from agno.agent import Agent
from agno.models.google import Gemini
from agno.tools.mcp import MCPTools
from agno.utils.pprint import apprint_run_response

QDRANT_URL = getenv("QDRANT_URL")
QDRANT_API_KEY = getenv("QDRANT_API_KEY")
COLLECTION_NAME = "qdrant_collection"
EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"


async def run_agent(message: str) -> None:
    async with MCPTools(
        "uvx mcp-server-qdrant",
        env={
            "QDRANT_URL": QDRANT_URL,
            "QDRANT_API_KEY": QDRANT_API_KEY,
            "COLLECTION_NAME": COLLECTION_NAME,
            "EMBEDDING_MODEL": EMBEDDING_MODEL,
        },
    ) as mcp_tools:
        agent = Agent(
            model=Gemini(id="gemini-2.5-flash-preview-05-20"),
            tools=[mcp_tools],
            instructions="""
            You are the storage agent for the Model Context Protocol (MCP) server.
            You need to save the files in the vector database and answer the user's questions.
            You can use the following tools:
            - qdrant-store: Store data/output in the Qdrant vector database.
            - qdrant-find: Retrieve data/output from the Qdrant vector database.
            """,
            markdown=True,
        )

        response = await agent.arun(message, stream=True)
        await apprint_run_response(response)


if __name__ == "__main__":
    query = """
    Tell me about the extinction event of dinosaurs in detail. Include all possible theories and evidence. Store the result in the vector database.
    """
    asyncio.run(run_agent(query))
