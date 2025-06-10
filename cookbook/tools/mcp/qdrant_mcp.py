"""📁 Qdrant MCP Agent - Your Personal Knowledge Base Assistant!

This example demonstrates how to create a knowledge base agent that uses MCP to interact with a Qdrant vector database.
The agent leverages the Model Context Protocol (MCP) to store and retrieve information, allowing it to remember conversations
and build a persistent knowledge base.

Example prompts to try:
- "What is the difference between deep learning and machine learning?"
- "Tell me about natural language processing"
- "What are the applications of computer vision?"

Run: `pip install agno mcp openai` to install the dependencies

Export the following environment variables:

```bash
export OPENAI_API_KEY="sk-..."
export QDRANT_API_KEY="..."
```

"""

import os
from textwrap import dedent

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.tools.mcp import MCPTools
import asyncio


async def run_qdrant_mcp_agent(question: str):
    """Run the qdrant agent with the given message."""

    # initialize the Qdrant MCP server
    async with MCPTools(
        "uvx mcp-server-qdrant",
        env={
            "QDRANT_URL": "http://localhost:6333", # your qdrant instance: local or cloud
            "COLLECTION_NAME": "TEST", # your qdrant collection name
            **os.environ,
        }
    ) as mcp_tools:
        agent = Agent(
            name="Qdrant Memory Assistant",
            description="memory assistant",
            model=OpenAIChat(id="o3-mini"),
            tools=[mcp_tools],
            instructions=dedent("""
            You are a database expert, your job is to push the data to database, knowledge base.

            1. always create a JSON structure of user query and agent response as
               example: {'user': <USER_QUERY>, 'assistant': <ASSISTANT_ANSWER>}
            2. after you create the structure always use MCP tools available to push the data into
               the knowledge base or database.\
            """),
            markdown=True,
            show_tool_calls=True,
        )

        await agent.aprint_response(question)

async def main():
    await run_qdrant_mcp_agent("What is the difference of LLM and VLM?")

if __name__ == "__main__":
    asyncio.run(main())

