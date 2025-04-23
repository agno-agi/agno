from agno.agent import Agent
from agno.tools.serpapi import SerpApiTools

agent = Agent(
    name="SerpApiTools",
    model="gpt-4o",
    description="You are a helpful assistant that can search the web for information.",
    tools=[SerpApiTools()],
    show_tool_calls=True,
)

agent.print_response("Whats happening in the USA?", markdown=True)
