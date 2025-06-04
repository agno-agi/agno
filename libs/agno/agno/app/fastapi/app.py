import logging
from typing import List, Optional, Union

from fastapi import FastAPI
from fastapi.routing import APIRouter
import uvicorn

from agno.agent.agent import Agent
from agno.app.base import BaseAPIApp
from agno.app.fastapi.async_router import get_async_router
from agno.app.fastapi.sync_router import get_sync_router
from agno.app.playground.settings import PlaygroundSettings
from agno.team.team import Team
from agno.utils.log import log_info

logger = logging.getLogger(__name__)


class FastAPIApp(BaseAPIApp):
    type = "fastapi"
    
    def __init__(
        self,
        agents: Optional[List[Agent]] = None,
        teams: Optional[List[Team]] = None,
        settings: Optional[PlaygroundSettings] = None,
        api_app: Optional[FastAPI] = None,
        router: Optional[APIRouter] = None,
        app_id: Optional[str] = None,
        name: Optional[str] = None,
        description: Optional[str] = None,
        monitoring: bool = True,
    ):
        if not agents and not teams:
            raise ValueError("Either agents or teams must be provided.")

        self.agents: Optional[List[Agent]] = agents
        self.teams: Optional[List[Team]] = teams
        self.settings: PlaygroundSettings = settings or PlaygroundSettings()
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

    def get_router(self) -> APIRouter:
        return get_sync_router(agents=self.agents, teams=self.teams)

    def get_async_router(self) -> APIRouter:
        return get_async_router(agents=self.agents, teams=self.teams)

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
        log_info(f"Starting API on {host}:{port}")

        uvicorn.run(app=app, host=host, port=port, reload=reload, **kwargs)
