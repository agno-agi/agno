"""Parallel Tools — web search, deep research, and monitoring.

Setup:
    pip install parallel-web
    export PARALLEL_API_KEY=<your-api-key>

APIs:
    - Search: Find relevant web content with natural language
    - Extract: Pull content from specific URLs
    - Task: Deep research with citations (enable_task=True)
    - Monitor: Track topics over time (enable_monitor=True)
"""

from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.tools.parallel import ParallelTools

# Basic search agent (default — Search & Extract enabled)
agent = Agent(
    model=OpenAIResponses(id="gpt-5.4"),
    tools=[ParallelTools()],
    markdown=True,
)

agent.print_response("What are the latest developments in AI agents?", stream=True)
