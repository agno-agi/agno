"""PII masking - replaces sensitive data with asterisks.

The 'mask' strategy replaces detected PII with asterisks (*) of equal length,
preserving the structure of the message while hiding sensitive values.

Example transformation:
  Input:  "My email is john@example.com"
  Masked: "My email is ****************"
"""

from agno.agent import Agent
from agno.guardrails import PIIDetectionGuardrail
from agno.models.openai import OpenAIChat

# Create guardrail with mask strategy
guardrail = PIIDetectionGuardrail(strategy="mask")

agent = Agent(
    model=OpenAIChat(id="gpt-4o-mini"),
    pre_hooks=[guardrail],
    instructions="Repeat back what the user told you, confirming their information.",
)

# Test with multiple PII types
test_input = "Contact me at john@example.com or 555-123-4567. My SSN is 123-45-6789."

print("Original input:")
print(f"  {test_input}")
print()

# The agent receives the masked version
agent.print_response(test_input)
