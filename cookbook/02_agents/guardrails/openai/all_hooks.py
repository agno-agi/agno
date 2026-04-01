"""OpenAIModerationGuardrail in all hooks - defense in depth pattern."""

from agno.agent import Agent
from agno.guardrails import OpenAIModerationGuardrail
from agno.models.openai import OpenAIChat

moderation = OpenAIModerationGuardrail(check_output=True)

agent = Agent(
    model=OpenAIChat(id="gpt-4o-mini"),
    pre_hooks=[moderation],  # Check user input
    model_hooks=[moderation],  # Check full context
    post_hooks=[moderation],  # Check model output
)

response = agent.run("What are some healthy breakfast ideas?")
print(f"Status: {response.status.value}")
print(f"Content: {response.content[:200]}...")
