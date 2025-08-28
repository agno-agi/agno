from agno.agent import Agent
from agno.models.huggingface import HuggingFace
from agno.tools.duckduckgo import DuckDuckGoTools

agent = Agent(
    model=HuggingFace(id="openai/gpt-oss-120b"),
    tools=[DuckDuckGoTools()],
    markdown=True,
)
agent.print_response("What is the latest news on AI?")
