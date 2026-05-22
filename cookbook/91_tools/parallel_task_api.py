"""Parallel Task API — deep research with structured output and citations.

Setup:
    pip install parallel-web
    export PARALLEL_API_KEY=<your-api-key>
"""

from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.tools.parallel import ParallelTools

agent = Agent(
    model=OpenAIResponses(id="gpt-5.4"),
    tools=[ParallelTools(enable_task=True, default_processor="standard")],
    markdown=True,
)

# Deep research task — agent will use run_task to get structured results with citations
agent.print_response(
    "Research the current state of quantum computing. "
    "Find the leading companies, their latest achievements, and funding amounts. "
    "Provide sources for each claim.",
    stream=True,
)


# Uncomment to test async task creation and status checking:
# agent.print_response(
#     "Create a research task about 'electric vehicle battery technology trends in 2026' "
#     "without waiting for results. Then check its status.",
#     stream=True,
# )


# Uncomment to test company research:
# agent.print_response(
#     "Research OpenAI: founding date, current CEO, latest valuation, "
#     "major product releases in 2025-2026, and key partnerships.",
#     stream=True,
# )


# Uncomment to test market research:
# agent.print_response(
#     "Research the AI agent framework market. "
#     "Who are the main players? What are the pricing models? "
#     "Which frameworks have the most GitHub stars?",
#     stream=True,
# )
