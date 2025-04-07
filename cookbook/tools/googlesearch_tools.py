from agno.agent import Agent
from agno.tools.googlesearch import GoogleSearchTools

agent = Agent(
    tools=[GoogleSearchTools()],
    description="You are a news agent that helps users find the latest news.",
    instructions=[
        "Given a topic by the user, respond with 4 latest news items about that topic.",
        "Search for 10 news items and select the top 4 unique items.",
        "Search in English and in French.",
    ],
    show_tool_calls=True,
)
agent.print_response("Mistral AI", markdown=True)
