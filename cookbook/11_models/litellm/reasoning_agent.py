"""
LiteLLM Reasoning Agent Example

This example demonstrates using reasoning models through LiteLLM.
The reasoning_content from the model response is extracted and displayed.

Supported reasoning models through LiteLLM:
- deepseek/deepseek-reasoner (DeepSeek R1)
"""

from agno.agent import Agent
from agno.models.litellm import LiteLLM

task = "9.11 and 9.9 -- which is bigger?"

# Using DeepSeek R1 through LiteLLM
agent = Agent(
    model=LiteLLM(
        id="deepseek/deepseek-reasoner",
    ),
    markdown=True,
)

agent.print_response(task, stream=True, stream_events=True, show_reasoning=True)
