"""Demo server entrypoint for CopilotKit backend.

Run with:
    uvicorn agno.app.copilotkit.demo:app --reload
"""

import logging
import sys

# Enable debug-level logging to see backend traces
logging.basicConfig(stream=sys.stdout, level=logging.DEBUG)

from agno.agent.agent import Agent
from agno.app.copilotkit.app import CopilotKitApp
from agno.models.openai.chat import OpenAIChat


class GPTAgent(Agent):
    def __init__(self):
        super().__init__(
            model=OpenAIChat(id="gpt-4o"),
            description="You are a helpful AI assistant named Agno.",
            instructions="You are a helpful conversational agent. You are given a conversation history and a new message. You need to respond to the new message based on the conversation history.",
            stream=True,
        )


# Create FastAPI app instance
app = CopilotKitApp(agent=GPTAgent()).get_app(use_async=False)
