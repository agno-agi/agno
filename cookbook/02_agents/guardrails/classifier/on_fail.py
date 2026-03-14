"""ClassifierGuardrail on_fail callback - custom classification handling."""

from typing import Any, Dict

from agno.agent import Agent
from agno.guardrails.classifier import ClassifierGuardrail
from agno.models.openai import OpenAIChat

classification_events: list[Dict[str, Any]] = []


def log_classification(
    error: Exception, input_data: Any, context: Dict[str, Any]
) -> None:
    """Log classification events for analytics."""
    classification_events.append(
        {
            "guardrail": context.get("guardrail_name"),
            "info": context.get("additional_info"),
        }
    )


classifier_model = OpenAIChat(id="gpt-4o-mini")

agent = Agent(
    model=OpenAIChat(id="gpt-4o-mini"),
    pre_hooks=[
        ClassifierGuardrail(
            model=classifier_model,
            categories=["safe", "spam"],
            blocked_categories=["spam"],
            on_fail=log_classification,
        )
    ],
)

response = agent.run("BUY NOW!!! FREE MONEY!!!")
print(f"Status: {response.status.value}")
print(f"Classification events: {len(classification_events)}")
