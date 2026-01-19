"""Build a Web Search Agent using xAI."""

from agno.agent import Agent
from agno.models.vllm import VLLM
from agno.tools.duckduckgo import DuckDuckGoTools

agent = Agent(
    model=VLLM(
        id="NousResearch/Nous-Hermes-2-Mistral-7B-DPO", top_k=20, enable_thinking=False
    ),
    tools=[DuckDuckGoTools()],
    markdown=True,
)
agent.print_response("Whats happening in France?", stream=True)
