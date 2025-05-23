import logging
from typing import Optional, Set

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from fastapi.routing import APIRouter
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request

from agno.agent.agent import Agent
from agno.app.fastapi.async_router import get_async_router
from agno.app.fastapi.sync_router import get_sync_router
from agno.app.settings import APIAppSettings
from agno.app.utils import generate_id
from agno.team.team import Team

logger = logging.getLogger(__name__)


class FastAPIApp:
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

        if self.agent:
            if not self.agent.agent_id:
                self.agent.agent_id = generate_id(self.agent.name)

        if self.team:
            if not self.team.team_id:
                self.team.team_id = generate_id(self.team.name)

        self.settings: APIAppSettings = settings or APIAppSettings()
        self.api_app: Optional[FastAPI] = api_app
        self.router: Optional[APIRouter] = router
        self.endpoints_created: Set[str] = set()

    def get_router(self) -> APIRouter:
        return get_sync_router(agent=self.agent, team=self.team)

    def get_async_router(self) -> APIRouter:
        return get_async_router(agent=self.agent, team=self.team)

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
            allow_origins=["*"],
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
            expose_headers=["*"],
        )

        return self.api_app
