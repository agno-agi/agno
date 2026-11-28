"""Redact prior team history before routing a new request to a specialist.

The callback receives the rendered history selected by num_team_history_runs.
Return None to omit that history entirely. It does not modify stored runs,
the current request, shared member interactions, or a member's own history.
"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.team.mode import TeamMode
from agno.team.team import Team


def redact_history(history: str) -> str:
    # Replace this illustrative rule with your application's redaction policy.
    return history.replace("DEMO-PRIVATE-123", "[redacted]")


# ---------------------------------------------------------------------------
# Create Team
# ---------------------------------------------------------------------------
team = Team(
    name="History Filtering Router",
    mode=TeamMode.route,
    model=OpenAIResponses(id="gpt-5.2"),
    members=[
        Agent(
            name="Support",
            role="Answers support questions",
            model=OpenAIResponses(id="gpt-5.2"),
        ),
        Agent(
            name="Billing",
            role="Answers billing questions",
            model=OpenAIResponses(id="gpt-5.2"),
        ),
    ],
    db=SqliteDb(db_file="tmp/history_filter.db"),
    add_team_history_to_members=True,
    num_team_history_runs=3,
    team_history_filter=redact_history,
    instructions="Route each request to the appropriate specialist.",
)

# ---------------------------------------------------------------------------
# Run Team
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # The first request is intentionally visible to Support as current input.
    # On the second request, Billing receives a redacted copy of prior history.
    team.print_response(
        "Ask Support to record my reference DEMO-PRIVATE-123.",
        session_id="history-filter-demo",
    )
    team.print_response(
        "Ask Billing how I can update my payment method.",
        session_id="history-filter-demo",
    )
