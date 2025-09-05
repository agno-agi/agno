from agno.agent import Agent
from agno.tools.tavily import TavilyTools

# Example 1: default TavilyTools
agent = Agent(tools=[TavilyTools()])

# Example 2: Enable all Tavily functions
agent_all = Agent(tools=[TavilyTools(all=True)])

# Example 3: Use advanced search with context
context_agent = Agent(
    tools=[
        TavilyTools(
            enable_web_search_using_tavily=False,
            enable_web_search_with_tavily=True,
        )
    ]
)

# Test the agents
agent.print_response(
    "Search for 'language models' and recent developments", markdown=True
)
context_agent.print_response(
    "Get detailed context about artificial intelligence trends", markdown=True
)
