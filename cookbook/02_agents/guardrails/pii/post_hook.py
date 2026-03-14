"""PIIDetectionGuardrail in post_hooks - checks model output for PII leakage."""

from agno.agent import Agent
from agno.guardrails import PIIDetectionGuardrail
from agno.models.openai import OpenAIChat

agent = Agent(
    model=OpenAIChat(id="gpt-4o-mini"),
    post_hooks=[PIIDetectionGuardrail(strategy="block")],
)

response = agent.run("What is 2+2?")
print(f"Status: {response.status.value}")
print(f"Content: {response.content}")
