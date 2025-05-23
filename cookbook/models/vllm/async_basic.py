"""
     python -m vllm.entrypoints.openai.api_server \
         --model microsoft/Phi-3-mini-4k-instruct \
         --dtype float32          # CPU-only OK
         # --port 8000 (8000 is default)
"""

import asyncio

from agno.agent import Agent, RunResponse  # noqa
from agno.models.vllm import Vllm

"""Asynchronous basic example using vLLM.

Prerequisites: run a vLLM server (see README).
"""

agent = Agent(model=Vllm(id="microsoft/Phi-3-mini-4k-instruct"), markdown=True)

# Get the response in a variable (non-streaming)
# run: RunResponse = agent.run("Share a 2 sentence horror story")
# print(run.content)

# Print the response in the terminal
asyncio.run(agent.aprint_response("Share a 2 sentence horror story"))
