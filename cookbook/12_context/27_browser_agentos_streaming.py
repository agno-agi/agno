"""
Browser Context Provider — AgentOS Streaming
=============================================

Tests browser sub-agent event streaming through os.agno.com. When the parent
agent calls query_browser, the sub-agent's events (tool calls like
browser_navigate, browser_snapshot) are streamed back in real-time.

Run locally:
    python cookbook/12_context/27_browser_agentos_streaming.py

Then open os.agno.com and connect to http://localhost:7777

Requires: OPENAI_API_KEY, Node.js 18+
"""

from agno.agent import Agent
from agno.context.browser import BrowserContextProvider, PlaywrightMCPBackend
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS

browser = BrowserContextProvider(
    id="browser",
    backend=PlaywrightMCPBackend(headless=True),
    model=OpenAIResponses(id="gpt-5.5"),
)

agent = Agent(
    name="Browser Assistant",
    model=OpenAIResponses(id="gpt-5.5"),
    tools=browser.get_tools(),
    instructions=[
        browser.instructions(),
        "You help users browse the web and extract information.",
        "When asked about a website, use query_browser to navigate and read it.",
    ],
    markdown=True,
)

agent_os = AgentOS(
    description="Browser context provider streaming demo",
    agents=[agent],
)
app = agent_os.get_app()

if __name__ == "__main__":
    print("Starting AgentOS on http://localhost:7777")
    print("Connect via os.agno.com and ask: 'Go to news.ycombinator.com and get the top 3 stories'")
    print()
    agent_os.serve(app="27_browser_agentos_streaming:app", reload=True)
