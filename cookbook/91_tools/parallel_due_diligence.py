"""Parallel Due Diligence — investment research with citations.

Setup:
    pip install parallel-web
    export PARALLEL_API_KEY=<your-api-key>
"""

from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.tools.parallel import ParallelTools

# Due diligence agent using deep research with pro processor for citations
agent = Agent(
    model=OpenAIResponses(id="gpt-5.4"),
    tools=[
        ParallelTools(
            enable_search=True,
            enable_task=True,
            default_processor="pro",
        )
    ],
    markdown=True,
    instructions=[
        "You are an investment research analyst conducting due diligence.",
        "Always use deep research (run_task) for comprehensive analysis.",
        "Include risk factors, competitive positioning, and growth indicators.",
        "Cite your sources for every claim.",
    ],
)

# Startup due diligence
agent.print_response(
    "Conduct due diligence on Anthropic. Research: "
    "1. Funding history and current valuation "
    "2. Key investors and board members "
    "3. Main products and revenue model "
    "4. Top 5 risk factors "
    "5. Competitive positioning vs OpenAI and Google DeepMind",
    stream=True,
)


# Uncomment for market opportunity analysis:
# agent.print_response(
#     "Analyze the AI agent infrastructure market opportunity. Research: "
#     "Total addressable market size and growth projections, "
#     "key players and their funding, "
#     "emerging trends and investment activity in 2025-2026.",
#     stream=True,
# )


# Uncomment for company comparison:
# agent.print_response(
#     "Compare Databricks vs Snowflake for a growth equity investment. "
#     "Analyze: revenue growth, customer metrics, product differentiation, "
#     "market position, and key risks for each.",
#     stream=True,
# )
