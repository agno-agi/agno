from os import getenv
from typing import Dict, List, Optional, Tuple, Union
from uuid import uuid4

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from rich import box
from rich.panel import Panel
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request

from agno.agent.agent import Agent
from agno.api.playground import PlaygroundEndpointCreate
from agno.app.utils import generate_id
from agno.cli.console import console
from agno.cli.settings import agno_cli_settings
from agno.os.managers.base import BaseManager
from agno.os.console import Console
from agno.os.interfaces.base import BaseInterface
from agno.os.router import get_base_router, get_console_router
from agno.os.settings import AgnoAPISettings
from agno.team.team import Team
from agno.utils.log import log_info, log_warning
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
        console: Optional[Console] = None,
        interfaces: Optional[List[BaseInterface]] = None,
        apps: Optional[List[BaseManager]] = None,
        settings: Optional[AgnoAPISettings] = None,
        api_app: Optional[FastAPI] = None,
        monitoring: bool = True,
    ):
        if not agents and not workflows and not teams:
            raise ValueError("Either agents, teams or workflows must be provided.")

        self.agents: Optional[List[Agent]] = agents
        self.workflows: Optional[List[Workflow]] = workflows
        self.teams: Optional[List[Team]] = teams
        
        self.console = console

        self.settings: AgnoAPISettings = settings or AgnoAPISettings()
        self.api_app: Optional[FastAPI] = api_app

        self.interfaces = interfaces or []
        self.apps = apps or []

        self.endpoints_created: Optional[PlaygroundEndpointCreate] = None

        self.os_id: Optional[str] = os_id
        self.name: Optional[str] = name
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
                # Required for playground to work
                agent.store_events = True

        if self.teams:
            for team in self.teams:
                if not team.os_id:
                    team.os_id = self.os_id
                team.initialize_team()
                # Required for playground to work
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
                    status_code=e.status_code if hasattr(e, "status_code") else 500,
                    content={"detail": str(e)},
                )

        self.api_app.middleware("http")(general_exception_handler)

        # Attach base router
        self.api_app.include_router(get_base_router(self))

        for interface in self.interfaces:
            if interface.type == "playground":
                self.api_app.include_router(
                    interface.get_router(agents=self.agents, teams=self.teams, workflows=self.workflows)
                )
            else:
                self.api_app.include_router(interface.get_router())

            self.interfaces_loaded.append((interface.type, interface.router_prefix))

        app_index_map: Dict[str, int] = {}
        for app in self.apps:
            app_index_map[app.type] = app_index_map.get(app.type, 0) + 1
            self.api_app.include_router(app.get_router(index=app_index_map[app.type]))
            self.apps_loaded.append((app.type, app.router_prefix))

        self.api_app.add_middleware(
            CORSMiddleware,
            allow_origins=self.settings.cors_origin_list,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
            expose_headers=["*"],
        )
        
        if self.console:
            self.console.initialize(self)
            
            self.api_app.include_router(get_console_router(self.console))

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

        # Create a panel with the playground URL
        panels = []
        for interface_type, interface_prefix in self.interfaces_loaded:
            if interface_type == "playground":
                encoded_endpoint = f"{full_host}:{port}{interface_prefix}"
                url = f"{agno_cli_settings.playground_url}?endpoint={encoded_endpoint}"
                panels.append(
                    Panel(
                        f"[bold orange1]Playground URL:[/bold orange1] [link={url}]{url}[/link]",
                        title="Agno Playground",
                        expand=False,
                        border_style="orange1",
                        box=box.HEAVY,
                        padding=(2, 2),
                    )
                )
            elif interface_type == "whatsapp":
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

        apps_panel_text = ""
        for loaded_app in self.apps:
            if loaded_app.type == "knowledge":
                apps_panel_text += f"[bold]Knowledge Manager:[/bold] {loaded_app.name}\n"
            elif loaded_app.type == "memory":
                apps_panel_text += f"[bold]Memory Manager:[/bold] {loaded_app.name}\n"
            elif loaded_app.type == "eval":
                apps_panel_text += f"[bold]Evals Manager:[/bold] {loaded_app.name}\n"
            elif loaded_app.type == "session":
                apps_panel_text += f"[bold]Sessions Manager:[/bold] {loaded_app.name}\n"
            else:
                log_warning(f"Unknown app type: {loaded_app.type}")

        if apps_panel_text:
            apps_panel_text = apps_panel_text.strip()
            panels.append(
                Panel(
                    apps_panel_text,
                    title="Configured Apps",
                    expand=False,
                    border_style="sea_green2",
                    box=box.HEAVY,
                    padding=(2, 2),
                )
            )
        
        if self.console:
            panels.append(
                Panel(
                    f"[bold]Console model:[/bold] {self.console.model.to_string()}",
                    title="Console",
                    expand=False,
                    border_style="orange_red1",
                    box=box.HEAVY,
                    padding=(2, 2),
                )
            )

        # Print the panel
        for panel in panels:
            console.print(panel)

        uvicorn.run(app=app, host=host, port=port, reload=reload, **kwargs)

    
    async def cli(
        self,
        user: str = "User",
        emoji: str = ":point_right: :point_right: :sunglasses:",
        stream: bool = False,
        markdown: bool = False,
        exit_on: Optional[List[str]] = None,
    ) -> None:
        """Run an interactive command-line interface to interact with the agent."""
        from rich.prompt import Prompt
        
        if not self.console:
            raise ValueError("Console is not initialized. Please initialize the console first.")
        
        _exit_on = exit_on or ["exit", "quit", "bye"]
        while True:
            message = Prompt.ask(f"[bold] {emoji} {user} [/bold]")
            if message in _exit_on:
                break
            
            await self.console.print(message)