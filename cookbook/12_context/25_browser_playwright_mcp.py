"""
Browser Context Provider with Playwright MCP
=============================================

BrowserContextProvider wraps a `ContextBackend` for browser automation.
Here we use `PlaywrightMCPBackend` which runs Playwright's official MCP
server via stdio.

The MCP server exposes browser tools using an accessibility tree, which
is more token-efficient than vision-based approaches (~1/4 the tokens).

Requires:
    OPENAI_API_KEY
    Node.js 18+ (npx will download @playwright/mcp on first run)
"""

from __future__ import annotations

import asyncio

from agno.agent import Agent
from agno.context.browser import BrowserContextProvider, PlaywrightMCPBackend
from agno.models.openai import OpenAIResponses

# ---------------------------------------------------------------------------
# Create the provider
# ---------------------------------------------------------------------------

# PlaywrightMCPBackend starts the Playwright MCP server via npx
# headless=True runs the browser without a visible window
backend = PlaywrightMCPBackend(headless=True)

# BrowserContextProvider wraps the backend in a sub-agent that handles
# natural language browsing requests
browser = BrowserContextProvider(
    backend=backend,
    model=OpenAIResponses(id="gpt-5.4-mini"),  # Model for the sub-agent
)

# ---------------------------------------------------------------------------
# Create the Agent
# ---------------------------------------------------------------------------
agent = Agent(
    model=OpenAIResponses(id="gpt-5.4"),
    tools=browser.get_tools(),
    instructions=browser.instructions(),
    markdown=True,
)


# ---------------------------------------------------------------------------
# Run the Agent
# ---------------------------------------------------------------------------
async def main():
    print(f"\nbrowser.status() = {browser.status()}\n")

    # Setup connects to the MCP server and launches the browser
    await browser.asetup()
    print(f"browser.status() = {browser.status()}\n")

    try:
        prompt = "Go to https://news.ycombinator.com and tell me the top 3 stories"
        print(f"> {prompt}\n")
        await agent.aprint_response(prompt)
    finally:
        # Always close to clean up the browser process
        await browser.aclose()


if __name__ == "__main__":
    asyncio.run(main())
