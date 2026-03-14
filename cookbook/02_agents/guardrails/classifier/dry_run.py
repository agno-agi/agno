"""ClassifierGuardrail dry_run mode - logs classifications without blocking."""

from agno.agent import Agent
from agno.guardrails.classifier import ClassifierGuardrail
from agno.models.openai import OpenAIChat

classifier_model = OpenAIChat(id="gpt-4o-mini")

# dry_run=True logs blocked categories but doesn't raise errors
agent = Agent(
    model=OpenAIChat(id="gpt-4o-mini"),
    pre_hooks=[
        ClassifierGuardrail(
            model=classifier_model,
            categories=["safe", "spam", "competitor_mention"],
            blocked_categories=["spam", "competitor_mention"],
            dry_run=True,
        )
    ],
)

# This would normally be blocked, but dry_run only logs
# Check logs for: "ClassifierGuardrail.pre_check would block (dry_run): ..."
response = agent.run("BUY NOW!!! LIMITED TIME OFFER!!!")
print(f"Status: {response.status.value}")
print(f"Content: {response.content[:100]}...")
