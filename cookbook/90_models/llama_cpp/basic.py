"""
Llama Cpp Basic
===============

Cookbook example for `llama_cpp/basic.py`.
"""

from agno.agent import Agent, RunOutput  # noqa
from agno.models.llama_cpp import LlamaCpp

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

agent = Agent(model=LlamaCpp(id="ggml-org/gpt-oss-20b-GGUF"), markdown=True)

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
