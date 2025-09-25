from contextlib import asynccontextmanager
from functools import partial
from os import getenv
from typing import Any, Dict, List, Optional, Set, Union
from uuid import uuid4

from fastapi import APIRouter, FastAPI, HTTPException
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from rich import box
from rich.panel import Panel
from starlette.requests import Request

from agno.agent.agent import Agent
from agno.os.config import (
    AgentOSConfig,
    DatabaseConfig,
    EvalsConfig,
    EvalsDomainConfig,
    KnowledgeConfig,
    KnowledgeDomainConfig,
    MemoryConfig,
    MemoryDomainConfig,
    MetricsConfig,
    MetricsDomainConfig,
    SessionConfig,
    SessionDomainConfig,
)
from agno.os.interfaces.base import BaseInterface
from agno.os.router import get_base_router, get_websocket_router
from agno.os.routers.evals import get_eval_router
from agno.os.routers.health import get_health_router
from agno.os.routers.home import get_home_router
from agno.os.routers.knowledge import get_knowledge_router
from agno.os.routers.memory import get_memory_router
from agno.os.routers.metrics import get_metrics_router
from agno.os.routers.session import get_session_router
from agno.os.settings import AgnoAPISettings
from agno.os.utils import update_cors_middleware
from agno.team.team import Team
from agno.utils.log import logger
from agno.utils.string import generate_id, generate_id_from_name
from agno.workflow.workflow import Workflow


@asynccontextmanager
async def mcp_lifespan(app, mcp_tools):
    """Manage MCP connection lifecycle inside a FastAPI app"""
    # Startup logic: connect to all contextual MCP servers
    for tool in mcp_tools:
        await tool.connect()

    yield

    # Shutdown logic: Close all contextual MCP connections
    for tool in mcp_tools:
        await tool.close()


