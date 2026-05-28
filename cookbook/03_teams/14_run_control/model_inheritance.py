"""
Model Inheritance
=============================

Demonstrates how member models inherit from parent team models.
"""

from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.team import Team

# ---------------------------------------------------------------------------
# Create Members
# ---------------------------------------------------------------------------
researcher = Agent(
    name="Researcher",
    role="Research and gather information",
    instructions=["Be thorough and detailed"],
)

writer = Agent(
    name="Writer",
    role="Write content based on research",
    instructions=["Write clearly and concisely"],
)

editor = Agent(
    name="Editor",
    role="Edit and refine content",
    model=OpenAIResponses(id="gpt-5.2"),
    instructions=["Ensure clarity and correctness"],
)

analyst = Agent(
    name="Analyst",
    role="Analyze data and provide insights",
)

sub_team = Team(
    name="Analysis Team",
    model=OpenAIResponses(id="gpt-5.2"),
    members=[analyst],
)

# ---------------------------------------------------------------------------
# Create Team
# ---------------------------------------------------------------------------
team = Team(
    name="Content Production Team",
    model=OpenAIResponses(id="gpt-5.2"),
    members=[researcher, writer, editor, sub_team],
    instructions=[
        "Research the topic thoroughly",
        "Write clear and engaging content",
        "Edit for quality and clarity",
        "Coordinate the entire process",
    ],
)

# ---------------------------------------------------------------------------
# Run Team
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    team.initialize_team()

    print(f"Researcher model: {researcher.model.id}")
    print(f"Writer model: {writer.model.id}")
    print(f"Editor model: {editor.model.id}")
    print(f"Analyst model: {analyst.model.id}")

    team.print_response("Write a brief article about AI", stream=True)
