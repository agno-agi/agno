"""Example demonstrating how to use Anthropic beta features.

Beta features are experimental capability extensions for Anthropic models.
You can use them with the `betas` parameter of the Agno Claude model class.
"""

import anthropic
from agno.agent import Agent
from agno.models.vertexai.claude import Claude

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
# Setup the beta features we want to use
betas = ["context-management-2025-06-27"]
model = Claude(id="claude-sonnet-4@20250514", betas=betas)

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

    print(
        "Note: Not all beta features are available across all inference providers. Read more here: https://platform.claude.com/docs/en/api/overview"
    )

    agent.print_response(
        "My name is John Doe and I live in New York City. I like to bike and hike in the Catskill Mountains."
    )
