from agno.agent import Agent
from agno.tools.googlesearch import GoogleSearchTools

# Example 1: Enable specific Google Search functions
agent = Agent(
    tools=[GoogleSearchTools(enable_google_search=True)],
    description="You are a news agent that helps users find the latest news.",
    instructions=[
        "Given a topic by the user, respond with 4 latest news items about that topic.",
        "Search for 10 news items and select the top 4 unique items.",
        "Search in English and in French.",
    ],
)

# Example 2: Enable all Google Search functions
agent_all = Agent(
    tools=[GoogleSearchTools(all=True)],
    description="You are a comprehensive search agent with all Google Search capabilities.",
    instructions=[
        "Use Google Search to find information on any topic requested by the user.",
        "Provide accurate and up-to-date results.",
    ],
)
agent.print_response("Mistral AI", markdown=True)
