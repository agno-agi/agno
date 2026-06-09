"""ContentGuardrail - restricts agent to specific topics."""

from agno.agent import Agent
from agno.guardrails import ContentGuardrail
from agno.models.openai import OpenAIChat
from agno.run.agent import RunStatus

# Support agent only handles billing and shipping
agent = Agent(
    model=OpenAIChat(id="gpt-4o-mini"),
    pre_hooks=[
        ContentGuardrail(
            check_off_topic=True,
            allowed_topics=["billing", "shipping", "order", "payment"],
        )
    ],
    instructions="Help with billing and shipping questions.",
)

if __name__ == "__main__":
    # On-topic - passes
    response = agent.run("What is my order status?")
    print(f"Status: {response.status.value}")
    if response.status == RunStatus.completed:
        print(f"[OK] {str(response.content)[:100]}")

    # Off-topic - blocked
    response = agent.run("Can you recommend a restaurant?")
    print(f"Status: {response.status.value}")
    if response.status == RunStatus.error:
        print(f"[BLOCKED] {response.content}")
