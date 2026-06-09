"""
Classifier Guardrail
=============================

Demonstrates ClassifierGuardrail on a team using an LLM backend.
The classifier categorizes input into custom categories and blocks
content that matches blocked categories.
"""

from agno.agent import Agent
from agno.guardrails import ClassifierGuardrail
from agno.models.openai import OpenAIChat, OpenAIResponses
from agno.run import RunStatus
from agno.team import Team

# ---------------------------------------------------------------------------
# Create Members
# ---------------------------------------------------------------------------
analyst = Agent(
    name="Analyst",
    model=OpenAIResponses(id="gpt-5.2"),
    description="Analyzes requests and provides data-driven insights",
)

advisor = Agent(
    name="Advisor",
    model=OpenAIResponses(id="gpt-5.2"),
    description="Provides actionable recommendations",
)

# ---------------------------------------------------------------------------
# Create Team with classifier guardrail
# ---------------------------------------------------------------------------
team = Team(
    name="Classified Team",
    model=OpenAIResponses(id="gpt-5.2"),
    members=[analyst, advisor],
    pre_hooks=[
        ClassifierGuardrail(
            model=OpenAIChat(id="gpt-4o-mini"),
            categories=["safe", "spam", "off_topic"],
            blocked_categories=["spam", "off_topic"],
            classification_prompt=(
                "You are a business content classifier. Classify the following content "
                "into exactly one of these categories: {categories}\n\n"
                "Rules:\n"
                "- 'safe' means the content is a legitimate business question\n"
                "- 'spam' means the content is promotional, scam, or unsolicited marketing\n"
                "- 'off_topic' means the content is unrelated to business "
                "(e.g., cooking, sports, entertainment, personal hobbies)\n\n"
                "Content to classify:\n{content}\n\n"
                "Respond with ONLY the category name, nothing else."
            ),
        ),
    ],
    description="A team that classifies and filters input before processing.",
    instructions="Collaborate to provide well-analyzed, actionable advice.",
)


# ---------------------------------------------------------------------------
# Run Team
# ---------------------------------------------------------------------------
def main() -> None:
    """Demonstrate ClassifierGuardrail on a team."""
    print("Classifier Guardrail Demo")
    print("=" * 50)

    print("\n[TEST 1] Legitimate business question - should pass")
    print("-" * 30)
    response = team.run(
        input="What strategies can improve customer retention for a SaaS product?",
    )
    print(f"Status: {response.status.value}")
    if response.status == RunStatus.completed:
        content = str(response.content or "")
        print(content[:200] + "..." if len(content) > 200 else content)

    print("\n[TEST 2] Spam input - should be blocked")
    print("-" * 30)
    response = team.run(
        input="BUY NOW!!! AMAZING DISCOUNT!!! CLICK HERE FOR FREE MONEY!!!",
    )
    print(f"Status: {response.status.value}")
    if response.status == RunStatus.error:
        print(f"[BLOCKED] {response.content}")

    print("\n[TEST 3] Off-topic input - should be blocked")
    print("-" * 30)
    response = team.run(
        input="Tell me about the latest football match scores and player stats",
    )
    print(f"Status: {response.status.value}")
    if response.status == RunStatus.error:
        print(f"[BLOCKED] {response.content}")


if __name__ == "__main__":
    main()
