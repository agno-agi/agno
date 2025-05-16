from typing import List, Optional, Set
from uuid import uuid4

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from fastapi.routing import APIRouter
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request

from agno.agent.agent import Agent
from agno.api.playground import PlaygroundEndpointCreate, create_playground_endpoint
from agno.playground.async_router import get_async_playground_router
from agno.playground.settings import PlaygroundSettings
from agno.playground.sync_router import get_sync_playground_router
from agno.team.team import Team
from agno.utils.log import logger
from agno.workflow.workflow import Workflow


class Playground:
    def __init__(
        self,
        agents: Optional[List[Agent]] = None,
        teams: Optional[List[Team]] = None,
        workflows: Optional[List[Workflow]] = None,
        settings: Optional[PlaygroundSettings] = None,
        api_app: Optional[FastAPI] = None,
        router: Optional[APIRouter] = None,
    ):
        if not agents and not workflows and not teams:
            raise ValueError("Either agents, teams or workflows must be provided.")

        self.agents: Optional[List[Agent]] = agents
        self.workflows: Optional[List[Workflow]] = workflows
        self.teams: Optional[List[Team]] = teams

        if self.agents:
            for agent in self.agents:
                agent.initialize_agent()

        if self.teams:
            for team in self.teams:
                team.initialize_team()
                for member in team.members:
                    if isinstance(member, Agent):
                        member.initialize_agent()
                    elif isinstance(member, Team):
                        member.initialize_team()

        if self.workflows:
            for workflow in self.workflows:
                if not workflow.workflow_id:
                    workflow.workflow_id = generate_id(workflow.name)

        self.settings: PlaygroundSettings = settings or PlaygroundSettings()
        self.api_app: Optional[FastAPI] = api_app
        self.router: Optional[APIRouter] = router
        self.endpoints_created: Set[str] = set()

    def get_router(self) -> APIRouter:
        return get_sync_playground_router(self.agents, self.workflows, self.teams)

    def get_async_router(self) -> APIRouter:
        return get_async_playground_router(self.agents, self.workflows, self.teams)

    def get_app(self, use_async: bool = True, prefix: str = "/v1") -> FastAPI:
        if not self.api_app:
            self.api_app = FastAPI(
                title=self.settings.title,
                docs_url="/docs" if self.settings.docs_enabled else None,
                redoc_url="/redoc" if self.settings.docs_enabled else None,
                openapi_url="/openapi.json" if self.settings.docs_enabled else None,
            )

        if not self.api_app:
            raise Exception("API App could not be created.")

        @self.api_app.exception_handler(HTTPException)
        async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
            return JSONResponse(
                status_code=exc.status_code,
                content={"detail": str(exc.detail)},
            )

        async def general_exception_handler(request: Request, call_next):
            try:
                return await call_next(request)
            except Exception as e:
                return JSONResponse(
                    status_code=e.status_code if hasattr(e, "status_code") else 500,
                    content={"detail": str(e)},
                )

        self.api_app.middleware("http")(general_exception_handler)

        if not self.router:
            self.router = APIRouter(prefix=prefix)

        if not self.router:
            raise Exception("API Router could not be created.")

        if use_async:
            self.router.include_router(self.get_async_router())
        else:
            self.router.include_router(self.get_router())
        self.api_app.include_router(self.router)

        self.api_app.add_middleware(
            CORSMiddleware,
            allow_origins=self.settings.cors_origin_list,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
            expose_headers=["*"],
        )

        return self.api_app

    def create_endpoint(self, endpoint: str, prefix: str = "/v1") -> None:
        if endpoint in self.endpoints_created:
            return

        try:
            logger.info(f"Creating playground endpoint: {endpoint}")
            create_playground_endpoint(
                playground=PlaygroundEndpointCreate(endpoint=endpoint, playground_data={"prefix": prefix})
            )
        except Exception as e:
            logger.error(f"Could not create playground endpoint: {e}")
            logger.error("Please try again.")
            return

        self.endpoints_created.add(endpoint)


def generate_id(name: Optional[str] = None) -> str:
    if name:
        return name.lower().replace(" ", "-").replace("_", "-")
    else:
        return str(uuid4())
