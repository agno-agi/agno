import logging
from typing import List, Optional, Union

import uvicorn
from fastapi import FastAPI
from fastapi.routing import APIRouter

from agno.agent.agent import Agent
from agno.app.base import BaseAPIApp
from agno.app.fastapi.async_router import get_async_router
from agno.app.fastapi.sync_router import get_sync_router
from agno.app.settings import APIAppSettings
from agno.app.utils import generate_id
from agno.team.team import Team
from agno.utils.log import log_info
from agno.workflow.workflow import Workflow

logger = logging.getLogger(__name__)


class FastAPIApp(BaseAPIApp):
    type = "fastapi"

    def __init__(
        self,
        agents: Optional[List[Agent]] = None,
        teams: Optional[List[Team]] = None,
        workflows: Optional[List[Workflow]] = None,
        settings: Optional[APIAppSettings] = None,
        api_app: Optional[FastAPI] = None,
        router: Optional[APIRouter] = None,
        app_id: Optional[str] = None,
        name: Optional[str] = None,
        description: Optional[str] = None,
        monitoring: bool = True,
    ):
        if not agents and not teams and not workflows:
            raise ValueError("Either agents, teams or workflows must be provided.")

        self.agents: Optional[List[Agent]] = agents
        self.teams: Optional[List[Team]] = teams
        self.workflows: Optional[List[Workflow]] = workflows

        self.settings: APIAppSettings = settings or APIAppSettings()
        self.api_app: Optional[FastAPI] = api_app
        self.router: Optional[APIRouter] = router

        self.app_id: Optional[str] = app_id
        self.name: Optional[str] = name
        self.monitoring = monitoring
        self.description = description
        self.set_app_id()

        if self.agents:
            for agent in self.agents:
                if not agent.app_id:
                    agent.app_id = self.app_id
                agent.initialize_agent()

        if self.teams:
            for team in self.teams:
                if not team.app_id:
                    team.app_id = self.app_id
                team.initialize_team()
                for member in team.members:
                    if isinstance(member, Agent):
                        if not member.app_id:
                            member.app_id = self.app_id

                        member.team_id = None
                        member.initialize_agent()
                    elif isinstance(member, Team):
                        member.initialize_team()

        if self.workflows:
            for workflow in self.workflows:
                if not workflow.app_id:
                    workflow.app_id = self.app_id
                if not workflow.workflow_id:
                    workflow.workflow_id = generate_id(workflow.name)

    def get_router(self) -> APIRouter:
        return get_sync_router(agents=self.agents, teams=self.teams, workflows=self.workflows)

    def get_async_router(self) -> APIRouter:
        return get_async_router(agents=self.agents, teams=self.teams, workflows=self.workflows)

    def serve(
        self,
        app: Union[str, FastAPI],
        *,
        host: str = "localhost",
        port: int = 7777,
        reload: bool = False,
        **kwargs,
    ):
        self.set_app_id()
        self.register_app_on_platform()

        if self.agents:
            for agent in self.agents:
                agent.register_agent()

        if self.teams:
            for team in self.teams:
                team.register_team()

        if self.workflows:
            for workflow in self.workflows:
                workflow.register_workflow()
        log_info(f"Starting API on {host}:{port}")

        uvicorn.run(app=app, host=host, port=port, reload=reload, **kwargs)
