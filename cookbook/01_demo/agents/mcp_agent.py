"""
MCP Agent - A general-purpose agent that connects to MCP servers.

This agent demonstrates how to build an MCP-powered assistant that:
- Connects to any MCP server via streamable-http transport
- Uses MCP tools to search and retrieve information
- Generates working code examples

The agent uses docs.agno.com/mcp as an example MCP server,
but can be configured to use any MCP server.

Example queries:
- "What is Agno?"
- "How do I create an agent with tools?"
- "Search for information about teams"
"""

import sys
from textwrap import dedent

from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.tools.mcp import MCPTools
from db import demo_db

# ============================================================================
# Description & Instructions
# ============================================================================
description = dedent(
    """\
    You are an MCP Agent - an AI assistant that uses MCP (Model Context Protocol)
    to access external tools and knowledge sources.\
    """
)

instructions = dedent(
    """\
    Your mission is to provide helpful responses using the MCP tools available to you.

    Follow this process:

    1. **Analyze the request**
        - Determine what information is needed
        - Identify which MCP tools can help

    2. **Search Process**
        - Use the available MCP tools to find relevant information
        - Perform iterative searches until you have comprehensive information

    3. **Response Guidelines**
        - Provide accurate, well-sourced answers
        - If asked for code, provide complete, working examples
        - Include all necessary imports and setup
        - Be specific and actionable

    4. **Code Examples**
        - Provide fully working code that can be run as-is
        - Write clear descriptions and instructions for agents
        - Always use `agent.run()` for execution
        - Include comments explaining key parts

        Example:
        ```python
        from agno.agent import Agent
        from agno.tools.websearch import WebSearchTools

        agent = Agent(tools=[WebSearchTools()])

        response = agent.run("What's happening in France?")
        print(response)
        ```

    5. **Handling Uncertainty**
        - If you can't find the information, say so clearly
        - Don't make up information
        - Suggest alternative approaches if needed
    """
)

# ============================================================================
# Create the Agent
# ============================================================================
mcp_agent = Agent(
    name="MCP Agent",
    model=OpenAIResponses(id="gpt-5.2"),
    tools=[MCPTools(transport="streamable-http", url="https://docs.agno.com/mcp")],
    description=description,
    instructions=instructions,
    add_history_to_context=True,
    add_datetime_to_context=True,
    enable_agentic_memory=True,
    num_history_runs=5,
    markdown=True,
    db=demo_db,
)


# ============================================================================
# Demo Tests
# ============================================================================
if __name__ == "__main__":
    print("=" * 60)
    print("MCP Agent")
    print("   MCP-powered assistant using docs.agno.com/mcp")
    print("=" * 60)

    if len(sys.argv) > 1:
        # Run with command line argument
        message = " ".join(sys.argv[1:])
        mcp_agent.print_response(message, stream=True)
    else:
        # Run demo tests
        print("\n--- Demo 1: General Question ---")
        mcp_agent.print_response(
            "What is Agno?",
            stream=True,
        )

        print("\n--- Demo 2: Code Request ---")
        mcp_agent.print_response(
            "Show me how to create a simple agent",
            stream=True,
        )

        print("\n--- Demo 3: Search ---")
        mcp_agent.print_response(
            "Search for information about how to use teams in Agno",
            stream=True,
        )
