"""
Agno Demo - AgentOS Entrypoint
================================

Serves all demo agents, teams, and workflows via AgentOS.
"""

from pathlib import Path

from agents.ace import ace
from agents.dash import dash
from agents.dex import dex
from agents.pal import pal
from agents.scout import scout
from agents.seek import seek
from agno.os import AgentOS
from db import get_postgres_db
from registry import registry
from teams.research import research_team
from teams.support import support_team
from workflows.daily_brief import daily_brief_workflow
from workflows.meeting_prep import meeting_prep_workflow

config_path = str(Path(__file__).parent.joinpath("config.yaml"))

agent_os = AgentOS(
    agents=[dash, scout, pal, seek, dex, ace],
    teams=[research_team, support_team],
    workflows=[daily_brief_workflow, meeting_prep_workflow],
    tracing=True,
    scheduler=True,
    registry=registry,
    config=config_path,
    db=get_postgres_db(),
)

app = agent_os.get_app()

if __name__ == "__main__":
    agent_os.serve(app="run:app", reload=True)
