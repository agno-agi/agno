"""
Speko Basic
===========

Cookbook example for `speko/basic.py`.

Speko is a voice router with an OpenAI-compatible chat completions endpoint.
id="auto" (the default) routes each request to the best available LLM by live
benchmarks; any routable "provider:model" ID can be pinned instead, e.g.
Speko(id="openai:gpt-4.1-mini"). Requires the SPEKO_API_KEY environment variable.
"""

from agno.agent import Agent, RunOutput  # noqa
from agno.models.speko import Speko
import asyncio

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

agent = Agent(model=Speko(id="auto"), markdown=True)

# The string syntax works too, and pinned IDs keep their provider prefix:
# agent = Agent(model="speko:auto", markdown=True)
# agent = Agent(model="speko:openai:gpt-4.1-mini", markdown=True)

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
    asyncio.run(agent.aprint_response("Share a 2 sentence horror story", stream=True))
