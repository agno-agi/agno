"""OpenAIModerationGuardrail on_fail callback - custom moderation handling."""

from typing import Any, Dict

from agno.agent import Agent
from agno.exceptions import InputCheckError
from agno.guardrails import OpenAIModerationGuardrail
from agno.models.openai import OpenAIChat

moderation_events: list[Dict[str, Any]] = []


def log_moderation(error: Exception, input_data: Any, context: Dict[str, Any]) -> None:
    """Log moderation events for security monitoring."""
    moderation_events.append(
        {
            "guardrail": context.get("guardrail_name"),
            "check_type": context.get("check_type"),
        }
    )


agent = Agent(
    model=OpenAIChat(id="gpt-4o-mini"),
    pre_hooks=[OpenAIModerationGuardrail(on_fail=log_moderation)],
)

try:
    agent.print_response("How can I violently attack someone?")
except InputCheckError:
    print(f"Moderation events: {len(moderation_events)}")
