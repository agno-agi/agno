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
from agno.os.interfaces.base import BaseInterface
from agno.os.managers import (
    EvalManager,
    KnowledgeManager,
    MemoryManager,
    MetricsManager,
    SessionManager,
)
from agno.os.managers.base import BaseManager
from agno.os.router import get_base_router
from agno.os.settings import AgnoAPISettings
from agno.team.team import Team
from agno.utils.log import log_debug, log_info, log_warning
from agno.workflow.workflow import Workflow


class AgentOS:
    host_url: Optional[str] = None

    def __init__(
        self,
        os_id: Optional[str] = None,
        name: Optional[str] = None,
        description: Optional[str] = None,
        agents: Optional[List[Agent]] = None,
        teams: Optional[List[Team]] = None,
        workflows: Optional[List[Workflow]] = None,
        interfaces: Optional[List[BaseInterface]] = None,
        managers: Optional[List[BaseManager]] = None,
        settings: Optional[AgnoAPISettings] = None,
        api_app: Optional[FastAPI] = None,
        monitoring: bool = True,
    ):
        if not agents and not workflows and not teams:
            raise ValueError("Either agents, teams or workflows must be provided.")

        self.agents: Optional[List[Agent]] = agents
        self.workflows: Optional[List[Workflow]] = workflows
        self.teams: Optional[List[Team]] = teams

        self.settings: AgnoAPISettings = settings or AgnoAPISettings()
        self.api_app: Optional[FastAPI] = api_app

        self.interfaces = interfaces or []
        self.managers = managers or []

        self.os_id: Optional[str] = os_id
        self.name: Optional[str] = name
        self.monitoring = monitoring
        self.description = description

        self.interfaces_loaded: List[Tuple[str, str]] = []
        self.managers_loaded: List[Tuple[str, str]] = []

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

    def _auto_discover_managers(self) -> List[BaseManager]:
        """Auto-discover managers from agents, teams, and workflows."""
        discovered_managers: List[BaseManager] = []

        seen_components: Dict[str, set] = {
            "session": set(),
            "knowledge": set(),
            "memory": set(),
            "metrics": set(),
            "eval": set(),
        }

        # Helper function to add unique components
        def add_unique_component(component_type: str, component_id: str):
            if component_id not in seen_components[component_type]:
                seen_components[component_type].add(component_id)
                return True
            return False

        # Process agents
        if self.agents:
            for agent in self.agents:
                if hasattr(agent, "memory") and agent.memory and hasattr(agent.memory, "db") and agent.memory.db:
                    memory_id = id(agent.memory)
                    db_id = id(agent.memory.db)

                    # Memory manager
                    if add_unique_component("memory", str(memory_id)):
                        discovered_managers.append(MemoryManager(memory=agent.memory))

                    # Session manager
                    if agent.memory.db.session_table_name:
                        if add_unique_component("session", str(db_id)):
                            discovered_managers.append(SessionManager(db=agent.memory.db))

                    # Metrics manager
                    if agent.memory.db.metrics_table_name:
                        if add_unique_component("metrics", str(db_id)):
                            discovered_managers.append(MetricsManager(db=agent.memory.db))

                    # Eval manager
                    if agent.memory.db.eval_table_name:
                        if add_unique_component("eval", str(db_id)):
                            discovered_managers.append(EvalManager(db=agent.memory.db))

                # Knowledge manager
                if hasattr(agent, "knowledge") and agent.knowledge:
                    knowledge_id = id(agent.knowledge)
                    if add_unique_component("knowledge", str(knowledge_id)):
                        discovered_managers.append(KnowledgeManager(knowledge=agent.knowledge))

        # Process teams
        if self.teams:
            for team in self.teams:
                if hasattr(team, "memory") and team.memory and hasattr(team.memory, "db") and team.memory.db:
                    memory_id = id(team.memory)
                    db_id = id(team.memory.db)

                    # Memory manager
                    if add_unique_component("memory", str(memory_id)):
                        discovered_managers.append(MemoryManager(memory=team.memory))

                    # Session manager
                    if team.memory.db.session_table_name:
                        if add_unique_component("session", str(db_id)):
                            discovered_managers.append(SessionManager(db=team.memory.db))

                    # Metrics manager
                    if team.memory.db.metrics_table_name:
                        if add_unique_component("metrics", str(db_id)):
                            discovered_managers.append(MetricsManager(db=team.memory.db))

                    # Eval manager
                    if team.memory.db.eval_table_name:
                        if add_unique_component("eval", str(db_id)):
                            discovered_managers.append(EvalManager(db=team.memory.db))

                # Knowledge manager
                if hasattr(team, "knowledge") and team.knowledge:
                    knowledge_id = id(team.knowledge)
                    if add_unique_component("knowledge", str(knowledge_id)):
                        discovered_managers.append(KnowledgeManager(knowledge=team.knowledge))

        # Process workflows
        # TODO: Implement workflow manager discovery

        # Log discovered managers
        if discovered_managers:
            for manager in discovered_managers:
                log_debug(f"{manager.type.title()} Manager added to AgentOS")

        return discovered_managers

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
                    status_code=e.status_code if hasattr(e, "status_code") else 500,  # type: ignore
                    content={"detail": str(e)},
                )

        self.api_app.middleware("http")(general_exception_handler)

        # Attach base router
        self.api_app.include_router(get_base_router(self))

        for interface in self.interfaces:
            self.api_app.include_router(interface.get_router())
            self.interfaces_loaded.append((interface.type, interface.router_prefix))

        # Auto-discover managers if none are provided
        if not self.managers:
            self.managers = self._auto_discover_managers()

        manager_index_map: Dict[str, int] = {}
        for manager in self.managers:
            manager_index_map[manager.type] = manager_index_map.get(manager.type, 0) + 1
            self.api_app.include_router(manager.get_router(index=manager_index_map[manager.type]))
            self.managers_loaded.append((manager.type, manager.router_prefix))

        self.api_app.add_middleware(
            CORSMiddleware,
            allow_origins=self.settings.cors_origin_list,  # type: ignore
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
        import uvicorn

        full_host = host

        log_info(f"Starting AgentOS on {full_host}:{port}")

        self.host_url = f"{full_host}:{port}"

        # Create a panel with the Home and interface URLs
        panels = []
        encoded_endpoint = f"{full_host}:{port}/home"
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

        managers_panel_text = ""
        for manager_type, manager_prefix in self.managers_loaded:
            encoded_endpoint = f"{full_host}:{port}{manager_prefix}"
            if manager_type == "session":
                managers_panel_text += f"[bold green]Sessions Manager:[/bold green] {encoded_endpoint}\n"
            elif manager_type == "knowledge":
                managers_panel_text += f"[bold green]Knowledge Manager:[/bold green] {encoded_endpoint}\n"
            elif manager_type == "memory":
                managers_panel_text += f"[bold green]Memory Manager:[/bold green] {encoded_endpoint}\n"
            elif manager_type == "eval":
                managers_panel_text += f"[bold green]Evals Manager:[/bold green] {encoded_endpoint}\n"
            elif manager_type == "metrics":
                managers_panel_text += f"[bold green]Metrics Manager:[/bold green] {encoded_endpoint}\n"
            else:
                log_warning(f"Unknown manager type: {manager_type}")

        if managers_panel_text:
            managers_panel_text = managers_panel_text.strip()
            panels.append(
                Panel(
                    managers_panel_text,
                    title="Configured Managers",
                    expand=False,
                    border_style="bright_cyan",
                    box=box.HEAVY,
                    padding=(2, 2),
                )
            )

        # Print the panel
        for panel in panels:
            console.print(panel)

        uvicorn.run(app=app, host=host, port=port, reload=reload, **kwargs)
