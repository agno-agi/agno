"""
Configure With Settings
====================================

Configure a Team with settings dataclasses instead of flat parameters.

Each settings class groups related parameters (session, context, team, ...).
The resulting team is identical to one built with the flat parameters, and the
flat parameters keep working as before. If a parameter is set both ways, the
settings object wins and a warning is logged if the values differ.
"""

from agno.agent import Agent
from agno.db.in_memory import InMemoryDb
from agno.models.openai import OpenAIResponses
from agno.settings import ContextSettings, DelegationSettings, SessionSettings
from agno.team import Team

# ---------------------------------------------------------------------------
# Create Members
# ---------------------------------------------------------------------------
researcher = Agent(
    name="Researcher",
    model=OpenAIResponses(id="gpt-5.4"),
    role="Finds and summarizes information.",
)

writer = Agent(
    name="Writer",
    model=OpenAIResponses(id="gpt-5.4"),
    role="Writes a short answer from the research.",
)

# ---------------------------------------------------------------------------
# Create Team
# ---------------------------------------------------------------------------
team = Team(
    name="Settings Team",
    model=OpenAIResponses(id="gpt-5.4"),
    members=[researcher, writer],
    db=InMemoryDb(),
    session_settings=SessionSettings(
        session_id="settings-demo",
        cache_session=True,
    ),
    context_settings=ContextSettings(
        markdown=True,
    ),
    delegation_settings=DelegationSettings(
        share_member_interactions=True,
        store_member_responses=True,
    ),
)

# ---------------------------------------------------------------------------
# Run Team
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # The flat attributes are set exactly as with flat parameters
    print(f"session_id: {team.session_id}")
    print(f"markdown: {team.markdown}")
    print(f"store_member_responses: {team.store_member_responses}")

    team.print_response("In one sentence, why is the sky blue?")
