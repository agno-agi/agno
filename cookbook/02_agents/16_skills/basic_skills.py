"""
Basic Skills
=============================

Basic Skills Example.
"""

from pathlib import Path

from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.skills import LocalSkills, Skills

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
# Get the skills directory relative to this file
skills_dir = Path(__file__).parent / "sample_skills"

# Create an agent with skills loaded from the directory
agent = Agent(
    name="Code Review Agent",
    model=OpenAIResponses(id="gpt-5.2"),
    skills=Skills(loaders=[LocalSkills(str(skills_dir))]),
    instructions=[
        "You are a helpful assistant with access to specialized skills.",
    ],
    markdown=True,
)


# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # Ask the agent to review some code
    agent.print_response(
        "Review this Python code and provide feedback:\n\n"
        "```python\n"
        "def calculate_total(items):\n"
        "    total = 0\n"
        "    for i in range(len(items)):\n"
        "        total = total + items[i]['price'] * items[i]['quantity']\n"
        "    return total\n"
        "```"
    )
