"""Example demonstrating how to use Anthropic beta features.

Beta features are experimental capability extensions for Anthropic models.
You can use them with the `betas` parameter of the Agno Claude model class.
"""

import anthropic
from agno.agent import Agent
from agno.models.anthropic import Claude

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
# Setup the beta features we want to use
betas = ["context-1m-2025-08-07"]
model = Claude(betas=betas)

# Note: you can see all beta features available in your Anthropic version like this:
all_betas = anthropic.types.AnthropicBetaParam
agent = Agent(model=model, debug_mode=True)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
# The beta features are now activated, the model will have access to use them.
if __name__ == "__main__":
    print("\n=== All available Anthropic beta features ===")
    beta_lines = "\n- ".join(str(b) for b in all_betas.__args__[1].__args__)
    print(f"- {beta_lines}")
    print("=============================================\n")

    agent.print_response("What is the weather in Tokyo?")
