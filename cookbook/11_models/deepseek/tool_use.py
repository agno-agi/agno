"""Run `pip install ddgs` to install dependencies."""

from agno.agent import Agent
from agno.models.deepseek import DeepSeek
from agno.tools.duckduckgo import DuckDuckGoTools

"""
The current version of the deepseek-chat model's Function Calling capabilitity is unstable, which may result in looped calls or empty responses.
Their development team is actively working on a fix, and it is expected to be resolved in the next version.
"""

agent = Agent(
    model=DeepSeek(id="deepseek-chat"),
    tools=[DuckDuckGoTools()],
    markdown=True,
)

agent.print_response("Whats happening in France?")
