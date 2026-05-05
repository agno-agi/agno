"""
Custom Guardrail
=============================

Custom Guardrail.
"""

from agno.agent import Agent
from agno.exceptions import CheckTrigger, InputCheckError
from agno.guardrails.base import BaseGuardrail
from agno.models.openai import OpenAIResponses


class TopicGuardrail(BaseGuardrail):
    """Blocks requests that ask for dangerous instructions."""

    def check(self, run_input) -> None:
        content = (run_input.input_content or "").lower()
        blocked_terms = ["build malware", "phishing template", "exploit"]
        if any(term in content for term in blocked_terms):
            raise InputCheckError(
                "Input contains blocked security-abuse content.",
                check_trigger=CheckTrigger.INPUT_NOT_ALLOWED,
            )

    async def async_check(self, run_input) -> None:
        self.check(run_input)


# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
agent = Agent(
    name="Guarded Agent",
    model=OpenAIResponses(id="gpt-5.2"),
    pre_hooks=[TopicGuardrail()],
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    agent.print_response(
        "Explain secure password management best practices.", stream=True
    )
