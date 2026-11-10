"""
Expected Output
===============

Demonstrates setting a team-level `expected_output` to describe the desired
run result shape.
"""

from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.team import Team

# ---------------------------------------------------------------------------
# Create Members
# ---------------------------------------------------------------------------
incident_analyst = Agent(
    name="Incident Analyst",
    model=OpenAIResponses(id="gpt-5-mini"),
    instructions=[
        "Extract outcomes and risks clearly.",
        "Avoid unnecessary speculation.",
    ],
)


# ---------------------------------------------------------------------------
# Create Team
# ---------------------------------------------------------------------------
incident_team = Team(
    name="Incident Reporting Team",
    model=OpenAIResponses(id="gpt-5-mini"),
    members=[incident_analyst],
    expected_output=(
        "Three sections: Summary, Impact, and Next Step. "
        "Keep each section to one sentence."
    ),
    instructions=[
        "Summarize incidents in a clear operational style.",
        "Prefer plain language over technical jargon.",
    ],
)


# ---------------------------------------------------------------------------
# Run Team
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    incident_team.print_response(
        (
            "A deployment changed the auth callback behavior, login requests increased by 12%, "
            "and a rollback script is already prepared."
        ),
        stream=True,
    )
