"""PIIDetectionGuardrail in all hooks - defense in depth pattern."""

from agno.agent import Agent
from agno.guardrails import PIIDetectionGuardrail
from agno.models.openai import OpenAIChat

agent = Agent(
    model=OpenAIChat(id="gpt-4o-mini"),
    # Layer 1: Check user input
    pre_hooks=[PIIDetectionGuardrail(strategy="block")],
    # Layer 2: Check full context (includes RAG/memory)
    model_hooks=[PIIDetectionGuardrail(strategy="block")],
    # Layer 3: Check model output
    post_hooks=[PIIDetectionGuardrail(strategy="block")],
)

response = agent.run("How are Elena's medical records?")
print(f"Status: {response.status.value}")
print(f"Content: {response.content}")
