"""
An example of how to use the thinking budget parameter with the Gemini model.
This requires `google-genai > 1.10.0`

- Turn off thinking use thinking_budget=0
- Turn on dynamic thinking use thinking_budget=-1
- To use a specific thinking token budget (e.g. 1280) use thinking_budget=1280
- Use include_thoughts=True to get the thought summaries in the response.
"""

from agno.agent import Agent
from agno.models.google import Gemini

task = (
    "Three missionaries and three cannibals need to cross a river. "
    "They have a boat that can carry up to two people at a time. "
    "If, at any time, the cannibals outnumber the missionaries on either side of the river, the cannibals will eat the missionaries. "
    "How can all six people get across the river safely? Provide a step-by-step solution and show the solutions as an ascii diagram"
)

agent = Agent(
    model=Gemini(id="gemini-2.5-pro", thinking_budget=1280, include_thoughts=True),
    markdown=True,
)
agent.print_response(task, stream=True)
