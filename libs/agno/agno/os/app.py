from os import getenv
from typing import Dict, List, Optional, Tuple, Union
from uuid import uuid4

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from rich import box
from rich.panel import Panel
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request

from agno.agent.agent import Agent
from agno.app.utils import generate_id
from agno.cli.console import console
from agno.os.apps import (
    EvalApp,
    KnowledgeApp,
    MemoryApp,
    MetricsApp,
    SessionApp,
)
from agno.os.apps.base import BaseApp
from agno.os.interfaces.base import BaseInterface
from agno.os.router import get_base_router
from agno.os.settings import AgnoAPISettings
from agno.team.team import Team
from agno.utils.log import log_debug, log_info, log_warning
from agno.workflow.v2.workflow import Workflow


class AgentOS:
    host_url: Optional[str] = None

    def __init__(
        self,
        os_id: Optional[str] = None,
        description: Optional[str] = None,
        agents: Optional[List[Agent]] = None,
        teams: Optional[List[Team]] = None,
        workflows: Optional[List[Workflow]] = None,
        interfaces: Optional[List[BaseInterface]] = None,
        apps: Optional[List[BaseApp]] = None,
        settings: Optional[AgnoAPISettings] = None,
        fastapi_app: Optional[FastAPI] = None,
        monitoring: bool = True,
    ):
        if not agents and not workflows and not teams:
            raise ValueError("Either agents, teams or workflows must be provided.")

        self.agents: Optional[List[Agent]] = agents
        self.workflows: Optional[List[Workflow]] = workflows
        self.teams: Optional[List[Team]] = teams

        self.settings: AgnoAPISettings = settings or AgnoAPISettings()
        self.fastapi_app: Optional[FastAPI] = fastapi_app

        self.interfaces = interfaces or []
        self.apps = apps or []

        self.os_id: Optional[str] = os_id
        self.monitoring = monitoring
        self.description = description

        self.interfaces_loaded: List[Tuple[str, str]] = []
        self.apps_loaded: List[Tuple[str, str]] = []

        self.set_os_id()

        if self.agents:
            for agent in self.agents:
                if not agent.os_id:
                    agent.os_id = self.os_id
                agent.initialize_agent()

                # Required for the built-in routes to work
                agent.store_events = True

        if self.teams:
            for team in self.teams:
                if not team.os_id:
                    team.os_id = self.os_id
                team.initialize_team()

                # Required for the built-in routes to work
                team.store_events = True

                for member in team.members:
                    if isinstance(member, Agent):
                        if not member.os_id:
                            member.os_id = self.os_id

                        member.team_id = None
                        member.initialize_agent()
                    elif isinstance(member, Team):
                        member.initialize_team()

        if self.workflows:
            for workflow in self.workflows:
                if not workflow.os_id:
                    workflow.os_id = self.os_id
                if not workflow.workflow_id:
                    workflow.workflow_id = generate_id(workflow.name)

    def _auto_discover_apps(self) -> List[BaseApp]:
        """Auto-discover apps from agents, teams, and workflows."""
        discovered_apps: List[BaseApp] = []

        seen_components: Dict[str, set] = {
            "session": set(),
            "knowledge": set(),
            "memory": set(),
            "metrics": set(),
            "eval": set(),
        }

        # Helper function to add unique components
        def _add_unique_component(component_type: str, component_id: str):
            if component_id not in seen_components[component_type]:
                seen_components[component_type].add(component_id)
                return True
            return False

        def _auto_discover_entity_apps(entity: Union[Agent, Team]) -> List[BaseApp]:
            if entity.db:
                # Memory app
                if _add_unique_component("memory", f"{entity.db.memory_table_name}"):
                    discovered_apps.append(MemoryApp(db=entity.db))

                # Session app
                if entity.db.session_table_name:
                    if _add_unique_component("session", f"{entity.db.session_table_name}"):
                        discovered_apps.append(SessionApp(db=entity.db))

                # Metrics app
                if entity.db.metrics_table_name:
                    if _add_unique_component("metrics", f"{entity.db.metrics_table_name}"):
                        discovered_apps.append(MetricsApp(db=entity.db))

                # Eval app
                if entity.db.eval_table_name:
                    if _add_unique_component("eval", f"{entity.db.eval_table_name}"):
                        discovered_apps.append(EvalApp(db=entity.db))

            # Knowledge app
            if entity.knowledge:
                if not entity.knowledge.contents_db:
                    log_warning("Knowledge contents_db is required to use knowledge inside AgentOS.")
                    return []

                db = entity.knowledge.contents_db
                if _add_unique_component("knowledge", f"{db.knowledge_table_name}") and entity.knowledge:
                    discovered_apps.append(KnowledgeApp(knowledge=entity.knowledge))

            return discovered_apps

        # Process agents
        if self.agents:
            for agent in self.agents:
                _auto_discover_entity_apps(agent)

        # Process teams
        if self.teams:
            for team in self.teams:
                _auto_discover_entity_apps(team)
                for member in team.members:
                    _auto_discover_entity_apps(member)

        # Process workflows
        # TODO: Implement workflow app discovery

        # Log discovered apps
        if discovered_apps:
            for app in discovered_apps:
                log_debug(f"{app.type.title()} App added to AgentOS")

        return discovered_apps

    def set_os_id(self) -> str:
        # If os_id is already set, keep it instead of overriding with UUID
        if self.os_id is None:
            self.os_id = str(uuid4())

        return self.os_id

    def _set_monitoring(self) -> None:
        """Override monitoring and telemetry settings based on environment variables."""

        # Only override if the environment variable is set
        monitor_env = getenv("AGNO_MONITOR")
        if monitor_env is not None:
            self.monitoring = monitor_env.lower() == "true"

    def get_app(self) -> FastAPI:
        if not self.fastapi_app:
            self.fastapi_app = FastAPI(
                title=self.settings.title,
                docs_url="/docs" if self.settings.docs_enabled else None,
                redoc_url="/redoc" if self.settings.docs_enabled else None,
                openapi_url="/openapi.json" if self.settings.docs_enabled else None,
            )

        if not self.fastapi_app:
            raise Exception("API App could not be created.")

        @self.fastapi_app.exception_handler(HTTPException)
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
                    status_code=e.status_code if hasattr(e, "status_code") else 500,  # type: ignore
                    content={"detail": str(e)},
                )

        self.fastapi_app.middleware("http")(general_exception_handler)

        self.fastapi_app.include_router(get_base_router(self, settings=self.settings))

        for interface in self.interfaces:
            interface_router = interface.get_router()
            self.fastapi_app.include_router(interface_router)
            self.interfaces_loaded.append((interface.type, interface.router_prefix))

        # Auto-discover apps if none are provided
        if not self.apps:
            self.apps = self._auto_discover_apps()

        app_index_map: Dict[str, int] = {}
        for app in self.apps:
            app_index_map[app.type] = app_index_map.get(app.type, 0) + 1

            # Passing contextual agents and teams to the eval app, so it can use them to run evals.
            if app.type == "eval":
                app_router = app.get_router(
                    index=app_index_map[app.type],
                    agents=self.agents,
                    teams=self.teams,
                    settings=self.settings,
                )
            else:
                app_router = app.get_router(index=app_index_map[app.type], settings=self.settings)

            self.fastapi_app.include_router(app_router)
            self.apps_loaded.append((app.type, app.router_prefix))

        self.fastapi_app.add_middleware(
            CORSMiddleware,
            allow_origins=self.settings.cors_origin_list,  # type: ignore
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
            expose_headers=["*"],
        )

        return self.fastapi_app

    def serve(
        self,
        app: Union[str, FastAPI],
        *,
        host: str = "localhost",
        port: int = 7777,
        reload: bool = False,
        **kwargs,
    ):
        import uvicorn

        full_host = host

        log_info(f"Starting AgentOS on {full_host}:{port}")

        self.host_url = f"{full_host}:{port}"

        # Create a panel with the Home and interface URLs
        panels = []
        encoded_endpoint = f"http://{full_host}:{port}/home"
        panels.append(
            Panel(
                f"[bold green]Home URL:[/bold green] {encoded_endpoint}",
                title="Home",
                expand=False,
                border_style="green",
                box=box.HEAVY,
                padding=(2, 2),
            )
        )
        for interface_type, interface_prefix in self.interfaces_loaded:
            if interface_type == "whatsapp":
                encoded_endpoint = f"{full_host}:{port}{interface_prefix}"
                panels.append(
                    Panel(
                        f"[bold cyan]Whatsapp URL:[/bold cyan] {encoded_endpoint}",
                        title="Whatsapp",
                        expand=False,
                        border_style="cyan",
                        box=box.HEAVY,
                        padding=(2, 2),
                    )
                )
            elif interface_type == "slack":
                encoded_endpoint = f"{full_host}:{port}{interface_prefix}"
                panels.append(
                    Panel(
                        f"[bold purple]Slack URL:[/bold purple] {encoded_endpoint}",
                        title="Slack",
                        expand=False,
                        border_style="purple",
                        box=box.HEAVY,
                        padding=(2, 2),
                    )
                )

        # Print the panel
        for panel in panels:
            console.print(panel)

        uvicorn.run(app=app, host=host, port=port, reload=reload, **kwargs)
