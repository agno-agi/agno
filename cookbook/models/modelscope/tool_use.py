"""Run `pip install duckduckgo-search` to install dependencies."""

from agno.agent import Agent
from agno.models.modelscope import ModelScope
from agno.tools.duckduckgo import DuckDuckGoTools

agent = Agent(
    model=ModelScope(id="Qwen/Qwen2.5-72B-Instruct"),
    description="You are an enthusiastic news reporter with a flair for storytelling!",
    tools=[DuckDuckGoTools()],
    show_tool_calls=True,
    markdown=True,
    debug_mode=True,
)

agent.print_response("Tell me about a breaking news story from New York.", stream=True)
