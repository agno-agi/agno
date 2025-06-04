"""Build a Web Search Agent using xAI."""

from agno.agent import Agent
from agno.models.vllm import vLLM
from agno.tools.duckduckgo import DuckDuckGoTools

agent = Agent(
    model=vLLM(
        id="NousResearch/Nous-Hermes-2-Mistral-7B-DPO", top_k=20, enable_thinking=False
    ),
    tools=[DuckDuckGoTools()],
    show_tool_calls=True,
    markdown=True,
)
agent.print_response("Whats happening in France?", stream=True)
