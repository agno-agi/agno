from agno.agent import Agent
from agno.models.vllm import Vllm
from agno.tools.duckduckgo import DuckDuckGoTools

model = Vllm(
    id="microsoft/Phi-3-mini-4k-instruct",  # must match what the server loaded
    base_url="http://localhost:8000/v1",  # default, override if needed
    api_key="dummy",  # vLLM ignores it but OpenAI-style client expects a value
)

agent = Agent(
    model=model,
    tools=[DuckDuckGoTools()],
    show_tool_calls=True,
    markdown=True,
)

agent.print_response("Give me a short haiku about sunsets.")
