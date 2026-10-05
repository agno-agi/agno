"""
Async tool use example with GitHub Copilot.

Prerequisites:
1. Install SDK: pip install github-copilot-sdk
2. Install Copilot CLI (separate installation)
3. Authenticate: copilot auth login

Run: .venvs/demo/bin/python cookbook/90_models/copilot/async_tool_use.py
"""

import asyncio

from agno.agent import Agent
from agno.models.copilot_sdk import CopilotChat
from agno.tools.websearch import WebSearchTools

agent = Agent(
    model=CopilotChat(id="claude-sonnet-4-5"),
    tools=[WebSearchTools()],
    markdown=True,
)

asyncio.run(agent.aprint_response("Whats happening in France?", stream=True))
