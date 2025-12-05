"""Example demonstrating how to set up retries with Together."""

from agno.agent import Agent
from agno.models.together import Together

# We will use a deliberately wrong model ID, to trigger retries.
wrong_model_id = "together-wrong-id"

agent = Agent(
    model=Together(
        id=wrong_model_id,
        retries=3,  # Number of times to retry the request.
        delay_between_retries=1,  # Delay between retries in seconds.
        exponential_backoff=True,  # If True, the delay between retries is doubled each time.
    ),
)

agent.print_response("What is the capital of France?")
