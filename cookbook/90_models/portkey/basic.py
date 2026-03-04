"""
Portkey Basic
=============

Cookbook example for `portkey/basic.py`.
"""

from agno.agent import Agent, RunOutput  # noqa
from agno.models.portkey import Portkey
import asyncio

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

# Create model using Portkey
model = Portkey(
    id="@first-integrati-707071/gpt-5-nano",
)

agent = Agent(model=model, markdown=True)

# Get the response in a variable
# run: RunOutput = agent.run("What is Portkey and why would I use it as an AI gateway?")
# print(run.content)

# Print the response in the terminal

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # --- Sync ---
    agent.print_response("What is Portkey and why would I use it as an AI gateway?")

    # --- Sync + Streaming ---
    agent.print_response(
        "What is Portkey and why would I use it as an AI gateway?", stream=True
    )

    # --- Async ---
    asyncio.run(
        agent.aprint_response(
            "What is Portkey and why would I use it as an AI gateway?"
        )
    )

    # --- Async + Streaming ---
    asyncio.run(
        agent.aprint_response("Share a breakfast recipe.", markdown=True, stream=True)
    )
