"""
This example demonstrates how to create a team with custom tools.

The team uses custom tools alongside agent tools to answer questions from a knowledge base
and fall back to web search when needed.
"""

from agno.agent import Agent
from agno.team.team import Team
from agno.tools import tool
from agno.tools.duckduckgo import DuckDuckGoTools


@tool()
def answer_from_known_questions(question: str) -> str:
    """Answer a question from a list of known questions

    Args:
        question: The question to answer

    Returns:
        The answer to the question
    """

    # FAQ knowledge base
    faq = {
        "What is the capital of France?": "Paris",
        "What is the capital of Germany?": "Berlin",
        "What is the capital of Italy?": "Rome",
        "What is the capital of Spain?": "Madrid",
        "What is the capital of Portugal?": "Lisbon",
        "What is the capital of Greece?": "Athens",
        "What is the capital of Turkey?": "Ankara",
    }

    # Check if question is in FAQ
    if question in faq:
        return f"From my knowledge base: {faq[question]}"
    else:
        return "I don't have that information in my knowledge base. Try asking the web search agent."


# Create web search agent for fallback
web_agent = Agent(
    name="Web Agent",
    role="Search the web for information",
    tools=[DuckDuckGoTools()],
    markdown=True,
)

# Create team with custom tool and agent members
team = Team(name="Q & A team", members=[web_agent], tools=[answer_from_known_questions])

# Test the team
team.print_response("What is the capital of France?", stream=True)

# Check if team has session state and display information
print("\n📊 Team Session Info:")
print(f"   Session ID: {team.session_id}")
print(f"   Session State: {team.session_state}")

# Show team capabilities
print("\n🔧 Team Tools Available:")
for t in team.tools:
    print(f"   - {t.name}: {t.description}")

print("\n👥 Team Members:")
for member in team.members:
    print(f"   - {member.name}: {member.role}")
