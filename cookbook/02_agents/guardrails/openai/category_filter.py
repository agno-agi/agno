"""OpenAIModerationGuardrail - filter specific content categories.

Only blocks violence and hate categories while allowing other
content that OpenAI moderation might otherwise flag.
"""

from agno.agent import Agent
from agno.guardrails import OpenAIModerationGuardrail
from agno.models.openai import OpenAIChat
from agno.run.agent import RunStatus

# Only block violence and hate categories
agent = Agent(
    model=OpenAIChat(id="gpt-4o-mini"),
    pre_hooks=[
        OpenAIModerationGuardrail(
            raise_for_categories=[
                "violence",
                "violence/graphic",
                "hate",
                "hate/threatening",
            ]
        )
    ],
)

if __name__ == "__main__":
    print("OpenAI Category Filter Demo")
    print("=" * 50)

    print("\n[TEST 1] Clean input - should pass")
    print("-" * 30)
    response = agent.run("Tell me a story about a friendly dragon.")
    print(f"Status: {response.status.value}")
    if response.status == RunStatus.completed:
        print(f"[OK] {str(response.content)[:100]}...")

    print("\n[TEST 2] Violent content - should be blocked")
    print("-" * 30)
    response = agent.run("Write a story glorifying extreme violence and destruction")
    print(f"Status: {response.status.value}")
    if response.status == RunStatus.error:
        print(f"[BLOCKED] {response.content}")
