"""Parallel Monitor API — continuous web tracking with scheduled runs.

Setup:
    pip install parallel-web
    export PARALLEL_API_KEY=<your-api-key>
"""

from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.tools.parallel import ParallelTools

agent = Agent(
    model=OpenAIResponses(id="gpt-5.4"),
    tools=[ParallelTools(enable_monitor=True, default_monitor_frequency="6h")],
    markdown=True,
)

# Create a monitor and list all monitors
agent.print_response(
    "Create a monitor to track 'AI startup funding announcements' with 6-hour frequency. "
    "Then list all my active monitors.",
    stream=True,
)


# Uncomment to test monitor management:
# agent.print_response(
#     "List all my monitors. If there are any, get the details of the first one "
#     "and check if it has detected any events.",
#     stream=True,
# )


# Uncomment to test monitor triggering:
# agent.print_response(
#     "List my monitors, then trigger an immediate run on the first active one.",
#     stream=True,
# )


# Uncomment to test monitor updates:
# agent.print_response(
#     "List my monitors. Update the first one to check every 12 hours instead.",
#     stream=True,
# )


# Uncomment to test snapshot monitor (requires a task_run_id):
# task_agent = Agent(
#     model=OpenAIResponses(id="gpt-5.4"),
#     tools=[ParallelTools(enable_task=True, enable_monitor=True)],
#     markdown=True,
# )
# task_agent.print_response(
#     "First create a research task about 'Tesla stock price and recent news'. "
#     "Then create a snapshot monitor to track when that information changes daily.",
#     stream=True,
# )
