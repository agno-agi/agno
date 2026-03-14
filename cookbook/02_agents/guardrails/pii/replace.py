"""PII replacement - replaces sensitive data with type labels.

The 'replace' strategy substitutes detected PII with descriptive labels
like [EMAIL], [SSN], [PHONE], preserving context while protecting data.

Example transformation:
  Input:   "Contact john@example.com or call 555-123-4567"
  Replaced: "Contact [EMAIL] or call [PHONE]"
"""

from agno.agent import Agent
from agno.guardrails import PIIDetectionGuardrail
from agno.models.openai import OpenAIChat

# Create guardrail with replace strategy
guardrail = PIIDetectionGuardrail(strategy="replace")

agent = Agent(
    model=OpenAIChat(id="gpt-4o-mini"),
    pre_hooks=[guardrail],
    instructions="Repeat back the information the user provided.",
)

# Test with multiple PII types
test_input = "My email is john@example.com and SSN is 123-45-6789"

print("Original input:")
print(f"  {test_input}")
print()

# The agent receives the replaced version: [EMAIL], [SSN]
agent.print_response(test_input)
