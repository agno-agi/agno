"""
Model hooks execute AFTER context is built but BEFORE the model is called.
This allows inspection and modification of the full message context.
"""

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.run.messages import RunMessages


def inspect_context(run_messages: RunMessages, **kwargs) -> None:
    """Model hook: Log the context being sent to model."""
    print("\n[MODEL HOOK] Context before model call:")
    print(f"  Messages: {len(run_messages.messages)}")
    for i, msg in enumerate(run_messages.messages):
        content = str(msg.content)[:60] if msg.content else "(empty)"
        print(f"    [{i}] {msg.role}: {content}...")


def add_reminder(run_messages: RunMessages, **kwargs) -> None:
    """Model hook: Add a reminder to the context."""
    from agno.models.message import Message

    reminder = Message(role="system", content="REMINDER: Be concise.")
    run_messages.messages.insert(-1, reminder)
    print("[MODEL HOOK] Added reminder to context")


agent = Agent(
    model=OpenAIChat(id="gpt-4o-mini"),
    description="A helpful assistant.",
    instructions=["Provide clear, accurate responses."],
    model_hooks=[inspect_context, add_reminder],
)

response = agent.run("What is Python?")
print("\nAgent Response:")
print(response.content)
