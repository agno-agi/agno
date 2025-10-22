"""
Example showing how to cache model responses to avoid redundant API calls.

Run this cookbook twice to see the difference in response time.

The first time should take a while to run.
The second time should be instant.
"""

from agno.agent import Agent
from agno.models.openai import OpenAIChat

agent = Agent(
    model=OpenAIChat(id="gpt-4o", cache_response=True)
)

# Should take a while to run the first time, then replay from cache
agent.print_response(
    "Write me a short story about a cat that can talk and solve problems."
)
