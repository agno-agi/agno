"""
Deep Nested Team History
========================

Demonstrates 3-layer nested team history with a customer support use case.

Structure:
- Support Team (Level 1)
  - Triage Agent
  - Escalation Team (Level 2)
    - Technical Support Agent
    - Expert Team (Level 3)
      - Database Expert Agent
      - Security Expert Agent

Use case: Customer reports a database issue. Triage escalates to Escalation Team,
which further escalates to Expert Team for deep investigation. Each team maintains
its conversation history across the multi-turn investigation.
"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.team import Team

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------
db = SqliteDb(db_file="tmp/nested_team_deep_history.db")

# ---------------------------------------------------------------------------
# Level 3: Expert Team (innermost)
# ---------------------------------------------------------------------------
db_expert = Agent(
    name="Database Expert",
    model=OpenAIResponses(id="gpt-5.6-sol"),
    role="Diagnose database performance and connectivity issues",
)

security_expert = Agent(
    name="Security Expert",
    model=OpenAIResponses(id="gpt-5.6-sol"),
    role="Investigate security concerns and access issues",
)

expert_team = Team(
    name="Expert Team",
    model=OpenAIResponses(id="gpt-5.6-sol"),
    members=[db_expert, security_expert],
    add_history_to_context=True,
    role="Deep technical investigation requiring specialized expertise",
)

# ---------------------------------------------------------------------------
# Level 2: Escalation Team (middle)
# ---------------------------------------------------------------------------
tech_support = Agent(
    name="Technical Support",
    model=OpenAIResponses(id="gpt-5.6-sol"),
    role="Handle technical issues and coordinate escalations",
)

escalation_team = Team(
    name="Escalation Team",
    model=OpenAIResponses(id="gpt-5.6-sol"),
    members=[tech_support, expert_team],
    add_history_to_context=True,
    role="Handle escalated issues requiring technical expertise",
)

# ---------------------------------------------------------------------------
# Level 1: Support Team (outermost)
# ---------------------------------------------------------------------------
triage_agent = Agent(
    name="Triage Agent",
    model=OpenAIResponses(id="gpt-5.6-sol"),
    role="Initial customer contact and issue classification",
)

support_team = Team(
    name="Support Team",
    model=OpenAIResponses(id="gpt-5.6-sol"),
    members=[triage_agent, escalation_team],
    db=db,
    add_history_to_context=True,
    mode="route",
    show_members_responses=True,
)

# ---------------------------------------------------------------------------
# Run Multi-Turn Support Scenario
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    session_id = "support-case-001"

    # Turn 1: Customer reports issue
    support_team.print_response(
        "Our database queries are timing out. Users cant log in.",
        session_id=session_id,
        stream=True,
    )

    # Turn 2: Follow-up with more details
    support_team.print_response(
        "The timeouts started after we deployed a new feature yesterday.",
        session_id=session_id,
        stream=True,
    )

    # Turn 3: Request resolution status
    support_team.print_response(
        "What have you found so far and whats the recommended fix?",
        session_id=session_id,
        stream=True,
    )