class AgentOS:
    def __init__(
        self,
        os_id: Optional[str] = None,
        name: Optional[str] = None,
        description: Optional[str] = None,
        version: Optional[str] = None,
        agents: Optional[List[Agent]] = None,
        teams: Optional[List[Team]] = None,
        workflows: Optional[List[Workflow]] = None,
        interfaces: Optional[List[BaseInterface]] = None,
        config: Optional[Union[str, AgentOSConfig]] = None,
        settings: Optional[AgnoAPISettings] = None,
        fastapi_app: Optional[FastAPI] = None,
        lifespan: Optional[Any] = None,
        enable_mcp: bool = False,
        replace_routes: bool = True,
        telemetry: bool = True,
    ):
        """Initialize AgentOS.

        Args:
            os_id: Unique identifier for this AgentOS instance
            name: Name of the AgentOS instance
            description: Description of the AgentOS instance
            version: Version of the AgentOS instance
            agents: List of agents to include in the OS
            teams: List of teams to include in the OS
            workflows: List of workflows to include in the OS
            interfaces: List of interfaces to include in the OS
            config: Configuration file path or AgentOSConfig instance
            settings: API settings for the OS
            fastapi_app: Optional custom FastAPI app to use instead of creating a new one
            lifespan: Optional lifespan context manager for the FastAPI app
            enable_mcp: Whether to enable MCP (Model Context Protocol)
            replace_routes: If False and using a custom fastapi_app, skip AgentOS routes that
                          conflict with existing routes, preferring the user's custom routes.
                          If True (default), AgentOS routes will override conflicting custom routes.
            telemetry: Whether to enable telemetry
        """
        if not agents and not workflows and not teams:
            raise ValueError("Either agents, teams or workflows must be provided.")

        self.config = self._load_yaml_config(config) if isinstance(config, str) else config

        self.agents: Optional[List[Agent]] = agents
        self.workflows: Optional[List[Workflow]] = workflows
        self.teams: Optional[List[Team]] = teams
        self.interfaces = interfaces or []

        self.settings: AgnoAPISettings = settings or AgnoAPISettings()

        self._app_set = False
        self.fastapi_app: Optional[FastAPI] = None
        if fastapi_app:
            self.fastapi_app = fastapi_app
            self._app_set = True

        self.interfaces = interfaces or []

        self.os_id = os_id
        self.name = name
        self.version = version
        self.description = description

        self.replace_routes = replace_routes

        self.telemetry = telemetry

        self.enable_mcp = enable_mcp
        self.lifespan = lifespan

        # List of all MCP tools used inside the AgentOS
        self.mcp_tools = []

        if self.agents:
            for agent in self.agents:
                # Track all MCP tools to later handle their connection
                if agent.tools:
                    for tool in agent.tools:
                        # Checking if the tool is a MCPTools or MultiMCPTools instance
                        type_name = type(tool).__name__
                        if type_name in ("MCPTools", "MultiMCPTools"):
                            self.mcp_tools.append(tool)

                agent.initialize_agent()

                # Required for the built-in routes to work
                agent.store_events = True

        if self.teams:
            for team in self.teams:
                # Track all MCP tools to later handle their connection
                if team.tools:
                    for tool in team.tools:
                        # Checking if the tool is a MCPTools or MultiMCPTools instance
                        type_name = type(tool).__name__
                        if type_name in ("MCPTools", "MultiMCPTools"):
                            self.mcp_tools.append(tool)

                team.initialize_team()

                # Required for the built-in routes to work
                team.store_events = True

                for member in team.members:
                    if isinstance(member, Agent):
                        member.team_id = None
                        member.initialize_agent()
                    elif isinstance(member, Team):
                        member.initialize_team()

        if self.workflows:
            for workflow in self.workflows:
                # TODO: track MCP tools in workflow members
                if not workflow.id:
                    workflow.id = generate_id_from_name(workflow.name)

        if not self.os_id:
            self.os_id = generate_id(self.name) if self.name else str(uuid4())

        if self.telemetry:
            from agno.api.os import OSLaunch, log_os_telemetry

            log_os_telemetry(launch=OSLaunch(os_id=self.os_id, data=self._get_telemetry_data()))

    def _make_app(self, lifespan: Optional[Any] = None) -> FastAPI:
        # Adjust the FastAPI app lifespan to handle MCP connections if relevant
        app_lifespan = lifespan
        if self.mcp_tools is not None:
            mcp_tools_lifespan = partial(mcp_lifespan, mcp_tools=self.mcp_tools)
            # If there is already a lifespan, combine it with the MCP lifespan
            if lifespan is not None:
                # Combine both lifespans
                @asynccontextmanager
                async def combined_lifespan(app: FastAPI):
                    # Run both lifespans
                    async with lifespan(app):  # type: ignore
                        async with mcp_tools_lifespan(app):  # type: ignore
                            yield

                app_lifespan = combined_lifespan  # type: ignore
            else:
                app_lifespan = mcp_tools_lifespan

        return FastAPI(
            title=self.name or "Agno AgentOS",
            version=self.version or "1.0.0",
            description=self.description or "An agent operating system.",
            docs_url="/docs" if self.settings.docs_enabled else None,
            redoc_url="/redoc" if self.settings.docs_enabled else None,
            openapi_url="/openapi.json" if self.settings.docs_enabled else None,
            lifespan=app_lifespan,
        )

    def get_app(self) -> FastAPI:
        if not self.fastapi_app:
            if self.enable_mcp:
                from contextlib import asynccontextmanager

                from agno.os.mcp import get_mcp_server

                self.mcp_app = get_mcp_server(self)

                final_lifespan = self.mcp_app.lifespan
                if self.lifespan is not None:
                    # Combine both lifespans
                    @asynccontextmanager
                    async def combined_lifespan(app: FastAPI):
                        # Run both lifespans
                        async with self.lifespan(app):  # type: ignore
                            async with self.mcp_app.lifespan(app):  # type: ignore
                                yield

                    final_lifespan = combined_lifespan  # type: ignore

                self.fastapi_app = self._make_app(lifespan=final_lifespan)
            else:
                self.fastapi_app = self._make_app(lifespan=self.lifespan)

        # Add routes with conflict detection
        self._add_router(get_base_router(self, settings=self.settings))
        self._add_router(get_websocket_router(self, settings=self.settings))
        self._add_router(get_health_router())
        self._add_router(get_home_router(self))

        for interface in self.interfaces:
            interface_router = interface.get_router()
            self._add_router(interface_router)

        self._auto_discover_databases()
        self._auto_discover_knowledge_instances()

        routers = [
            get_session_router(dbs=self.dbs),
            get_memory_router(dbs=self.dbs),
            get_eval_router(dbs=self.dbs, agents=self.agents, teams=self.teams),
            get_metrics_router(dbs=self.dbs),
            get_knowledge_router(knowledge_instances=self.knowledge_instances),
        ]

        for router in routers:
            self._add_router(router)

        # Mount MCP if needed
        if self.enable_mcp and self.mcp_app:
            self.fastapi_app.mount("/", self.mcp_app)

        # Add middleware (only if app is not set)
        if not self._app_set:

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

        # Update CORS middleware
        update_cors_middleware(self.fastapi_app, self.settings.cors_origin_list)  # type: ignore

        return self.fastapi_app

    def get_routes(self) -> List[Any]:
        """Retrieve all routes from the FastAPI app.

        Returns:
            List[Any]: List of routes included in the FastAPI app.
        """
        app = self.get_app()

        return app.routes

    def _get_existing_route_paths(self) -> Dict[str, List[str]]:
        """Get all existing route paths and methods from the FastAPI app.

        Returns:
            Dict[str, List[str]]: Dictionary mapping paths to list of HTTP methods
        """
        if not self.fastapi_app:
            return {}

        existing_paths: Dict[str, Any] = {}
        for route in self.fastapi_app.routes:
            if isinstance(route, APIRoute):
                path = route.path
                methods = list(route.methods) if route.methods else []
                if path in existing_paths:
                    existing_paths[path].extend(methods)
                else:
                    existing_paths[path] = methods
        return existing_paths

    def _add_router(self, router: APIRouter) -> None:
        """Add a router to the FastAPI app, avoiding route conflicts.

        Args:
            router: The APIRouter to add
        """
        if not self.fastapi_app:
            return

        # Get existing routes
        existing_paths = self._get_existing_route_paths()

        # Check for conflicts
        conflicts = []
        conflicting_routes = []

        for route in router.routes:
            if isinstance(route, APIRoute):
                full_path = route.path
                route_methods = list(route.methods) if route.methods else []

                if full_path in existing_paths:
                    conflicting_methods: Set[str] = set(route_methods) & set(existing_paths[full_path])
                    if conflicting_methods:
                        conflicts.append({"path": full_path, "methods": list(conflicting_methods), "route": route})
                        conflicting_routes.append(route)

        if conflicts and self._app_set:
            if self.replace_routes:
                # Log warnings but still add all routes (AgentOS routes will override)
                for conflict in conflicts:
                    methods_str = ", ".join(conflict["methods"])  # type: ignore
                    logger.warning(
                        f"Route conflict detected: {methods_str} {conflict['path']} - "
                        f"AgentOS route will override existing custom route"
                    )

                # Remove conflicting routes
                for route in self.fastapi_app.routes:
                    for conflict in conflicts:
                        if isinstance(route, APIRoute):
                            if route.path == conflict["path"] and list(route.methods) == list(conflict["methods"]):  # type: ignore
                                self.fastapi_app.routes.pop(self.fastapi_app.routes.index(route))

                self.fastapi_app.include_router(router)

            else:
                # Skip conflicting AgentOS routes, prefer user's existing routes
                for conflict in conflicts:
                    methods_str = ", ".join(conflict["methods"])  # type: ignore
                    logger.debug(
                        f"Skipping conflicting AgentOS route: {methods_str} {conflict['path']} - "
                        f"Using existing custom route instead"
                    )

                # Create a new router without the conflicting routes
                filtered_router = APIRouter()
                for route in router.routes:
                    if route not in conflicting_routes:
                        filtered_router.routes.append(route)

                # Use the filtered router if it has any routes left
                if filtered_router.routes:
                    self.fastapi_app.include_router(filtered_router)
        else:
            # No conflicts, add router normally
            self.fastapi_app.include_router(router)

    def _get_telemetry_data(self) -> Dict[str, Any]:
        """Get the telemetry data for the OS"""
        return {
            "agents": [agent.id for agent in self.agents] if self.agents else None,
            "teams": [team.id for team in self.teams] if self.teams else None,
            "workflows": [workflow.id for workflow in self.workflows] if self.workflows else None,
            "interfaces": [interface.type for interface in self.interfaces] if self.interfaces else None,
        }

    def _load_yaml_config(self, config_file_path: str) -> AgentOSConfig:
        """Load a YAML config file and return the configuration as an AgentOSConfig instance."""
        from pathlib import Path

        import yaml

        # Validate that the path points to a YAML file
        path = Path(config_file_path)
        if path.suffix.lower() not in [".yaml", ".yml"]:
            raise ValueError(f"Config file must have a .yaml or .yml extension, got: {config_file_path}")

        # Load the YAML file
        with open(config_file_path, "r") as f:
            return AgentOSConfig.model_validate(yaml.safe_load(f))

    def _auto_discover_databases(self) -> None:
        """Auto-discover the databases used by all contextual agents, teams and workflows."""
        dbs = {}
        knowledge_dbs = {}  # Track databases specifically used for knowledge

        for agent in self.agents or []:
            if agent.db:
                dbs[agent.db.id] = agent.db
            if agent.knowledge and agent.knowledge.contents_db:
                knowledge_dbs[agent.knowledge.contents_db.id] = agent.knowledge.contents_db
                # Also add to general dbs if it's used for both purposes
                if agent.knowledge.contents_db.id not in dbs:
                    dbs[agent.knowledge.contents_db.id] = agent.knowledge.contents_db

        for team in self.teams or []:
            if team.db:
                dbs[team.db.id] = team.db
            if team.knowledge and team.knowledge.contents_db:
                knowledge_dbs[team.knowledge.contents_db.id] = team.knowledge.contents_db
                # Also add to general dbs if it's used for both purposes
                if team.knowledge.contents_db.id not in dbs:
                    dbs[team.knowledge.contents_db.id] = team.knowledge.contents_db

        for workflow in self.workflows or []:
            if workflow.db:
                dbs[workflow.db.id] = workflow.db

        for interface in self.interfaces or []:
            if interface.agent and interface.agent.db:
                dbs[interface.agent.db.id] = interface.agent.db
            elif interface.team and interface.team.db:
                dbs[interface.team.db.id] = interface.team.db

        self.dbs = dbs
        self.knowledge_dbs = knowledge_dbs

    def _auto_discover_knowledge_instances(self) -> None:
        """Auto-discover the knowledge instances used by all contextual agents, teams and workflows."""
        knowledge_instances = []
        for agent in self.agents or []:
            if agent.knowledge:
                knowledge_instances.append(agent.knowledge)

        for team in self.teams or []:
            if team.knowledge:
                knowledge_instances.append(team.knowledge)

        self.knowledge_instances = knowledge_instances

    def _get_session_config(self) -> SessionConfig:
        session_config = self.config.session if self.config and self.config.session else SessionConfig()

        if session_config.dbs is None:
            session_config.dbs = []

        multiple_dbs: bool = len(self.dbs.keys()) > 1
        dbs_with_specific_config = [db.db_id for db in session_config.dbs]

        for db_id in self.dbs.keys():
            if db_id not in dbs_with_specific_config:
                session_config.dbs.append(
                    DatabaseConfig(
                        db_id=db_id,
                        domain_config=SessionDomainConfig(
                            display_name="Sessions" if not multiple_dbs else "Sessions in database '" + db_id + "'"
                        ),
                    )
                )

        return session_config

    def _get_memory_config(self) -> MemoryConfig:
        memory_config = self.config.memory if self.config and self.config.memory else MemoryConfig()

        if memory_config.dbs is None:
            memory_config.dbs = []

        multiple_dbs: bool = len(self.dbs.keys()) > 1
        dbs_with_specific_config = [db.db_id for db in memory_config.dbs]

        for db_id in self.dbs.keys():
            if db_id not in dbs_with_specific_config:
                memory_config.dbs.append(
                    DatabaseConfig(
                        db_id=db_id,
                        domain_config=MemoryDomainConfig(
                            display_name="Memory" if not multiple_dbs else "Memory in database '" + db_id + "'"
                        ),
                    )
                )

        return memory_config

    def _get_knowledge_config(self) -> KnowledgeConfig:
        knowledge_config = self.config.knowledge if self.config and self.config.knowledge else KnowledgeConfig()

        if knowledge_config.dbs is None:
            knowledge_config.dbs = []

        multiple_knowledge_dbs: bool = len(self.knowledge_dbs.keys()) > 1
        dbs_with_specific_config = [db.db_id for db in knowledge_config.dbs]

        # Only add databases that are actually used for knowledge contents
        for db_id in self.knowledge_dbs.keys():
            if db_id not in dbs_with_specific_config:
                knowledge_config.dbs.append(
                    DatabaseConfig(
                        db_id=db_id,
                        domain_config=KnowledgeDomainConfig(
                            display_name="Knowledge" if not multiple_knowledge_dbs else "Knowledge in database " + db_id
                        ),
                    )
                )

        return knowledge_config

    def _get_metrics_config(self) -> MetricsConfig:
        metrics_config = self.config.metrics if self.config and self.config.metrics else MetricsConfig()

        if metrics_config.dbs is None:
            metrics_config.dbs = []

        multiple_dbs: bool = len(self.dbs.keys()) > 1
        dbs_with_specific_config = [db.db_id for db in metrics_config.dbs]

        for db_id in self.dbs.keys():
            if db_id not in dbs_with_specific_config:
                metrics_config.dbs.append(
                    DatabaseConfig(
                        db_id=db_id,
                        domain_config=MetricsDomainConfig(
                            display_name="Metrics" if not multiple_dbs else "Metrics in database '" + db_id + "'"
                        ),
                    )
                )

        return metrics_config

    def _get_evals_config(self) -> EvalsConfig:
        evals_config = self.config.evals if self.config and self.config.evals else EvalsConfig()

        if evals_config.dbs is None:
            evals_config.dbs = []

        multiple_dbs: bool = len(self.dbs.keys()) > 1
        dbs_with_specific_config = [db.db_id for db in evals_config.dbs]

        for db_id in self.dbs.keys():
            if db_id not in dbs_with_specific_config:
                evals_config.dbs.append(
                    DatabaseConfig(
                        db_id=db_id,
                        domain_config=EvalsDomainConfig(
                            display_name="Evals" if not multiple_dbs else "Evals in database '" + db_id + "'"
                        ),
                    )
                )

        return evals_config

    def serve(
        self,
        app: Union[str, FastAPI],
        *,
        host: str = "localhost",
        port: int = 7777,
        reload: bool = False,
        workers: Optional[int] = None,
        **kwargs,
    ):
        import uvicorn

        if getenv("AGNO_API_RUNTIME", "").lower() == "stg":
            public_endpoint = "https://os-stg.agno.com/"
        else:
            public_endpoint = "https://os.agno.com/"

        # Create a terminal panel to announce OS initialization and provide useful info
        from rich.align import Align
        from rich.console import Console, Group

        panel_group = []
        panel_group.append(Align.center(f"[bold cyan]{public_endpoint}[/bold cyan]"))
        panel_group.append(
            Align.center(f"\n\n[bold dark_orange]OS running on:[/bold dark_orange] http://{host}:{port}")
        )
        if bool(self.settings.os_security_key):
            panel_group.append(Align.center("\n\n[bold chartreuse3]:lock: Security Enabled[/bold chartreuse3]"))

        console = Console()
        console.print(
            Panel(
                Group(*panel_group),
                title="AgentOS",
                expand=False,
                border_style="dark_orange",
                box=box.DOUBLE_EDGE,
                padding=(2, 2),
            )
        )

        uvicorn.run(app=app, host=host, port=port, reload=reload, workers=workers, **kwargs)
