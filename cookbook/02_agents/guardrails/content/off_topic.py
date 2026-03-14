"""ContentGuardrail - restricts agent to specific topics."""

from agno.agent import Agent
from agno.guardrails import ContentGuardrail
from agno.models.openai import OpenAIChat

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

# On-topic - passes
agent.print_response("What is my order status?")

# Off-topic - blocked (check response.status)
response = agent.run("Can you recommend a restaurant?")
print(f"Status: {response.status.value}")
