import asyncio
import threading
from os import getenv
from typing import Any, Dict, List, Optional, Set, Union
from urllib.parse import quote
from uuid import uuid4

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from fastapi.routing import APIRouter
from rich import box
from rich.panel import Panel
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request

from agno.agent.agent import Agent
from agno.api.playground import PlaygroundEndpointCreate, create_playground_endpoint
from agno.cli.console import console
from agno.cli.settings import agno_cli_settings
from agno.playground.async_router import get_async_playground_router
from agno.playground.settings import PlaygroundSettings
from agno.playground.sync_router import get_sync_playground_router
from agno.team.team import Team
from agno.utils.log import log_debug, logger
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
        app_id: Optional[str] = None,
        name: Optional[str] = None,
        description: Optional[str] = None,
        monitoring: bool = False,
    ):
        if not agents and not workflows and not teams:
            raise ValueError("Either agents, teams or workflows must be provided.")

        self.agents: Optional[List[Agent]] = agents
        self.workflows: Optional[List[Workflow]] = workflows
        self.teams: Optional[List[Team]] = teams
        self.settings: PlaygroundSettings = settings or PlaygroundSettings()
        self.api_app: Optional[FastAPI] = api_app
        self.router: Optional[APIRouter] = router
        self.endpoints_created: Dict[str, Dict[str, str]] = {}
        self.app_id: Optional[str] = app_id
        self.name: Optional[str] = name
        self.monitoring = monitoring
        self.description = description
        if self.agents:
            for agent in self.agents:
                if not agent.agent_id:
                    agent.agent_id = generate_id(agent.name) 
                if not agent.app_id:
                    agent.app_id = self.app_id

        if self.teams:
            for team in self.teams:
                if not team.team_id:
                    team.team_id = generate_id(team.name)
                if not team.app_id:
                    team.app_id = self.app_id

        if self.workflows:
            for workflow in self.workflows:
                if not workflow.workflow_id:
                    workflow.workflow_id = generate_id(workflow.name)

    def set_app_id(self) -> str:
        # If app_id is already set, keep it instead of overriding with UUID
        if self.app_id is None:
            app_id_parts = []
            if self.agents and self.agents is not None:
                app_id_parts.append(f"agent-{self.agents[0].agent_id}")
            if self.teams and self.teams is not None:
                app_id_parts.append(f"team-{self.teams[0].team_id}")
            if self.workflows and self.workflows is not None:
                app_id_parts.append(f"workflow-{self.workflows[0].workflow_id}")

            if app_id_parts:
                self.app_id = "-".join(app_id_parts)

        # Don't override existing app_id
        return self.app_id

    def _set_monitoring(self) -> None:
        """Override monitoring and telemetry settings based on environment variables."""

        # Only override if the environment variable is set
        monitor_env = getenv("AGNO_MONITOR")
        if monitor_env is not None:
            self.monitoring = monitor_env.lower() == "true"

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


        # asyncio.create_task(self.aregister_app_on_platform())
        return self.api_app

    def register_playground_app(
        self,
        app: Union[str, FastAPI],
        *,
        scheme: str = "http",
        host: str = "localhost",
        port: int = 7777,
        reload: bool = False,
        prefix="/v1",
        **kwargs,
    ):
        import uvicorn

        try:
            create_playground_endpoint(
                playground=PlaygroundEndpointCreate(
                    endpoint=f"{scheme}://{host}:{port}", playground_data={"prefix": prefix}
                ),
            )
        except Exception as e:
            logger.error(f"Could not create playground endpoint: {e}")
            logger.error("Please try again.")
            return

        logger.info(f"Starting playground on {scheme}://{host}:{port}")
        # Encode the full endpoint (host:port)
        encoded_endpoint = quote(f"{host}:{port}")
        self.endpoints_created = f"{scheme}://{host}:{port}"

        
        # Create a panel with the playground URL
        url = f"{agno_cli_settings.playground_url}?endpoint={encoded_endpoint}"
        panel = Panel(
            f"[bold green]Playground URL:[/bold green] [link={url}]{url}[/link]",
            title="Agent Playground",
            expand=False,
            border_style="cyan",
            box=box.HEAVY,
            padding=(2, 2),
        )

        # Print the panel
        console.print(panel)
        print(app, "this is app")
        self.set_app_id()   
        thread = threading.Thread(target=self.register_app_on_platform)
        thread.start()
        if self.agents:
            for agent in self.agents:
                t1 = threading.Thread(target=agent.register_agent_on_platform)
                t1.start()
        if self.teams:
            for team in self.teams:
                t2 = threading.Thread(target=team._register_team_on_platform)
                t2.start()
        uvicorn.run(app=app, host=host, port=port, reload=reload, **kwargs)

    def register_app_on_platform(self) -> None:
        self._set_monitoring()
        if not self.monitoring:
            return

        from agno.api.app import AppCreate, create_app

        try:
            print(f"Creating Agent on Platform: {self.name}, {self.app_id}")
            # print("HERE", self.playground_to_dict())
            create_app(app=AppCreate(name=self.name, app_id=self.app_id, config=self.playground_to_dict()))
        except Exception as e:
            log_debug(f"Could not create Agent app: {e}")
        log_debug(f"Agent app created: {self.name}, {self.app_id}")

    async def aregister_app_on_platform(self) -> None:
        self._set_monitoring()
        if not self.monitoring:
            return

        from agno.api.app import AppCreate, acreate_app

        try:
            log_debug(f"Creating App on Platform: {self.name}, {self.agent_id}, {self.team_id},")
            await acreate_app(app=AppCreate(name=self.name, app_id=self.app_id, config=self.playground_to_dict()))

        except Exception as e:
            log_debug(f"Could not create App: {e}")
        log_debug(f"App created: {self.name}, {self.agent_id}, {self.team_id},")

    def playground_to_dict(self) -> Dict[str, Any]:
        payload = {
            "agents": [
                {
                    **agent.get_agent_config_dict(),
                    "agent_id": agent.agent_id,
                    "team_id": agent.team_id
                } for agent in self.agents
            ] if self.agents else [],
            "teams": [
                {
                    **team.to_platform_dict(),
                    "team_id": team.team_id
                } for team in self.teams
            ] if self.teams else [],
            "endpoint": self.endpoints_created,
            "type": "playground",
            "description": self.description
        }
        print(payload, "this is payload")
        return payload


def generate_id(name: Optional[str] = None) -> str:
    if name:
        return name.lower().replace(" ", "-").replace("_", "-")
    else:
        return str(uuid4())
