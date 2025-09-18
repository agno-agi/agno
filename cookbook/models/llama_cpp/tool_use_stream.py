"""Run `pip install ddgs` to install dependencies."""

from agno.agent import Agent
from agno.models.llama_cpp import LlamaCpp
from agno.tools.duckduckgo import DuckDuckGoTools

agent = Agent(
    model=LlamaCpp(id="ggml-org/gpt-oss-20b-GGUF"),
    tools=[DuckDuckGoTools()],
    markdown=True,
)
agent.print_response("Whats happening in France?", stream=True)
