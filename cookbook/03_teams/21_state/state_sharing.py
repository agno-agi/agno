"""
State Sharing
=============================

Demonstrates sharing session state and member interactions across team members.
"""

from agno.agent import Agent
from agno.db.in_memory import InMemoryDb
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.team import Team, TeamMode
from agno.tools.websearch import WebSearchTools

# ---------------------------------------------------------------------------
# Create Members
# ---------------------------------------------------------------------------
user_advisor = Agent(
    role="User Advisor",
    description="You answer questions related to the user.",
    model=OpenAIResponses(id="gpt-5.2"),
    instructions="User's name is {user_name} and age is {age}",
)

web_research_agent = Agent(
    name="Web Research Agent",
    model=OpenAIResponses(id="gpt-5-mini"),
    tools=[WebSearchTools()],
    instructions="You are a web research agent that can answer questions from the web.",
)

report_agent = Agent(
    name="Report Agent",
    model=OpenAIResponses(id="gpt-5-mini"),
    instructions="You are a report agent that can write a report from the web research.",
)

# ---------------------------------------------------------------------------
# Create Team
# ---------------------------------------------------------------------------
state_team = Team(
    db=InMemoryDb(),
    model=OpenAIResponses(id="gpt-5.2"),
    instructions="You are a team that answers questions related to the user. Delegate to the member agent to address user requests or answer any questions about the user.",
    members=[user_advisor],
    mode=TeamMode.route,
)

interaction_team = Team(
    model=OpenAIResponses(id="gpt-5-mini"),
    db=SqliteDb(db_file="tmp/agents.db"),
    members=[web_research_agent, report_agent],
    share_member_interactions=True,
    instructions=[
        "You are a team of agents that can research the web and write a report.",
        "First, research the web for information about the topic.",
        "Then, use your report agent to write a report from the web research.",
    ],
    show_members_responses=True,
    debug_mode=True,
)

# ---------------------------------------------------------------------------
# Run Team
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    state_team.print_response(
        "Write a short poem about my name and age",
        session_id="session_1",
        user_id="user_1",
        session_state={"user_name": "John", "age": 30},
        add_session_state_to_context=True,
    )

    state_team.print_response(
        "How old am I?",
        session_id="session_1",
        user_id="user_1",
        add_session_state_to_context=True,
    )

    interaction_team.print_response("How are LEDs made?")
