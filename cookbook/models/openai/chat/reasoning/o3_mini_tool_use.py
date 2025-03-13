from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.tools.duckduckgo import DuckDuckGoTools

agent = Agent(
    model=OpenAIChat(id="o3-mini"),
    tools=[DuckDuckGoTools()],
    show_tool_calls=True,
    markdown=True,
)

# Print the response in the terminal
agent.print_response("Write a report on the latest news on o3-mini?", stream=True)
