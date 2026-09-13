"""
Escalation: Small Primary, Large Advisors
=========================================
A common pattern: run a small, fast, cheap model as the primary agent and
let it escalate hard sub-problems to larger models.

Advisors can be defined as model strings ("provider:model-id") instead of
Model instances. They are resolved via `agno.models.utils.get_model`, so you
do not need to import each model class.

Benefits:
- Most turns are handled by the cheap model
- The agent only pays for the large models when it actually needs them
- Descriptions steer which advisor gets which kind of question
"""

from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.tools.advisor import AdvisorTools

# ---------------------------------------------------------------------------
# Create Agent: small primary model, large advisors via model strings
# ---------------------------------------------------------------------------

agent = Agent(
    model=OpenAIResponses(id="gpt-5-mini"),
    tools=[
        AdvisorTools(
            advisors=["anthropic:claude-sonnet-4-6", "openai:gpt-5.5"],
            descriptions={
                "claude-sonnet-4-6": "Escalate tricky code and correctness questions here",
                "gpt-5.5": "Escalate open-ended reasoning and planning questions here",
            },
        )
    ],
    instructions=[
        "You are a fast assistant. Handle easy questions yourself.",
        "When a question is hard or high-stakes, escalate it to the most suitable advisor.",
        "Always give the advisor a self-contained prompt with the relevant context.",
    ],
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    agent.print_response(
        "Write a Python function that merges overlapping intervals. "
        "Before finalizing, get your implementation reviewed by an advisor "
        "and incorporate any corrections.",
        stream=True,
    )
