"""
Team Callable Members
=====================
Pass a function as `members` to a Team. The team composition
is decided at run time based on session_state.

Members can be flat agents or nested sub-teams — the factory
can return any mix of Agent and Team instances.
"""

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.team import Team

# ---------------------------------------------------------------------------
# Create the Team Members
# ---------------------------------------------------------------------------

writer = Agent(
    name="Writer",
    role="Content writer",
    model=OpenAIChat(id="gpt-4o-mini"),
    instructions=["Write clear, concise content."],
)

researcher = Agent(
    name="Researcher",
    role="Research analyst",
    model=OpenAIChat(id="gpt-4o-mini"),
    instructions=["Research topics and summarize findings."],
)

reviewer = Agent(
    name="Reviewer",
    role="Quality reviewer",
    model=OpenAIChat(id="gpt-4o-mini"),
    instructions=["Review content for accuracy and clarity."],
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
    model=OpenAIChat(id="gpt-4o-mini"),
    members=pick_members,
    cache_callables=False,
    instructions=["Coordinate the team to complete the task."],
)

# ---------------------------------------------------------------------------
# Nested sub-team as a callable member
# ---------------------------------------------------------------------------

content_team = Team(
    name="ContentTeam",
    model=OpenAIChat(id="gpt-4o-mini"),
    members=[researcher, writer],
    instructions=["Coordinate research and writing tasks."],
)


def pick_members_with_subteam(session_state: dict):
    """Return a sub-team and optionally a reviewer."""
    needs_review = session_state.get("needs_review", False)
    print(f"--> needs_review={needs_review}")

    members = [content_team]
    if needs_review:
        members.append(reviewer)
    return members


parent_team = Team(
    name="PublishingTeam",
    model=OpenAIChat(id="gpt-4o-mini"),
    members=pick_members_with_subteam,
    cache_callables=False,
    instructions=["Coordinate the team to complete the publishing task."],
)

# ---------------------------------------------------------------------------
# Run the Team
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    # Flat callable members
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

    # Nested sub-team as callable member
    print("\n=== Nested sub-team (no review) ===")
    parent_team.print_response(
        "Write a haiku about Python programming",
        session_state={"needs_review": False},
        stream=True,
    )

    print("\n=== Nested sub-team (with review) ===")
    parent_team.print_response(
        "Write a short paragraph about agent frameworks and review it",
        session_state={"needs_review": True},
        stream=True,
    )
