import asyncio

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.models.anthropic import Claude
from agno.models.google import Gemini
from agno.tools.mcp import MCPTools
from mcp import StdioServerParameters


async def run_agent(message: str) -> None:
    server_params = StdioServerParameters(
        command="npx",
        args=[
            "@playwright/mcp@latest",
        ],
    )

    async with MCPTools(
        server_params=server_params, include_tools=["browser_navigate", "browser_click"]
    ) as mcp_tools:
        agent = Agent(
            model=Claude(id="claude-sonnet-4-5-20250929"),
            tools=[mcp_tools],
            role="Your task is to use your web browsing capabilities to find information and take actions on the web.",
            markdown=True,
            exponential_backoff=True,
            db=PostgresDb(db_url="postgresql+psycopg://ai:ai@localhost:5532/ai"),
            max_tool_calls_in_context=3,  # Keep only the last 3 tool calls in context
            add_history_to_context=True,
            session_id="playwright_personality_session",
        )

        await agent.aprint_response(input=message, debug_mode=True, stream=True)


if __name__ == "__main__":
    asyncio.run(
        run_agent(
            "Look for a personality test with less than 10 questions on the web and take it. Summarize the results of the test and provide a link to the test you took.",
        )
    )
