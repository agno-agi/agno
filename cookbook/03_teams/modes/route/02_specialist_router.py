"""
Specialist Router Example

Demonstrates routing to domain specialist agents. The team leader analyzes
the user's question and routes it to the most qualified specialist.

Run: .venvs/demo/bin/python cookbook/03_teams/modes/route/02_specialist_router.py
"""

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.team.mode import TeamMode
from agno.team.team import Team

# -- Domain specialists ------------------------------------------------------

math_agent = Agent(
    name="Math Specialist",
    role="Solves mathematical problems and explains concepts",
    model=OpenAIChat(id="gpt-4o-mini"),
    instructions=[
        "You are a mathematics expert.",
        "Solve problems step by step, showing your work clearly.",
        "Explain the underlying concepts when relevant.",
    ],
)

code_agent = Agent(
    name="Code Specialist",
    role="Writes code and explains programming concepts",
    model=OpenAIChat(id="gpt-4o-mini"),
    instructions=[
        "You are a programming expert.",
        "Write clean, well-commented code.",
        "Explain your approach and any trade-offs.",
    ],
)

science_agent = Agent(
    name="Science Specialist",
    role="Explains scientific concepts and phenomena",
    model=OpenAIChat(id="gpt-4o-mini"),
    instructions=[
        "You are a science expert covering physics, chemistry, and biology.",
        "Explain concepts clearly with real-world examples.",
    ],
)

# -- Route team --------------------------------------------------------------

team = Team(
    name="Expert Router",
    mode=TeamMode.route,
    model=OpenAIChat(id="gpt-4o"),
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

# -- Run ---------------------------------------------------------------------

if __name__ == "__main__":
    team.print_response(
        "What is the time complexity of merge sort and why?",
        stream=True,
    )
