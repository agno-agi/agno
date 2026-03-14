"""PIIDetectionGuardrail on_fail callback - custom PII handling."""

from typing import Any, Dict

from agno.agent import Agent
from agno.exceptions import InputCheckError
from agno.guardrails import PIIDetectionGuardrail
from agno.models.openai import OpenAIChat

pii_incidents: list[Dict[str, Any]] = []


def log_pii_incident(
    error: Exception, input_data: Any, context: Dict[str, Any]
) -> None:
    """Log PII incidents for compliance reporting."""
    pii_incidents.append(
        {
            "guardrail": context.get("guardrail_name"),
            "check_type": context.get("check_type"),
        }
    )


agent = Agent(
    model=OpenAIChat(id="gpt-4o-mini"),
    pre_hooks=[PIIDetectionGuardrail(on_fail=log_pii_incident)],
)

try:
    agent.print_response("My SSN is 123-45-6789")
except InputCheckError:
    print(f"PII incidents: {len(pii_incidents)}")
