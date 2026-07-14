"""Example demonstrating how to set up retries with DaoXE."""

import os

from agno.agent import Agent
from agno.models.daoxe import DaoXE

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

# Deliberately wrong model ID to trigger retries.
wrong_model_id = os.environ.get("DAOXE_MODEL_WRONG", "daoxe-wrong-id")

agent = Agent(
    model=DaoXE(
        id=wrong_model_id,
        retries=3,
        delay_between_retries=1,
        exponential_backoff=True,
    ),
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    agent.print_response("What is the capital of France?")
