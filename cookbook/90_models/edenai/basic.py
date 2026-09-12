"""
Eden AI Basic
=============

Cookbook example for `edenai/basic.py`.

Set your Eden AI key first (grab it from https://app.edenai.run/admin/api-settings/features-preferences):

    export EDENAI_API_KEY="***"

Eden AI addresses models as "<provider>/<model>", e.g. "openai/gpt-4o-mini".
"""

import asyncio

from agno.agent import Agent
from agno.models.edenai import EdenAI

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

# Using the model class
agent = Agent(
    model=EdenAI(id="openai/gpt-5.5"),
    markdown=True,
)

# Equivalent using the string syntax:
# agent = Agent(model="edenai:openai/gpt-5.5", markdown=True)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # --- Sync ---
    agent.print_response("write a two sentence horror story")

    # --- Sync + Streaming ---
    agent.print_response("write a two sentence horror story", stream=True)

    # --- Async ---
    asyncio.run(agent.aprint_response("write a two sentence horror story"))

    # --- Async + Streaming ---
    asyncio.run(agent.aprint_response("write a two sentence horror story", stream=True))
