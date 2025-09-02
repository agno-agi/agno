from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.tools.duckduckgo import DuckDuckGoTools

agent = Agent(
    model=OpenAIChat(id="gpt-4.1"),
    tools=[DuckDuckGoTools()],
    show_tool_calls=True,
)

agent.print_response("Whats the latest about gpt 5?", markdown=True)
