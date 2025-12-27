"""Example demonstrating how to set up retries with Google Gemini."""

from agno.agent import Agent
from agno.models.google import Gemini

# We will use a deliberately wrong model ID, to trigger retries.
wrong_model_id = "gemini-wrong-id"

agent = Agent(
    model=Gemini(
        id=wrong_model_id,
        retries=3,  # Number of times to retry the request.
        delay_between_retries=1,  # Delay between retries in seconds.
        exponential_backoff=True,  # If True, the delay between retries is doubled each time.
    ),
)

agent.print_response("What is the capital of France?")
