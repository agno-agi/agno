from agno.agent import Agent, RunOutput  # noqa
from agno.models.cerebras import Cerebras

"""
This example demonstrates how it works when you pass a non-reasoning model as a reasoning model.
It defaults to using the default OpenAI reasoning model.
We recommend using the appropriate reasoning model or passing reasoning=True for the default COT.
"""

reasoning_agent = Agent(
    model=Cerebras(id="llama-3.3-70b"),
    reasoning=True,
    debug_mode=True,
    markdown=True,
)
reasoning_agent.print_response(
    "Give me steps to write a python script for fibonacci series",
    stream=True,
    show_full_reasoning=True,
)
