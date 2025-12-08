"""Example demonstrating how to use Anthropic beta features.

Beta features are experimental capability extensions for Anthropic models.
You can use them with the `betas` parameter of the Agno Claude model class.
"""

import anthropic
from agno.agent import Agent
from agno.models.anthropic import Claude

# Setup the beta features we want to use
betas = ["context-1m-2025-08-07"]
model = Claude(betas=betas)

# Note: you can see all beta features available in your Anthropic version like this:
all_betas = anthropic.types.AnthropicBetaParam
print("\n=== All available Anthropic beta features ===")
print(f"- {'\n- '.join(all_betas.__args__[1].__args__)}")
print("=============================================\n")

agent = Agent(model=model, debug_mode=True)

# The beta features are now activated, the model will have access to use them.
agent.print_response("What is the weather in Tokyo?")
