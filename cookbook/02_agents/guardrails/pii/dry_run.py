"""PIIDetectionGuardrail dry_run mode - logs PII without blocking."""

from agno.agent import Agent
from agno.guardrails import PIIDetectionGuardrail
from agno.models.openai import OpenAIChat

# dry_run=True logs PII detections but doesn't block
agent = Agent(
    model=OpenAIChat(id="gpt-4o-mini"),
    pre_hooks=[PIIDetectionGuardrail(dry_run=True)],
)

# This would normally be blocked, but dry_run only logs
# Check logs for: "PIIDetectionGuardrail.pre_check would block (dry_run): ..."
response = agent.run("My SSN is 123-45-6789")
print(f"Status: {response.status.value}")
print(f"Content: {response.content[:100]}...")
