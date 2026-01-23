"""
Basic GitHub Copilot example.

Prerequisites:
1. Install SDK: pip install github-copilot-sdk
2. Install Copilot CLI (separate installation)
3. Authenticate: copilot auth login

Run: .venvs/demo/bin/python cookbook/90_models/copilot/basic.py
"""

from agno.agent import Agent
from agno.models.copilot_sdk import CopilotChat
from agno.tools.hackernews import HackerNewsTools

agent = Agent(
    model=CopilotChat(id="claude-sonnet-4.5"),
    tools=[HackerNewsTools()],
    markdown=True,
    debug_mode=True,
    debug_level=2,
)

# Print the response in the terminal
agent.print_response("What are 3 trending stories in AI this month?")
