"""
This example demonstrates how it works when you pass a non-reasoning model to the reasoning model.
We recommend using the appropriate reasoning model or passing reasoning=True for the default reasoning model.
"""

from agno.agent import Agent
from agno.models.openai import OpenAIChat

task = "Give me steps to write a python script for fibonacci series"

reasoning_agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    reasoning_model=OpenAIChat(id="gpt-4o"),
    reasoning=True,
    markdown=True,
)
reasoning_agent.print_response(task, stream=True, show_full_reasoning=True)
