"""
Browser Toolkits (Direct Access)
================================

Use toolkits directly when you don't need the BrowserContextProvider abstraction:
- Full control over browser configuration
- Access to toolkit-specific features (video recording, console logs)
- No sub-agent overhead

Two toolkits available:

1. PlaywrightTools — local browser via Playwright SDK
   - Video recording, PDF generation, console capture
   - Requires: playwright install chromium

2. BrowserbaseTools — cloud browser via Browserbase SDK
   - Session recording, ad blocking, CAPTCHA solving
   - Requires: BROWSERBASE_API_KEY, BROWSERBASE_PROJECT_ID

Requires: OPENAI_API_KEY
"""

import asyncio
from os import getenv

from agno.agent import Agent
from agno.models.openai import OpenAIResponses


async def demo_playwright_tools() -> None:
    """Local browser with video recording."""
    print("=== PlaywrightTools (local) ===\n")

    from agno.tools.playwright import PlaywrightTools

    browser_tools = PlaywrightTools(
        headless=True,
        record_video_dir="/tmp/playwright_recordings",
        all=True,
    )

    agent = Agent(
        model=OpenAIResponses(id="gpt-5.5"),
        tools=[browser_tools],
        instructions=browser_tools.instructions,
        markdown=True,
    )

    await agent.aprint_response(
        "Go to https://example.com and tell me what you see. Then close the session."
    )

    print("\nVideo saved to /tmp/playwright_recordings/")


async def demo_browserbase_tools() -> None:
    """Cloud browser with session recording."""
    print("\n=== BrowserbaseTools (cloud) ===\n")

    if not getenv("BROWSERBASE_API_KEY") or not getenv("BROWSERBASE_PROJECT_ID"):
        print("Skipping: missing BROWSERBASE_API_KEY or BROWSERBASE_PROJECT_ID")
        return

    from agno.tools.browserbase import BrowserbaseTools

    browser_tools = BrowserbaseTools()

    agent = Agent(
        model=OpenAIResponses(id="gpt-5.5"),
        tools=[browser_tools],
        instructions=browser_tools.instructions,
        markdown=True,
    )

    await agent.aprint_response(
        "Go to https://example.com, tell me what you see, "
        "get the session URL for the recording, then close the session."
    )


if __name__ == "__main__":
    asyncio.run(demo_playwright_tools())
    # Uncomment to run Browserbase demo:
    # asyncio.run(demo_browserbase_tools())
