from agno.agent import Agent
from agno.models.google import Gemini

from agno.tools.webbrowsertool import WebBrowserTools
from agno.tools.duckduckgo import DuckDuckGoTools

agent = Agent(
    model=Gemini("gemini-2.0-flash"),
    tools=[WebBrowserTools(),DuckDuckGoTools()],
    instructions=[
        "Find related websites and pages using DuckDuckGo"
        "Use web browser to open the site"
    ],
    show_tool_calls=True,
    markdown=True,
)
agent.print_response("Find an article explaining MCP")