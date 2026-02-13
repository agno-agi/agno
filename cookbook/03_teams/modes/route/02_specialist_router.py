"""
Specialist Router Example

Demonstrates routing to domain specialist agents. The team leader analyzes
the user's question and routes it to the most qualified specialist.

"""

from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.team.mode import TeamMode
from agno.team.team import Team

# ---------------------------------------------------------------------------
# Create Members
# ---------------------------------------------------------------------------

math_agent = Agent(
    name="Math Specialist",
    role="Solves mathematical problems and explains concepts",
    model=OpenAIResponses(id="gpt-5.2"),
    instructions=[
        "You are a mathematics expert.",
        "Solve problems step by step, showing your work clearly.",
        "Explain the underlying concepts when relevant.",
    ],
)

code_agent = Agent(
    name="Code Specialist",
    role="Writes code and explains programming concepts",
    model=OpenAIResponses(id="gpt-5.2"),
    instructions=[
        "You are a programming expert.",
        "Write clean, well-commented code.",
        "Explain your approach and any trade-offs.",
    ],
)

science_agent = Agent(
    name="Science Specialist",
    role="Explains scientific concepts and phenomena",
    model=OpenAIResponses(id="gpt-5.2"),
    instructions=[
        "You are a science expert covering physics, chemistry, and biology.",
        "Explain concepts clearly with real-world examples.",
    ],
)

# ---------------------------------------------------------------------------
# Create Team
# ---------------------------------------------------------------------------

team = Team(
    name="Expert Router",
    mode=TeamMode.route,
    model=OpenAIResponses(id="gpt-5.2"),
    members=[math_agent, code_agent, science_agent],
    instructions=[
        "You are an expert router.",
        "Analyze the user's question and route it to the best specialist:",
        "- Math questions -> Math Specialist",
        "- Programming questions -> Code Specialist",
        "- Science questions -> Science Specialist",
    ],
    show_members_responses=True,
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run Team
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    team.print_response(
        "What is the time complexity of merge sort and why?",
        stream=True,
    )
