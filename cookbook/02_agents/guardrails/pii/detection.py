"""PIIDetectionGuardrail - blocks messages containing PII."""

from agno.agent import Agent
from agno.exceptions import InputCheckError
from agno.guardrails import PIIDetectionGuardrail
from agno.models.openai import OpenAIChat

agent = Agent(
    model=OpenAIChat(id="gpt-4o-mini"),
    pre_hooks=[PIIDetectionGuardrail()],  # Default: block strategy
)

if __name__ == "__main__":
    # Normal request - passes
    agent.print_response("What is the return policy?")

    # Request with SSN - blocked
    try:
        agent.print_response("My SSN is 123-45-6789")
    except InputCheckError as e:
        print(f"Blocked: {e.message}")
