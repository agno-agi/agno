"""ClassifierGuardrail in all hooks - defense in depth pattern."""

from agno.agent import Agent
from agno.guardrails.classifier import ClassifierGuardrail
from agno.models.openai import OpenAIChat

classifier_model = OpenAIChat(id="gpt-4o-mini")

agent = Agent(
    model=OpenAIChat(id="gpt-4o-mini"),
    # Layer 1: Check user input
    pre_hooks=[
        ClassifierGuardrail(
            model=classifier_model,
            categories=["safe", "spam", "competitor_mention"],
            blocked_categories=["spam", "competitor_mention"],
        )
    ],
    # Layer 2: Check full context (includes RAG/memory)
    model_hooks=[
        ClassifierGuardrail(
            model=classifier_model,
            categories=["safe", "spam", "competitor_mention"],
            blocked_categories=["spam", "competitor_mention"],
        )
    ],
    # Layer 3: Check model output
    post_hooks=[
        ClassifierGuardrail(
            model=classifier_model,
            categories=["safe", "promotional", "inappropriate"],
            blocked_categories=["promotional", "inappropriate"],
            check_output=True,
        )
    ],
    instructions="You are a customer support assistant.",
)

response = agent.run("How do I reset my password?")
print(f"Status: {response.status.value}")
print(f"Content: {response.content[:200]}...")
