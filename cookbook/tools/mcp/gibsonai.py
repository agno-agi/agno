"""🛢 GibsonAI MCP Server - Create and manage databases with prompts

This example shows how to connect a local GibsonAI MCP to Agno agent.
You can instantly generate, modify database schemas
and chat with your relational database using natural language.
From prompt to a serverless database (MySQL, PostgresQL, etc.), auto-generated REST APIs for your data.

Example prompts to try:
- "Create a new GibsonAI project for my e-commerce app"
- "Show me the current schema for my project"
- "Add a 'products' table with name, price, and description fields"
- "Create a 'users' table with authentication fields"
- "Deploy my schema changes to production"

How to setup and run:

1. Install [UV](https://docs.astral.sh/uv/) package manager.
2. Install the GibsonAI CLI:
    ```bash
    uvx --from gibson-cli@latest gibson auth login
    ```
3. Install the required dependencies:
    ```bash
    pip install agno mcp openai
    ```
4. Export your API key:
    ```bash
    export OPENAI_API_KEY="your_openai_api_key"
    ```
5. Run the GibsonAI agent by running this file.
6. Check created database and schema on GibsonAI dashboard: https://app.gibsonai.com

This logs you into the [GibsonAI CLI](https://docs.gibsonai.com/reference/cli-quickstart)
so you can access all the features directly from your agent.

"""

import asyncio
from textwrap import dedent

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.tools.mcp import MCPTools


async def run_gibsonai_agent(message: str):
    """Run the GibsonAI agent with the given message."""
    mcp_tools = MCPTools(
        "uvx --from gibson-cli@latest gibson mcp run",
        timeout_seconds=300,  # Extended timeout for GibsonAI operations
    )

    # Connect to the MCP server
    await mcp_tools.connect()

    agent = Agent(
        name="GibsonAIAgent",
        model=OpenAIChat(id="gpt-4o"),
        tools=[mcp_tools],
        description="Agent for managing database projects and schemas",
        instructions=dedent("""\
            You are a GibsonAI database assistant. Help users manage their database projects and schemas.

            Your capabilities include:
            - Creating new GibsonAI projects
            - Managing database schemas (tables, columns, relationships)
            - Deploying schema changes to hosted databases
            - Querying database schemas and data
            - Providing insights about database structure and best practices
        """),
        markdown=True,
    )

    # Run the agent
    await agent.aprint_response(message, stream=True)

    # Close the MCP connection
    await mcp_tools.close()


# Example usage
if __name__ == "__main__":
    asyncio.run(
        run_gibsonai_agent(
            """
            Create a database for blog posts platform with users and posts tables.
            You can decide the schema of the tables without double checking with me.
            """
        )
    )
