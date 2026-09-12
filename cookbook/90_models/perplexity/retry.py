"""Example demonstrating how to set up retries with Perplexity."""

import os

from agno.agent import Agent
from agno.models.openai import OpenAIResponses

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

# We will use a deliberately wrong model ID, to trigger retries.
wrong_model_id = "openai/perplexity-wrong-id"

agent = Agent(
    model=OpenAIResponses(
        id=wrong_model_id,
        base_url="https://api.perplexity.ai/v1",
        api_key=os.environ["PERPLEXITY_API_KEY"],
        retries=3,  # Number of times to retry the request.
        delay_between_retries=1,  # Delay between retries in seconds.
        exponential_backoff=True,  # If True, the delay between retries is doubled each time.
    ),
)

agent.print_response("What is the capital of France?")

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    pass
