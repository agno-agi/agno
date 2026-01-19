"""This example shows how to use a custom role map with the OpenAIChat class.

This is useful when using a custom model that doesn't support the default role map.

To run this example:
- Set the MISTRAL_API_KEY environment variable.
- Run `pip install openai agno` to install dependencies.
"""

from os import getenv

from agno.agent import Agent
from agno.models.openai import OpenAIChat

# Using these Mistral model and url as an example.
model_id = "mistral-medium-2505"
base_url = "https://api.mistral.ai/v1"
api_key = getenv("MISTRAL_API_KEY")
mistral_role_map = {
    "system": "system",
    "user": "user",
    "assistant": "assistant",
    "tool": "tool",
    "model": "assistant",
}

# When initializing the model, we pass our custom role map.
model = OpenAIChat(
    id=model_id,
    base_url=base_url,
    api_key=api_key,
    role_map=mistral_role_map,
)

agent = Agent(model=model, markdown=True)

# Running the agent with a custom role map.
res = agent.print_response("Hey, how are you doing?")
