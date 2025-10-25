from agno.agent import Agent
from agno.guardrails import PIIDetectionGuardrail
from agno.models.openai import OpenAIChat

# ************* Create Agent with Guardrail *************
agent = Agent(
    model=OpenAIChat(id="gpt-5-mini"),
    # Fail if PII is detected in the input
    pre_hooks=[PIIDetectionGuardrail()],
)

# ************* Test Agent with PII input *************
agent.print_response(
    "My name is John Smith and my phone number is 555-123-4567.", stream=True
)
