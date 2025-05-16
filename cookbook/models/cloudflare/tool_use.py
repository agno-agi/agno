"""Build a Web Search Agent using Cloudflare."""

from agno.agent import Agent
from agno.models.cloudflare import Cloudflare
from agno.tools.duckduckgo import DuckDuckGoTools

agent = Agent(
    model=Cloudflare(id="@cf/meta/llama-3.3-70b-instruct-fp8-fast"),
    tools=[DuckDuckGoTools()],
    show_tool_calls=True,
    markdown=True,
)
agent.print_response("Whats happening in France?", stream=True)
