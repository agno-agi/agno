"""Run `pip install ddgs` to install dependencies."""

from agno.agent import Agent  # noqa
from agno.models.deepinfra import DeepInfra  # noqa
from agno.tools.duckduckgo import DuckDuckGoTools  # noqa

agent = Agent(
    model=DeepInfra(id="meta-llama/Llama-2-70b-chat-hf"),
    tools=[DuckDuckGoTools()],
    markdown=True,
)

agent.print_response("Whats happening in France?", stream=True)
