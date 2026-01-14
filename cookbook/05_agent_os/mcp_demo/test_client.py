"""
First run the AgentOS with enable_mcp=True

```bash
python cookbook/agent_os/mcp/enable_mcp.py
```
"""

import asyncio
from uuid import uuid4

from agno.agent import Agent
from agno.db.in_memory import InMemoryDb
from agno.models.openai import OpenAIChat
from agno.tools.mcp import MCPTools

# This is the URL of the MCP server we want to use.
server_url = "http://localhost:7777/mcp"

session_id = f"session_{uuid4()}"


async def run_agent() -> None:
    async with MCPTools(
        transport="streamable-http", url=server_url, timeout_seconds=60
    ) as mcp_tools:
        agent = Agent(
            model=OpenAIChat(id="gpt-5-mini"),
            tools=[mcp_tools],
            instructions=[
                "You are a helpful assistant that has access to the configuration of a AgentOS.",
                "If you are asked to do something, use the appropriate tool to do it. ",
                "Look up information you need in the AgentOS configuration.",
            ],
            user_id="john@example.com",
            session_id=session_id,
            db=InMemoryDb(),
            add_session_state_to_context=True,
            add_history_to_context=True,
            markdown=True,
        )

        await agent.aprint_response(
            input="Which agents do I have in my AgentOS?", stream=True, markdown=True
        )

        # await agent.aprint_response(
        #     input="Use my agent to search the web for the latest news about AI",
        #     stream=True,
        #     markdown=True,
        # )

        ## Memory management
        # await agent.aprint_response(
        #     input="What memories do you have of me?",
        #     stream=True,
        #     markdown=True,
        # )

        # await agent.aprint_response(
        #     input="I like to ski, remember that of me.",
        #     stream=True,
        #     markdown=True,
        # )
        # await agent.aprint_response(
        #     input="Clean up all duplicate memories of me.",
        #     stream=True,
        #     markdown=True,
        # )

        ## Session management
        # await agent.aprint_response(
        #     input="How many sessions does my web-research-agent have?",
        #     stream=True,
        #     markdown=True,
        # )


# Example usage
if __name__ == "__main__":
    asyncio.run(run_agent())
