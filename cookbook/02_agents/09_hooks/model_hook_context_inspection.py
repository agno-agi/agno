"""
Model Hook Context Inspection
=============================

Model hooks execute AFTER context is built but BEFORE the model is called.
This example demonstrates read-only inspection of the full message context,
useful for logging, debugging, and token estimation.
"""

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.run.messages import RunMessages


# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------
def inspect_context(run_messages: RunMessages, **kwargs) -> None:
    """Log the message context being sent to the model."""
    print("\n  [MODEL HOOK] Context before model call:")
    print(f"  Messages: {len(run_messages.messages)}")
    for i, msg in enumerate(run_messages.messages):
        content = str(msg.content)[:80] if msg.content else "(empty)"
        print(f"    [{i}] {msg.role}: {content}")


def estimate_tokens(run_messages: RunMessages, **kwargs) -> None:
    """Estimate input size from the message context (read-only)."""
    total_chars = sum(len(str(msg.content or "")) for msg in run_messages.messages)
    estimated_tokens = total_chars // 4
    print(
        f"  [MODEL HOOK] Estimated input: ~{total_chars} chars, ~{estimated_tokens} tokens"
    )


# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
agent = Agent(
    model=OpenAIChat(id="gpt-4o-mini"),
    description="A helpful assistant.",
    instructions=["Provide clear, accurate responses."],
    model_hooks=[inspect_context, estimate_tokens],
)


# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
def main() -> None:
    print("Model Hook Context Inspection")
    print("=" * 50)

    print("\n[TEST 1] Simple question")
    print("-" * 30)
    response = agent.run("What is Python?")
    print(f"\nResponse: {str(response.content)[:200]}")

    print("\n[TEST 2] Longer question with context")
    print("-" * 30)
    response = agent.run(
        "I am building a web application using Python and Django. "
        "What are the best practices for structuring the project?"
    )
    print(f"\nResponse: {str(response.content)[:200]}")


if __name__ == "__main__":
    main()
