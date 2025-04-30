"""Run `pip install duckduckgo-search` to install dependencies."""

from agno.agent import Agent
from agno.models.meta import LlamaOpenAI
from agno.tools.duckduckgo import DuckDuckGoTools

agent = Agent(
    model=LlamaOpenAI(id="Llama-4-Maverick-17B-128E-Instruct-FP8"),
    tools=[DuckDuckGoTools()],
    show_tool_calls=True,
)
agent.print_response("Whats happening in France?")
