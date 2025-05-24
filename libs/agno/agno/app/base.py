from abc import ABC, abstractmethod
from typing import Optional

from fastapi import FastAPI
from fastapi.routing import APIRouter

from agno.agent.agent import Agent
from agno.app.settings import APIAppSettings
from agno.team.team import Team


class BaseAPIApp(ABC):
    def __init__(
        self,
        agent: Optional[Agent] = None,
        team: Optional[Team] = None,
        settings: Optional[APIAppSettings] = None,
        api_app: Optional[FastAPI] = None,
        router: Optional[APIRouter] = None,
    ):
        if not agent and not team:
            raise ValueError("Either agent or team must be provided.")

        if agent and team:
            raise ValueError("Only one of agent or team can be provided.")

        self.agent: Optional[Agent] = agent
        self.team: Optional[Team] = team

        if self.agent is not None:
            agent.initialize_agent()

        if self.team is not None:
            team.initialize_team()
            for member in team.members:
                if isinstance(member, Agent):
                    member.initialize_agent()
                elif isinstance(member, Team):
                    member.initialize_team()

        self.settings: APIAppSettings = settings or APIAppSettings()
        self.api_app: Optional[FastAPI] = api_app
        self.router: Optional[APIRouter] = router

    @abstractmethod
    def get_router(self) -> APIRouter:
        pass

    @abstractmethod
    def get_async_router(self) -> APIRouter:
        pass

    def get_app(self, use_async: bool = True, prefix: str = "") -> FastAPI:
        if not self.api_app:
            self.api_app = FastAPI(
                title=self.settings.title,
                docs_url="/docs" if self.settings.docs_enabled else None,
                redoc_url="/redoc" if self.settings.docs_enabled else None,
                openapi_url="/openapi.json" if self.settings.docs_enabled else None,
            )

        if not self.api_app:
            raise Exception("API App could not be created.")

        if not self.router:
            self.router = APIRouter(prefix=prefix)

        if not self.router:
            raise Exception("API Router could not be created.")

        if use_async:
            self.router.include_router(self.get_async_router())
        else:
            self.router.include_router(self.get_router())

        self.api_app.include_router(self.router)

        return self.api_app
