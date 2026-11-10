"""
Tool use example with GitHub Copilot.

Prerequisites:
1. Install SDK: pip install github-copilot-sdk
2. Install Copilot CLI (separate installation)
3. Authenticate: copilot auth login

Run: .venvs/demo/bin/python cookbook/90_models/copilot/tool_use.py
"""

from agno.agent import Agent
from agno.models.copilot_sdk import CopilotChat
from agno.tools.hackernews import HackerNewsTools

agent = Agent(
    model=CopilotChat(id="claude-sonnet-4-5"),
    tools=[HackerNewsTools()],
    markdown=True,
)

# Print the response in the terminal
agent.print_response("What are the top 3 stories on HackerNews today?", stream=True)
