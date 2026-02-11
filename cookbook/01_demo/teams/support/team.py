"""
Support Team
=============

Ace + Scout + Dash working together to handle incoming questions. The team
leader routes questions to the right agents and produces accurate, well-sourced
responses.

Test:
    python -m teams.support.team
"""

from agents.ace import ace
from agents.dash import dash
from agents.scout import scout
from agno.models.openai import OpenAIResponses
from agno.team.team import Team
from db import get_postgres_db

# ---------------------------------------------------------------------------
# Team
# ---------------------------------------------------------------------------
support_team = Team(
    id="support-team",
    name="Support Team",
    model=OpenAIResponses(id="gpt-5.2"),
    db=get_postgres_db(contents_table="support_team_contents"),
    members=[ace, scout, dash],
    respond_directly=True,
    instructions=[
        "You lead a support team that handles incoming questions by routing them to the right specialist:",
        "- Ace: Response agent. Route here for drafting replies to emails, messages, or questions where tone and style matter.",
        "- Scout: Enterprise knowledge navigator. Route here for questions about internal docs, policies, runbooks, architecture.",
        "- Dash: Data analyst. Route here for data questions, SQL queries, metrics, and analytical tasks.",
        "",
        "Routing rules:",
        "- Data/metrics/SQL questions -> Dash",
        "- Internal knowledge/policy/docs questions -> Scout",
        "- Drafting responses/emails/messages -> Ace",
        "- If unclear, prefer Scout for factual questions and Ace for communication tasks.",
        "- If the question needs multiple agents, route to the primary one.",
    ],
    show_members_responses=True,
    markdown=True,
    add_datetime_to_context=True,
)

if __name__ == "__main__":
    test_cases = [
        "What is our company's PTO policy?",
        "Draft a reply to this message: Thanks for the demo. "
        "Can we discuss pricing next week?",
    ]
    for idx, prompt in enumerate(test_cases, start=1):
        print(f"\n--- Support team test case {idx}/{len(test_cases)} ---")
        print(f"Prompt: {prompt}")
        support_team.print_response(prompt, stream=True)
