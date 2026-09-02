"""
Async streaming example using GitHub Copilot.

Prerequisites:
1. Install SDK: pip install github-copilot-sdk
2. Install Copilot CLI (separate installation)
3. Authenticate: copilot auth login

Run: .venvs/demo/bin/python cookbook/90_models/copilot/async_basic_stream.py
"""

import asyncio

from agno.agent import Agent
from agno.models.copilot_sdk import CopilotChat

agent = Agent(
    model=CopilotChat(id="claude-sonnet-4-5"),
    markdown=True,
)

asyncio.run(agent.aprint_response("Share a 2 sentence horror story", stream=True))
