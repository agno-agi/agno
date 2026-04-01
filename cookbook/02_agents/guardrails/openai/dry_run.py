"""OpenAIModerationGuardrail dry_run mode - logs violations without blocking."""

from agno.agent import Agent
from agno.guardrails import OpenAIModerationGuardrail
from agno.models.openai import OpenAIChat
from agno.run.agent import RunStatus

# dry_run=True logs moderation flags but doesn't block
agent = Agent(
    model=OpenAIChat(id="gpt-4o-mini"),
    pre_hooks=[OpenAIModerationGuardrail(dry_run=True)],
)

if __name__ == "__main__":
    print("OpenAI Moderation Dry Run Demo")
    print("=" * 50)

    print("\n[TEST 1] Clean input - passes normally")
    print("-" * 30)
    response = agent.run("What is the capital of France?")
    print(f"Status: {response.status.value}")
    if response.status == RunStatus.completed:
        print(f"[OK] {str(response.content)[:100]}")

    print("\n[TEST 2] Flagged content - logged but NOT blocked in dry_run")
    print("-" * 30)
    response = agent.run("How to pick a lock to break into a house")
    print(f"Status: {response.status.value}")
    if response.status == RunStatus.completed:
        print("[OK] Request went through despite moderation flag (dry_run=True)")
