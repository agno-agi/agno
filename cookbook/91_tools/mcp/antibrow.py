"""
AntiBrow MCP Agent - Browsing With a Persistent Identity

This example shows how to drive AntiBrow's MCP server from an Agno agent, so the
browser the agent uses keeps its cookies, storage, fingerprint and exit IP between
runs instead of starting over in a fresh Chromium every session.

Features:
- A named profile: sign in once, still signed in on the next run
- 19 MCP tools, including launch_browser, navigate, click, fill, get_content
- The browser runs locally, so there are no browser-hours to buy

Prerequisites:
- Install dependencies: uv pip install agno mcp
- Set environment variables: ANTI_DETECT_BROWSER_KEY, OPENAI_API_KEY
- Run this example: python cookbook/91_tools/mcp/antibrow.py

Note on the command below: the MCP protocol SDK is an optional peer dependency of
the npm package, which is why both `-p` flags are needed. Without them the server
exits with "MCP server mode needs @modelcontextprotocol/sdk".
"""

import asyncio
from os import environ
from textwrap import dedent

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.tools.mcp import MCPTools
from mcp import StdioServerParameters

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------


async def run_agent(message: str) -> None:
    server_params = StdioServerParameters(
        command="npx",
        args=[
            "-y",
            "-p",
            "anti-detect-browser",
            "-p",
            "@modelcontextprotocol/sdk",
            "anti-detect-browser",
            "--mcp",
        ],
        env=environ.copy(),
    )

    async with MCPTools(server_params=server_params, timeout_seconds=120) as mcp_tools:
        agent = Agent(
            model=OpenAIChat(id="gpt-5.6-luna"),
            tools=[mcp_tools],
            instructions=dedent("""\
                You drive a real browser through the AntiBrow MCP server.

                Order of operations:
                1. launch_browser first, with a profile name. The profile is created if new,
                   and reused if it already exists - that is what keeps the session alive
                   between runs, so check what is already on screen before signing in again.
                2. navigate, then get_content to read the page. Prefer get_content over
                   screenshot: text costs far fewer tokens than an image.
                3. click and fill take CSS selectors. evaluate is there for the cases a
                   selector cannot express.
                4. close_browser when you are done. An abandoned browser is a whole
                   Chromium still running.

                One profile is one identity. If a task needs two identities that must not
                be linked, launch two profiles rather than two tabs.
            """),
            markdown=True,
        )
        await agent.aprint_response(message, stream=True)


# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    asyncio.run(
        run_agent(
            "Using the profile 'research-01', open https://news.ycombinator.com and summarise the top three stories."
        )
    )
