"""
Output Guardrail
=============================

Output Guardrail.
"""

from agno.agent import Agent
from agno.exceptions import CheckTrigger, OutputCheckError
from agno.models.openai import OpenAIResponses
from agno.run.agent import RunOutput


def enforce_non_empty_output(run_output: RunOutput) -> None:
    """Reject empty or very short responses."""
    content = (run_output.content or "").strip()
    if len(content) < 20:
        raise OutputCheckError(
            "Output is too short to be useful.",
            check_trigger=CheckTrigger.OUTPUT_NOT_ALLOWED,
        )


# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
agent = Agent(
    name="Output-Checked Agent",
    model=OpenAIResponses(id="gpt-5.2"),
    post_hooks=[enforce_non_empty_output],
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    agent.print_response("Summarize the key ideas in clean architecture.", stream=True)
