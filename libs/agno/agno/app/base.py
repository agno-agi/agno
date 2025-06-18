from abc import ABC, abstractmethod
from os import getenv
from typing import Any, Dict, Optional, Union
from uuid import uuid4

import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.routing import APIRouter
from starlette.middleware.cors import CORSMiddleware

from agno.agent.agent import Agent
from agno.api.app import AppCreate, create_app
from agno.app.settings import APIAppSettings
from agno.team.team import Team
from agno.utils.log import log_debug, log_info


class BaseAPIApp(ABC):
    type: Optional[str] = None

    def __init__(
        self,
        agent: Optional[Agent] = None,
        team: Optional[Team] = None,
        settings: Optional[APIAppSettings] = None,
        api_app: Optional[FastAPI] = None,
        router: Optional[APIRouter] = None,
        monitoring: bool = True,
        app_id: Optional[str] = None,
        name: Optional[str] = None,
        description: Optional[str] = None,
        version: Optional[str] = None,
    ):
        if not agent and not team:
            raise ValueError("Either agent or team must be provided.")

        if agent and team:
            raise ValueError("Only one of agent or team can be provided.")

        self.agent: Optional[Agent] = agent
        self.team: Optional[Team] = team
        self.settings: APIAppSettings = settings or APIAppSettings()
        self.api_app: Optional[FastAPI] = api_app
        self.router: Optional[APIRouter] = router
        self.monitoring = monitoring
        self.app_id: Optional[str] = app_id
        self.name: Optional[str] = name
        self.description = description
        self.version = version
        self.set_app_id()

        if self.agent:
            if not self.agent.app_id:
                self.agent.app_id = self.app_id
            self.agent.initialize_agent()

        if self.team:
            if not self.team.app_id:
                self.team.app_id = self.app_id
            self.team.initialize_team()
            for member in self.team.members:
                if isinstance(member, Agent):
                    if not member.app_id:
                        member.app_id = self.app_id
                    member.team_id = None
                    member.initialize_agent()
                elif isinstance(member, Team):
                    member.initialize_team()

    def set_app_id(self) -> str:
        # If app_id is already set, keep it instead of overriding with UUID
        if self.app_id is None:
            self.app_id = str(uuid4())

        # Don't override existing app_id
        return self.app_id

    def _set_monitoring(self) -> None:
        monitor_env = getenv("AGNO_MONITOR")
        if monitor_env is not None:
            self.monitoring = monitor_env.lower() == "true"

    @abstractmethod
    def get_router(self) -> APIRouter:
        raise NotImplementedError("get_router must be implemented")

    @abstractmethod
    def get_async_router(self) -> APIRouter:
        raise NotImplementedError("get_async_router must be implemented")

    def get_app(self, use_async: bool = True, prefix: str = "") -> FastAPI:
        if not self.api_app:
            kwargs = {
                "title": self.settings.title,
            }
            if self.version:
                kwargs["version"] = self.version
            if self.settings.docs_enabled:
                kwargs["docs_url"] = "/docs"
                kwargs["redoc_url"] = "/redoc"
                kwargs["openapi_url"] = "/openapi.json"

            self.api_app = FastAPI(
                **kwargs,  # type: ignore
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

        if self.agent:
            self.agent.register_agent()
        if self.team:
            self.team.register_team()
        log_info(f"Starting API on {host}:{port}")

        uvicorn.run(app=app, host=host, port=port, reload=reload, **kwargs)

    def register_app_on_platform(self) -> None:
        self._set_monitoring()
        if not self.monitoring:
            return

        try:
            log_debug(f"Creating app on Platform: {self.name}, {self.app_id}")
            create_app(app=AppCreate(name=self.name, app_id=self.app_id, config=self.to_dict()))
        except Exception as e:
            log_debug(f"Could not create Agent app: {e}")
        log_debug(f"Agent app created: {self.name}, {self.app_id}")

    def to_dict(self) -> Dict[str, Any]:
        payload = {
            "agents": [
                {
                    **self.agent.get_agent_config_dict(),
                    "agent_id": self.agent.agent_id,
                    "team_id": self.agent.team_id,
                }
            ]
            if self.agent
            else None,
            "teams": [
                {
                    **self.team.to_platform_dict(),
                    "team_id": self.team.team_id,
                }
            ]
            if self.team
            else None,
            "type": self.type,
            "description": self.description,
        }
        payload = {k: v for k, v in payload.items() if v is not None}
        return payload
