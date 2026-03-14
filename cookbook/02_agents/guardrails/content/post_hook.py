"""ContentGuardrail in post_hooks - validates model output."""

from agno.agent import Agent
from agno.guardrails import ContentGuardrail
from agno.models.openai import OpenAIChat

agent = Agent(
    model=OpenAIChat(id="gpt-4o-mini"),
    post_hooks=[
        ContentGuardrail(
            check_toxicity=True,
            check_output=True,  # Required for post_hooks
        )
    ],
)

response = agent.run("Explain how computers work briefly.")
print(f"Status: {response.status.value}")
print(f"Content: {response.content}")
