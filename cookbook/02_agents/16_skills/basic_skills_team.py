"""
Basic Skills on a Team
=============================

Shows how to attach Skills to a Team leader so it gets domain expertise
(instructions, references, scripts) directly — without needing to delegate
to a member agent.
"""

from pathlib import Path

from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.skills import LocalSkills, Skills
from agno.team.team import Team

# ---------------------------------------------------------------------------
# Skills — loaded from the same sample directory used by basic_skills.py
# ---------------------------------------------------------------------------
skills_dir = Path(__file__).parent / "sample_skills"

# ---------------------------------------------------------------------------
# Member Agents
# ---------------------------------------------------------------------------
implementer = Agent(
    name="Implementer",
    role="Write code based on the review feedback",
    model=OpenAIResponses(id="gpt-5.2"),
    instructions=[
        "You write clean, well-tested Python code.",
        "When given review feedback, produce an improved version of the code.",
    ],
)

# ---------------------------------------------------------------------------
# Team with Skills on the leader
# ---------------------------------------------------------------------------
review_team = Team(
    name="Code Review Team",
    model=OpenAIResponses(id="gpt-5.2"),
    members=[implementer],
    skills=Skills(loaders=[LocalSkills(str(skills_dir))]),
    instructions=[
        "You are a team leader with access to code review skills.",
        "Use your skills to review code, then delegate implementation work to the Implementer.",
    ],
    markdown=True,
    show_members_responses=True,
)

# ---------------------------------------------------------------------------
# Run Team
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    review_team.print_response(
        "Review this Python code and suggest improvements, "
        "then have the Implementer write the improved version:\n\n"
        "```python\n"
        "def calculate_total(items):\n"
        "    total = 0\n"
        "    for i in range(len(items)):\n"
        "        total = total + items[i]['price'] * items[i]['quantity']\n"
        "    return total\n"
        "```",
        stream=True,
    )
