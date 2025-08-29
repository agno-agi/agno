"""
Run this cookbook twice to see the difference in response time.

The first time should take a while to run.

The second time should be instant.
"""

from agno.agent.agent import Agent
from agno.models.openai.chat import OpenAIChat

agent = Agent(
    model=OpenAIChat(id="o3-mini"), cache_model_response=True, debug_mode=True
)

# Should take a while to run the first time, then replay from cache
agent.print_response(
    "Write me a short story about a cat that can talk and solve problems.", stream=True
)
