from agno.agent import Agent
from agno.models.dashscope import DashScope
from agno.tools.duckduckgo import DuckDuckGoTools

agent = Agent(
    model=DashScope(id="qwen-plus"),
    tools=[DuckDuckGoTools()],
    show_tool_calls=True,
    markdown=True,
)
agent.print_response("What's happening in AI today?", stream=True)
