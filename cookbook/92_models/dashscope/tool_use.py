from agno.agent import Agent
from agno.models.dashscope import DashScope
from agno.tools.websearch import WebSearchTools

agent = Agent(
    model=DashScope(id="qwen-plus"),
    tools=[WebSearchTools()],
    markdown=True,
)
agent.print_response("What's happening in AI today?", stream=True)
