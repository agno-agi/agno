from agno.agent import Agent
from agno.tools.exa import ExaTools

agent = Agent(
    tools=[
        ExaTools(
            include_domains=["cnbc.com", "reuters.com", "bloomberg.com"],
            show_results=True,
            text=False,
            highlights=False,
        )
    ],
    show_tool_calls=True,
    markdown=True,
)

agent.print_response("Search for AAPL news", markdown=True)


agent = Agent(
    tools=[
        ExaTools(
            show_results=True,
        )
    ],
    show_tool_calls=True,
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
