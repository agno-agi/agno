"""ContentGuardrail in all hooks - defense in depth pattern."""

from agno.agent import Agent
from agno.guardrails import ContentGuardrail
from agno.models.openai import OpenAIChat

agent = Agent(
    model=OpenAIChat(id="gpt-4o-mini"),
    # Layer 1: Check user input
    pre_hooks=[ContentGuardrail(check_jailbreak=True, check_toxicity=True)],
    # Layer 2: Check full context (includes RAG/memory)
    model_hooks=[ContentGuardrail(check_jailbreak=True)],
    # Layer 3: Check model output
    post_hooks=[ContentGuardrail(check_toxicity=True, check_output=True)],
)

response = agent.run("What is the Python programming language?")
print(f"Status: {response.status.value}")
print(f"Content: {response.content[:200]}...")
