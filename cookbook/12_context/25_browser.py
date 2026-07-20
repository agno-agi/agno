"""
Browser Context Provider
========================

BrowserContextProvider wraps browser automation behind a sub-agent that handles
natural language requests. Two backends are available:

1. PlaywrightMCPBackend (local) — runs Playwright's MCP server via npx
   - Free, no API keys needed (just Node.js 18+)
   - Uses accessibility tree for token-efficient navigation

2. BrowserbaseMCPBackend (cloud) — runs Browserbase's Stagehand MCP server
   - Cloud-hosted browsers, no local Chromium needed
   - Requires BROWSERBASE_API_KEY, BROWSERBASE_PROJECT_ID, GEMINI_API_KEY

Use mode=ContextMode.tools for direct tool access instead of sub-agent routing.

Requires: OPENAI_API_KEY, Node.js 18+
"""

import asyncio

from agno.agent import Agent
from agno.context.browser import (
    BrowserbaseMCPBackend,
    BrowserContextProvider,
    PlaywrightMCPBackend,
)
from agno.context.mode import ContextMode
from agno.models.openai import OpenAIResponses


async def demo_playwright() -> None:
    """Local browser via Playwright MCP — no API keys needed."""
    print("=== Playwright MCP (local) ===\n")

    browser = BrowserContextProvider(
        backend=PlaywrightMCPBackend(headless=True),
        model=OpenAIResponses(id="gpt-5.5"),
    )

    await browser.asetup()
    try:
        agent = Agent(
            model=OpenAIResponses(id="gpt-5.5"),
            tools=browser.get_tools(),
            instructions=browser.instructions(),
            markdown=True,
        )

        await agent.aprint_response(
            "Go to https://news.ycombinator.com and tell me the top 3 stories"
        )
    finally:
        await browser.aclose()


async def demo_browserbase() -> None:
    """Cloud browser via Browserbase — requires API keys."""
    print("\n=== Browserbase MCP (cloud) ===\n")

    browser = BrowserContextProvider(
        backend=BrowserbaseMCPBackend(),
        model=OpenAIResponses(id="gpt-5.5"),
    )

    status = browser.status()
    if not status.ok:
        print(f"Skipping: {status.detail}")
        return

    await browser.asetup()
    try:
        agent = Agent(
            model=OpenAIResponses(id="gpt-5.5"),
            tools=browser.get_tools(),
            instructions=browser.instructions(),
            markdown=True,
        )

        await agent.aprint_response(
            "Go to https://example.com and extract the main heading"
        )
    finally:
        await browser.aclose()


async def demo_tools_mode() -> None:
    """Direct tool access without sub-agent routing."""
    print("\n=== Tools Mode (direct access) ===\n")

    browser = BrowserContextProvider(
        backend=PlaywrightMCPBackend(headless=True),
        mode=ContextMode.tools,
    )

    await browser.asetup()
    try:
        tools = browser.get_tools()
        print("Available browser tools:")
        for tool in tools:
            if hasattr(tool, "functions"):
                for name in tool.functions:
                    print(f"  - {name}")

        agent = Agent(
            model=OpenAIResponses(id="gpt-5.5"),
            tools=tools,
            instructions=(
                "You have direct access to browser automation tools. "
                "Use browser_navigate to go to URLs, browser_snapshot to see "
                "the page structure, and browser_click/browser_type for interaction."
            ),
            markdown=True,
        )

        await agent.aprint_response(
            "Navigate to https://example.com and take a snapshot of the page"
        )
    finally:
        await browser.aclose()


async def demo_structured_output() -> None:
    """Extract structured data from a webpage."""
    from pydantic import BaseModel, Field

    print("\n=== Structured Output ===\n")

    class Story(BaseModel):
        title: str = Field(description="The story title")
        url: str = Field(description="Link to the story or comments")
        points: int | None = Field(
            default=None, description="Points/score if available"
        )

    class TopStories(BaseModel):
        stories: list[Story] = Field(description="List of top stories")

    browser = BrowserContextProvider(
        backend=PlaywrightMCPBackend(headless=True),
        model=OpenAIResponses(id="gpt-5.5"),
    )

    await browser.asetup()
    try:
        agent = Agent(
            model=OpenAIResponses(id="gpt-5.5"),
            tools=browser.get_tools(),
            output_schema=TopStories,
        )

        response = await agent.arun(
            "Go to https://news.ycombinator.com and extract the top 3 stories"
        )

        result: TopStories = response.content
        for i, story in enumerate(result.stories, 1):
            print(f"{i}. {story.title}")
            print(f"   URL: {story.url}")
            if story.points:
                print(f"   Points: {story.points}")
            print()
    finally:
        await browser.aclose()


if __name__ == "__main__":
    asyncio.run(demo_playwright())
    # Uncomment to run other demos:
    # asyncio.run(demo_browserbase())
    # asyncio.run(demo_tools_mode())
    # asyncio.run(demo_structured_output())
