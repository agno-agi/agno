from agno.agent import Agent
from agno.models.huggingface import HuggingFace
from agno.tools.websearch import WebSearchTools

agent = Agent(
    model=HuggingFace(id="openai/gpt-oss-120b"),
    tools=[WebSearchTools()],
    markdown=True,
)
agent.print_response("What is the latest news on AI?")
