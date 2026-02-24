"""
Mixed Hooks and Guardrails
=============================

Example demonstrating how to combine plain hooks with guardrails in pre_hooks.
When both are used together, guardrails always block before any plain hooks run
in background mode — ensuring PII never reaches the model.
"""

from agno.agent import Agent
from agno.exceptions import InputCheckError
from agno.guardrails import PIIDetectionGuardrail
from agno.models.openai import OpenAIResponses
from agno.run.agent import RunInput


# ---------------------------------------------------------------------------
# Plain hook (non-guardrail)
# ---------------------------------------------------------------------------
def log_request(run_input: RunInput) -> None:
    """Pre-hook that logs every incoming request."""
    print(f"  [log_request] Input: {run_input.input_content[:60]}")


# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
def main():
    print("Mixed Hooks and Guardrails Demo")
    print("=" * 50)

    agent = Agent(
        name="Privacy-Protected Agent",
        model=OpenAIResponses(id="gpt-5-mini"),
        pre_hooks=[log_request, PIIDetectionGuardrail()],
        instructions="You are a helpful assistant that protects user privacy.",
    )

    # Test 1: Clean input — hook runs, guardrail passes, agent responds
    print("\n[TEST 1] Clean input (no PII)")
    print("-" * 40)
    try:
        response = agent.run(input="What is the weather today?")
        print(f"  [OK] Agent responded: {response.content[:80]}")
    except InputCheckError as e:
        print(f"  [ERROR] Unexpected block: {e.message}")

    # Test 2: PII input — guardrail blocks before agent sees the data
    print("\n[TEST 2] Input with SSN")
    print("-" * 40)
    try:
        agent.run(input="My SSN is 123-45-6789, can you help?")
        print("  [WARNING] Should have been blocked!")
    except InputCheckError as e:
        print(f"  [BLOCKED] Guardrail rejected: {e.message}")
        print(f"   Trigger: {e.check_trigger}")

    # Test 3: PII input with credit card
    print("\n[TEST 3] Input with credit card")
    print("-" * 40)
    try:
        agent.run(input="My card is 4532 1234 5678 9012, charge it.")
        print("  [WARNING] Should have been blocked!")
    except InputCheckError as e:
        print(f"  [BLOCKED] Guardrail rejected: {e.message}")
        print(f"   Trigger: {e.check_trigger}")

    print("\n" + "=" * 50)
    print("Mixed Hooks and Guardrails Demo Complete")


# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    main()
