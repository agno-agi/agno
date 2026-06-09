"""PIIDetectionGuardrail at all three hook positions.

Demonstrates each hook layer actually firing:
  - pre_hooks (mask): transforms PII in user input
  - model_hooks (block): catches PII injected via instructions/context
  - post_hooks (block): catches PII in model output
"""

from agno.agent import Agent
from agno.guardrails import PIIDetectionGuardrail
from agno.models.openai import OpenAIChat
from agno.run.agent import RunStatus

# --- Layer 1 demo: pre_hook masks PII in user input ---
pre_hook_agent = Agent(
    model=OpenAIChat(id="gpt-4o-mini"),
    pre_hooks=[PIIDetectionGuardrail(strategy="mask")],
    instructions="You are a helpful assistant.",
)

# --- Layer 2 demo: model_hook blocks PII in full context ---
# The system instructions contain PII that pre_hook doesn't see.
# model_hook inspects the full message context including instructions.
model_hook_agent = Agent(
    model=OpenAIChat(id="gpt-4o-mini"),
    model_hooks=[PIIDetectionGuardrail(strategy="block")],
    instructions="The admin contact is admin@internal-corp.com. Help users with their questions.",
)

# --- Layer 3 demo: post_hook blocks PII in model output ---
# Instructions tell the model to include a phone number in responses.
post_hook_agent = Agent(
    model=OpenAIChat(id="gpt-4o-mini"),
    post_hooks=[PIIDetectionGuardrail(strategy="block")],
    instructions="Always end your response with: For support call 555-867-5309.",
)

if __name__ == "__main__":
    print("PII All Hooks Demo")
    print("=" * 50)

    print("\n[TEST 1] Pre-hook: masks PII in user input")
    print("-" * 30)
    response = pre_hook_agent.run("My SSN is 123-45-6789, can you help?")
    print(f"Status: {response.status.value}")
    if response.status == RunStatus.completed:
        print("[OK] PII masked in input, model received: ************")

    print("\n[TEST 2] Model-hook: blocks PII found in context")
    print("-" * 30)
    response = model_hook_agent.run("Who should I contact?")
    print(f"Status: {response.status.value}")
    if response.status == RunStatus.error:
        print(f"[BLOCKED at model_hook] {response.content}")

    print("\n[TEST 3] Post-hook: blocks PII in model output")
    print("-" * 30)
    response = post_hook_agent.run("How do I reset my password?")
    print(f"Status: {response.status.value}")
    if response.status == RunStatus.error:
        print(f"[BLOCKED at post_hook] {response.content}")
