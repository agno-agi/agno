"""
Basic streaming example using GitHub Copilot.

Prerequisites:
1. Install SDK: pip install github-copilot-sdk
2. Install Copilot CLI (separate installation)
3. Authenticate: copilot auth login

Run: .venvs/demo/bin/python cookbook/90_models/copilot/basic_stream.py
"""

from typing import Iterator  # noqa

from agno.agent import Agent, RunOutputEvent  # noqa
from agno.models.copilot_sdk import CopilotChat

agent = Agent(model=CopilotChat(id="claude-sonnet-4-5"), markdown=True)

# Get the response in a variable
# run_response: Iterator[RunOutputEvent] = agent.run("Share a 2 sentence horror story", stream=True)
# for chunk in run_response:
#     print(chunk.content)

# Print the response in the terminal
agent.print_response("Share a 2 sentence horror story", stream=True)
