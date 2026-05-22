"""Parallel Research Thesis Tracking — monitor evidence for investment thesis.

Setup:
    pip install parallel-web
    export PARALLEL_API_KEY=<your-api-key>
"""

from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.tools.parallel import ParallelTools

# Research thesis agent with deep research and continuous monitoring
agent = Agent(
    model=OpenAIResponses(id="gpt-5.4"),
    tools=[
        ParallelTools(
            enable_search=True,
            enable_task=True,
            enable_monitor=True,
            default_processor="pro",
            default_monitor_frequency="1d",
        )
    ],
    markdown=True,
    instructions=[
        "You are a research analyst tracking an investment thesis.",
        "Set up monitors for both supporting evidence and contradicting signals.",
        "Use deep research for initial thesis validation.",
    ],
)

# Build and monitor a thesis on AI infrastructure
agent.print_response(
    "I have a thesis: 'AI inference costs will drop 10x in the next 2 years, "
    "making AI agents economically viable for SMBs.' "
    "First, do deep research to validate this thesis with current data. "
    "Then create monitors to track: "
    "1. 'AI inference cost reduction announcements' (supporting) "
    "2. 'GPU shortage supply chain issues' (contradicting) "
    "3. 'SMB AI agent adoption case studies' (market validation)",
    stream=True,
)


# Uncomment for crypto thesis tracking:
# agent.print_response(
#     "Thesis: 'Layer 2 solutions will capture 80% of Ethereum transaction volume by 2027.' "
#     "Research current L2 adoption metrics and set up monitors for: "
#     "1. 'Arbitrum Optimism Base transaction volume growth' "
#     "2. 'Ethereum mainnet congestion gas fees' "
#     "3. 'L2 bridge security incidents' (risk signal)",
#     stream=True,
# )


# Uncomment for market structure thesis:
# agent.print_response(
#     "Thesis: 'Vertical AI agents will outperform horizontal platforms in enterprise sales.' "
#     "Research examples of vertical vs horizontal AI success in enterprises. "
#     "Then monitor for: "
#     "1. 'Enterprise AI agent deployment case studies' "
#     "2. 'Vertical SaaS AI integration announcements'",
#     stream=True,
# )
