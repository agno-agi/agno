"""
Agno Demo - AgentOS Entrypoint
================================

Serves all demo agents, teams, and workflows via AgentOS.

Run:
    .venvs/demo/bin/python cookbook/demo/run.py

Then connect to http://localhost:7777 via os.agno.com
"""

from pathlib import Path

from agents.ace import ace

# Agents
from agents.dash import dash, reasoning_dash
from agents.dex import dex
from agents.pal import pal
from agents.scout import reasoning_scout, scout
from agents.seek import reasoning_seek, seek
from agno.os import AgentOS

# Config
from db import get_postgres_db
from registry import registry

# Teams
from teams.research import research_team
from teams.support import support_team

# Workflows
from workflows.daily_brief import daily_brief_workflow
from workflows.meeting_prep import meeting_prep_workflow

config_path = str(Path(__file__).parent.joinpath("config.yaml"))

agent_os = AgentOS(
    agents=[
        dash,
        reasoning_dash,
        scout,
        reasoning_scout,
        pal,
        seek,
        reasoning_seek,
        dex,
        ace,
    ],
    teams=[
        research_team,
        support_team,
    ],
    workflows=[
        daily_brief_workflow,
        meeting_prep_workflow,
    ],
    registry=registry,
    config=config_path,
    db=get_postgres_db(),
    tracing=True,
)

app = agent_os.get_app()

if __name__ == "__main__":
    agent_os.serve(app="run:app", reload=True)
