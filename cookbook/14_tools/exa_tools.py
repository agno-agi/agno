from agno.agent import Agent
from agno.tools.exa import ExaTools

# Example 1: Enable all tools
agent_all = Agent(
    tools=[
        ExaTools(
            all=True,  # Enable all exa tools
            show_results=True,
        )
    ],
    markdown=True,
)

# Example 2: Enable specific tools only
agent_specific = Agent(
    tools=[
        ExaTools(
            enable_search=True,
            enable_answer=True,
            enable_get_contents=False,
            enable_find_similar=False,
            enable_research=False,
            include_domains=["cnbc.com", "reuters.com", "bloomberg.com"],
            show_results=True,
            text=False,
        )
    ],
    markdown=True,
)

# Example 3: Default behavior (most functions enabled by default)
agent = Agent(
    tools=[
        ExaTools(
            include_domains=["cnbc.com", "reuters.com", "bloomberg.com"],
            show_results=True,
            text=False,
        )
    ],
    markdown=True,
)

agent.print_response("Search for AAPL news", markdown=True)


agent = Agent(
    tools=[
        ExaTools(
            show_results=True,
        )
    ],
    markdown=True,
)

agent.print_response("Search for AAPL news", markdown=True)

agent.print_response(
    "What is the paper at https://arxiv.org/pdf/2307.06435 about?", markdown=True
)

agent.print_response(
    "Find me similar papers to https://arxiv.org/pdf/2307.06435 and provide a summary of what they contain",
    markdown=True,
)

agent.print_response(
    "What is the latest valuation of SpaceX?",
    markdown=True,
)
