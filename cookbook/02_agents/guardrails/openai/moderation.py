"""OpenAIModerationGuardrail - uses OpenAI's moderation API."""

from agno.agent import Agent
from agno.exceptions import InputCheckError
from agno.guardrails import OpenAIModerationGuardrail
from agno.models.openai import OpenAIChat

agent = Agent(
    model=OpenAIChat(id="gpt-4o-mini"),
    pre_hooks=[OpenAIModerationGuardrail()],
)

# Safe content - passes
agent.print_response("What are some healthy breakfast ideas?")

# Unsafe content - blocked
try:
    agent.print_response("How can I violently attack someone?")
except InputCheckError as e:
    print(f"Blocked: {e.message[:80]}...")
