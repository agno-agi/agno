"""Parallel Tools — web search, extraction, deep research, and monitoring.

Setup:
    pip install parallel-web
    export PARALLEL_API_KEY=<your-api-key>
"""

from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.tools.parallel import ParallelTools

# Search & Extract (default tools)
agent = Agent(
    model=OpenAIResponses(id="gpt-5.4"),
    tools=[ParallelTools()],
    markdown=True,
)

agent.print_response("What are the latest developments in AI agents?", stream=True)


# Uncomment to test Task API (deep research):
# task_agent = Agent(
#     model=OpenAIResponses(id="gpt-5.4"),
#     tools=[ParallelTools(enable_task=True)],
#     markdown=True,
# )
# task_agent.print_response(
#     "Research the current valuation and recent funding of Anthropic. "
#     "Include sources and confidence for each claim.",
#     stream=True,
# )


# Uncomment to test Monitor API (web tracking):
# monitor_agent = Agent(
#     model=OpenAIResponses(id="gpt-5.4"),
#     tools=[ParallelTools(enable_monitor=True)],
#     markdown=True,
# )
# monitor_agent.print_response(
#     "Create a monitor to track news about 'AI regulation in the EU' "
#     "with daily frequency. Then list all my active monitors.",
#     stream=True,
# )
