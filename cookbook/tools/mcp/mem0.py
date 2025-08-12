"""
👩‍💻 Mem0 MCP - Personalized Code Reviewer

This example demonstrates how to use Agno's MCP integration together with Mem0, to build a personalized code reviewer.

- Run your Mem0 MCP server. Full instructions: https://github.com/mem0ai/mem0-mcp
- Run: `pip install agno mcp` to install the dependencies
"""

import asyncio
from textwrap import dedent

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.tools.mcp import MCPTools

mcp_server_url = "http://localhost:8080/sse"


async def run_agent(message: str) -> None:
    async with MCPTools(url=mcp_server_url, transport="sse") as mcp_tools:
        agent = Agent(
            tools=[mcp_tools],
            model=OpenAIChat(id="o4-mini"),
            instructions=dedent(
                """
                You are a professional code reviewer. You help users keep their code clean and on line with their preferences.
                You have access to some tools to keep track of coding preferences you need to enforce when reviewing code.
                You will be given a code snippet and you need to review it and provide feedback on it.
                """
            ),
        )
        await agent.aprint_response(message, stream=True)


if __name__ == "__main__":
    # The agent will use mem0 memory to keep track of the user's preferences.
    asyncio.run(
        run_agent(
            "When possible, use the walrus operator to make the code more readable."
        )
    )
    # The agent will review your code and propose improvements based on your preferences.
    asyncio.run(
        run_agent(
            dedent(
                """
Please, review this Python snippet:

```python
def process_data(data):
    length = len(data)
    if length > 10:
        print(f"Processing {length} items")
        return data[:10]
    return data

# Example usage
items = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12]
result = process_data(items)
```
"""
            )
        )
    )
