from agno.agent import Agent
from agno.tools.bravesearch import BraveSearchTools

# Example 1: Enable specific Brave Search functions
agent = Agent(
    tools=[BraveSearchTools(enable_brave_search=True)],
    description="You are a news agent that helps users find the latest news.",
    instructions=[
        "Given a topic by the user, respond with 4 latest news items about that topic."
    ],
)

# Example 2: Enable all Brave Search functions
agent_all = Agent(
    tools=[BraveSearchTools(all=True)],
    description="You are a comprehensive search agent with full Brave Search capabilities.",
    instructions=[
        "Use Brave Search to find accurate, privacy-focused search results.",
        "Provide relevant and up-to-date information on any topic.",
    ],
)
agent.print_response("AI Agents", markdown=True)
