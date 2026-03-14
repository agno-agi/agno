"""PII tokenization - replaces PII with tokens, allows restoration later."""

from agno.agent import Agent
from agno.guardrails import PIIDetectionGuardrail
from agno.models.openai import OpenAIChat

guardrail = PIIDetectionGuardrail(strategy="tokenize")

agent = Agent(
    model=OpenAIChat(id="gpt-4o-mini"),
    pre_hooks=[guardrail],
    instructions="Repeat the user's message exactly.",
)

# PII becomes <PII_0>, <PII_1>, etc.
response = agent.run("Contact john@example.com or call 555-123-4567")
print(f"Tokenized response: {response.content}")

# Restore original PII when needed
restored = guardrail.restore(str(response.content))
print(f"Restored: {restored}")
print(f"Mapping: {guardrail.pii_mapping}")
