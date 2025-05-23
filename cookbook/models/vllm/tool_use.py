"""Run `pip install duckduckgo-search` to install dependencies."""

from agno.agent import Agent
from agno.models.vllm import Vllm
from agno.tools.duckduckgo import DuckDuckGoTools

# An agent that can decide to invoke the DuckDuckGo search tool.
# Requires the vLLM server to be started with --enable-auto-tool-choice
# and an appropriate --tool-call-parser (see basic.py for server command).

agent = Agent(
    model=Vllm(id="microsoft/Phi-3-mini-4k-instruct"),
    tools=[DuckDuckGoTools()],
    show_tool_calls=True,
    markdown=True,
)

agent.print_response("What's happening in France?")
