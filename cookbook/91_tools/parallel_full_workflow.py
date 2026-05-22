"""Parallel Full Workflow — combining Task and Monitor APIs for research automation.

Setup:
    pip install parallel-web
    export PARALLEL_API_KEY=<your-api-key>
"""

from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.tools.parallel import ParallelTools

# Enable all Parallel APIs for a research automation workflow
agent = Agent(
    model=OpenAIResponses(id="gpt-5.4"),
    tools=[
        ParallelTools(
            enable_search=True,
            enable_extract=True,
            enable_task=True,
            enable_monitor=True,
        )
    ],
    markdown=True,
)

# Research + monitoring workflow: research a topic, then set up tracking
agent.print_response(
    "I want to track developments in AI regulation. "
    "First, do a quick search to understand the current state. "
    "Then create a daily monitor to track new announcements about 'AI regulation laws'.",
    stream=True,
)


# Uncomment for competitive intelligence workflow:
# agent.print_response(
#     "Research the top 3 AI agent frameworks (LangChain, CrewAI, Agno). "
#     "For each, find: GitHub stars, latest release date, key features. "
#     "Then set up monitors to track news about each of them.",
#     stream=True,
# )


# Uncomment for investment research workflow:
# agent.print_response(
#     "Research Anthropic's funding history, current valuation, and recent news. "
#     "Extract detailed information from their official blog. "
#     "Then create a monitor to track future announcements.",
#     stream=True,
# )
