from agno.agent import Agent
from agno.tools.bravesearch import BraveSearchTools

agent = Agent(
    tools=[BraveSearchTools()],
    description="You are a news agent that helps users find the latest news.",
    instructions=[
        "Given a topic by the user, respond with 4 latest news items about that topic."
    ],
    show_tool_calls=True,
)
agent.print_response("AI Agents", markdown=True)
