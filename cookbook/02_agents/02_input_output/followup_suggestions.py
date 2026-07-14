"""
Followups (Built-in)
====================

Enable built-in followup prompts on any agent with a single flag.

After the main response, the agent automatically makes a second model call
to generate structured followup prompts and attaches them to RunOutput.

Key concepts:
- followups=True: enables the feature
- num_followups: controls how many suggestions (default 3)
- followup_model: optional cheaper model for generating followups
- run_response.followups: the structured result

The main response is never constrained — it streams freely as normal text.

Example prompts to try:
- "Which national park is the best?"
- "What programming language should I learn first?"
- "How do I start investing?"
"""

from agno.agent import Agent, RunOutput
from agno.models.openai import OpenAIResponses

# ---------------------------------------------------------------------------
# Create the Agent — just set followups=True
# ---------------------------------------------------------------------------
agent = Agent(
    model=OpenAIResponses(id="gpt-4o"),
    instructions="You are a knowledgeable assistant. Answer questions thoroughly.",
    # Enable built-in followups
    followups=True,
    num_followups=3,
    # Optionally use a cheaper model for followups
    # followup_model=OpenAIResponses(id="gpt-4o-mini"),
    markdown=True,
)


# ---------------------------------------------------------------------------
# Run the Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    run: RunOutput = agent.run("Which national park is the best?")

    # The main response — full free-form text
    print(f"\n{'=' * 60}")
    print("Response:")
    print(f"{'=' * 60}")
    print(run.content)

    # Followups — structured, attached to RunOutput
    print(f"\n{'=' * 60}")
    print("Followups:")
    print(f"{'=' * 60}")
    if run.followups:
        for i, suggestion in enumerate(run.followups, 1):
            print(f"  {i}. {suggestion}")
    else:
        print("  No followups generated.")

    print()
