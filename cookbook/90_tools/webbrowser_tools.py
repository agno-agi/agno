from agno.agent import Agent
from agno.models.google import Gemini
from agno.tools.duckduckgo import DuckDuckGoTools
from agno.tools.webbrowser import WebBrowserTools

# Example 1: Enable specific WebBrowser functions
agent = Agent(
    model=Gemini("gemini-2.0-flash"),
    tools=[WebBrowserTools(enable_open_page=True), DuckDuckGoTools(all=True)],
    instructions=[
        "Find related websites and pages using DuckDuckGo",
        "Use web browser to open the site",
    ],
    markdown=True,
)

# Example 2: Enable all WebBrowser functions
agent_all = Agent(
    model=Gemini("gemini-2.0-flash"),
    tools=[WebBrowserTools(all=True), DuckDuckGoTools(all=True)],
    instructions=[
        "Find related websites and pages using DuckDuckGo",
        "Use web browser to open the site with full functionality",
    ],
    markdown=True,
)
agent.print_response("Find an article explaining MCP and open it in the web browser.")
