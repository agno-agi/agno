"""
Basic Agent - Your First Gemini Agent
=======================================
Simple Agno agent with Gemini 3 Flash.

Key concepts:
- Agent: The core building block in Agno wraps a model with instructions
- print_response: Runs the agent and prints formatted output
- stream=True: Streams tokens as they arrive instead of waiting for the full response
- Sync vs async: Every Agno method has an async variant (aprint_response, arun, etc.)

Example prompts to try:
- "What are the top 3 things to see in Paris?"
- "Explain quantum computing in simple terms"
- "Write a haiku about programming"
"""

import asyncio

from agno.agent import Agent
from agno.models.google import Gemini

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
chat_agent = Agent(
    name="Chat Assistant",
    model=Gemini(id="gemini-3-flash-preview"),
    # markdown=True renders rich formatting in the terminal
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # --- Sync ---
    # chat_agent.print_response("What are the top 3 things to see in Paris?")

    # --- Sync + Streaming ---
    # chat_agent.print_response(
    #     "What are the top 3 things to see in Paris?", stream=True
    # )

    # --- Async ---
    # asyncio.run(
    #     chat_agent.aprint_response("What are the top 3 things to see in Paris?")
    # )

    # --- Async + Streaming ---
    asyncio.run(
        chat_agent.aprint_response(
            "What are the top 3 things to see in Paris?", stream=True
        )
    )

# ---------------------------------------------------------------------------
# More Examples
# ---------------------------------------------------------------------------
"""
Agno supports four execution modes for every agent:

1. Sync (blocking)
   agent.print_response("prompt")
   response = agent.run("prompt")

2. Sync + Streaming (tokens arrive as they're generated)
   agent.print_response("prompt", stream=True)
   for chunk in agent.run("prompt", stream=True):
       print(chunk.content, end="")

3. Async (non-blocking)
   await agent.aprint_response("prompt")
   response = await agent.arun("prompt")

4. Async + Streaming
   await agent.aprint_response("prompt", stream=True)
   async for chunk in await agent.arun("prompt", stream=True):
       print(chunk.content, end="")

All examples in this guide use sync for simplicity.
For production apps, use async (see cookbook/02_agents/ for patterns).
"""
