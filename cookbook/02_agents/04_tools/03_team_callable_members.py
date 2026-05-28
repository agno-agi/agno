"""
Team Callable Members
=====================
Pass a function as `members` to a Team. The team composition
is decided at run time based on session_state.
"""

from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.team import Team

# ---------------------------------------------------------------------------
# Create the Team Members
# ---------------------------------------------------------------------------

writer = Agent(
    name="Writer",
    role="Content writer",
    model=OpenAIResponses(id="gpt-5-mini"),
    instructions=["Write clear, concise content."],
)

researcher = Agent(
    name="Researcher",
    role="Research analyst",
    model=OpenAIResponses(id="gpt-5-mini"),
    instructions=["Research topics and summarize findings."],
)


def pick_members(session_state: dict):
    """Include the researcher only when needed."""
    needs_research = session_state.get("needs_research", False)
    print(f"--> needs_research={needs_research}")

    if needs_research:
        return [researcher, writer]
    return [writer]


# ---------------------------------------------------------------------------
# Create the Team
# ---------------------------------------------------------------------------

team = Team(
    name="Content Team",
    model=OpenAIResponses(id="gpt-5-mini"),
    members=pick_members,
    cache_callables=False,
    instructions=["Coordinate the team to complete the task."],
)


# ---------------------------------------------------------------------------
# Run the Team
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("=== Writer only ===")
    team.print_response(
        "Write a haiku about Python",
        session_state={"needs_research": False},
        stream=True,
    )

    print("\n=== Researcher + Writer ===")
    team.print_response(
        "Research the history of Python and write a short summary",
        session_state={"needs_research": True},
        stream=True,
    )
