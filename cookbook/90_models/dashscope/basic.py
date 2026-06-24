"""
Dashscope Basic
===============

Cookbook example for `dashscope/basic.py`.
"""

from agno.agent import Agent, RunOutput  # noqa
from agno.models.dashscope import DashScope
import asyncio

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

agent = Agent(model=DashScope(id="qwen-plus", temperature=0.5), markdown=True)

# Get the response in a variable
# run: RunOutput = agent.run("Share a 2 sentence horror story")
# print(run.content)

# Print the response in the terminal

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # --- Sync ---
    agent.print_response("Share a 2 sentence horror story")

    # --- Sync + Streaming ---
    agent.print_response("Share a 2 sentence horror story", stream=True)

    # --- Async ---
    asyncio.run(agent.aprint_response("Share a 2 sentence horror story"))

    # --- Async + Streaming ---
    async def main():
        # Get the response in a variable
        # async for chunk in agent.arun("Share a 2 sentence horror story", stream=True):
        #     print(chunk.content, end="", flush=True)

        # Print the response in the terminal
        await agent.aprint_response("Share a 2 sentence horror story", stream=True)
