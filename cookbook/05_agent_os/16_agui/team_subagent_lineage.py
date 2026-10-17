"""
Attribute Team member work over AG-UI
=====================================

A Team run mixes the leader's own output with the output of every member it
delegated to. By default AG-UI streams all of it as the team's work, which is
what released clients already expect. Set subagent_visibility="attributed" and
the same run also carries lineage: SUBAGENT_STARTED, then SUBAGENT_FINISHED or
SUBAGENT_ERROR, per delegation, and a subagentRunId on the events that carry a
member's own output, so a client can label its messages, tool calls and
reasoning per member.
Session state events are left unattributed on purpose: a team's session state is
one shared document, so a client filtering by member must not lose a change a
member's tool made.

The same team is mounted twice so the two streams can be compared side by side.
Send the same prompt to each mount, but give each request its own threadId, for
example "lineage-attributed" for /lineage and "lineage-inline" for
/lineage-inline. A threadId becomes the Agno session id, so reusing one across
both mounts is guaranteed to do one thing: the second request continues the
first request's session, that session's history included. Whether the leader
delegates again from there is the model's decision, not something this file can
promise, but the answer is already in the history it reads, so it will most
likely reply straight from it and leave the second stream with little or no
member work to compare.

Prerequisites: OPENAI_API_KEY, internet access, and ag-ui-protocol 0.1.21 or newer
Run: .venvs/demo/bin/python cookbook/05_agent_os/16_agui/team_subagent_lineage.py
Try: POST one prompt per threadId to http://localhost:7777/lineage/agui, then /lineage-inline/agui
"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS
from agno.os.interfaces.agui import AGUI
from agno.team import Team
from agno.tools.websearch import WebSearchTools

# ---------------------------------------------------------------------------
# Create Team and Interface Mounts
# ---------------------------------------------------------------------------

db = SqliteDb(
    id="agui-lineage-db",
    db_file="tmp/agui_team_lineage.db",
)

researcher = Agent(
    id="lineage-researcher",
    name="Researcher",
    role="Find current, relevant source material.",
    model=OpenAIResponses(id="gpt-5.6-luna"),
    db=db,
    tools=[WebSearchTools()],
    instructions="Search the web, prefer primary sources, and return concise findings with URLs.",
)

writer = Agent(
    id="lineage-writer",
    name="Writer",
    role="Turn research into a short, readable brief.",
    model=OpenAIResponses(id="gpt-5.6-luna"),
    db=db,
    instructions="Synthesize supplied research without inventing unsupported facts.",
)

research_team = Team(
    id="lineage-research-team",
    name="AG-UI Lineage Team",
    model=OpenAIResponses(id="gpt-5.6-luna"),
    db=db,
    members=[researcher, writer],
    instructions=[
        "Delegate research to the Researcher and synthesis to the Writer.",
        "Return a concise brief with source links.",
    ],
)

agent_os = AgentOS(
    id="agui-lineage-os",
    description="One Team served twice, with and without member attribution.",
    teams=[research_team],
    interfaces=[
        # Members are announced, and the events carrying a member's own output
        # are tagged with its run id. Session state events are not, as above.
        AGUI(team=research_team, prefix="/lineage", subagent_visibility="attributed"),
        # The default: member work streams as the team's own.
        AGUI(team=research_team, prefix="/lineage-inline"),
    ],
)
app = agent_os.get_app()

# ---------------------------------------------------------------------------
# Run Multi-Interface Server
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    agent_os.serve(app=app)
