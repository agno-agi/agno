"""
Custom Tools
============

Demonstrates a team using a custom FAQ tool plus web-search fallback.
"""

from agno.agent import Agent
from agno.team import Team
from agno.tools import tool
from agno.tools.websearch import WebSearchTools


@tool()
def answer_from_known_questions(question: str) -> str:
    """Answer a question from a small built-in FAQ."""
    faq = {
        "What is the capital of France?": "Paris",
        "What is the capital of Germany?": "Berlin",
        "What is the capital of Italy?": "Rome",
        "What is the capital of Spain?": "Madrid",
        "What is the capital of Portugal?": "Lisbon",
        "What is the capital of Greece?": "Athens",
        "What is the capital of Turkey?": "Ankara",
    }

    if question in faq:
        return f"From my knowledge base: {faq[question]}"
    return "I don't have that information in my knowledge base. Try asking the web search agent."


# ---------------------------------------------------------------------------
# Create Members
# ---------------------------------------------------------------------------
web_agent = Agent(
    name="Web Agent",
    role="Search the web for information",
    tools=[WebSearchTools()],
    markdown=True,
)

# ---------------------------------------------------------------------------
# Create Team
# ---------------------------------------------------------------------------
team = Team(
    name="Q & A team",
    members=[web_agent],
    tools=[answer_from_known_questions],
)

# ---------------------------------------------------------------------------
# Run Team
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    team.print_response("What is the capital of France?", stream=True)

    print("\nTeam Session Info:")
    print(f"   Session ID: {team.session_id}")
    print(f"   Session State: {team.session_state}")

    print("\nTeam Tools Available:")
    for t in team.tools:
        print(f"   - {t.name}: {t.description}")

    print("\nTeam Members:")
    for member in team.members:
        print(f"   - {member.name}: {member.role}")
