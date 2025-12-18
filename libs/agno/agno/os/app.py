from contextlib import asynccontextmanager
from functools import partial
from os import getenv
from typing import Any, Dict, List, Literal, Optional, Union
from uuid import uuid4

from fastapi import APIRouter, FastAPI, HTTPException
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from rich import box
from rich.panel import Panel
from starlette.requests import Request

from agno.agent.agent import Agent
from agno.db.base import AsyncBaseDb, BaseDb
from agno.knowledge.knowledge import Knowledge
from agno.os.config import (
    AgentOSConfig,
    AuthorizationConfig,
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
    TracesConfig,
    TracesDomainConfig,
)
from agno.os.interfaces.base import BaseInterface
from agno.os.router import get_base_router
from agno.os.routers.agents import get_agent_router
from agno.os.routers.evals import get_eval_router
from agno.os.routers.health import get_health_router
from agno.os.routers.home import get_home_router
from agno.os.routers.knowledge import get_knowledge_router
from agno.os.routers.memory import get_memory_router
from agno.os.routers.metrics import get_metrics_router
from agno.os.routers.session import get_session_router
from agno.os.routers.teams import get_team_router
from agno.os.routers.traces import get_traces_router
from agno.os.routers.workflows import get_websocket_router, get_workflow_router
from agno.os.settings import AgnoAPISettings
from agno.os.utils import (
    collect_mcp_tools_from_team,
    collect_mcp_tools_from_workflow,
    find_conflicting_routes,
    load_yaml_config,
    resolve_origins,
    setup_tracing_for_os,
    update_cors_middleware,
)
from agno.team.team import Team
from agno.utils.log import log_debug, log_error, log_info, log_warning
from agno.utils.string import generate_id, generate_id_from_name
from agno.workflow.workflow import Workflow


@asynccontextmanager
async def mcp_lifespan(_, mcp_tools):
    """Manage MCP connection lifecycle inside a FastAPI app"""
    # Startup logic: connect to all contextual MCP servers
    for tool in mcp_tools:
        await tool.connect()

    yield

    # Shutdown logic: Close all contextual MCP connections
    for tool in mcp_tools:
        await tool.close()


@asynccontextmanager
async def db_lifespan(app: FastAPI, agent_os: "AgentOS"):
    """Initializes databases in the event loop"""
    if agent_os.auto_provision_dbs:
        agent_os._initialize_sync_databases()
        await agent_os._initialize_async_databases()
    yield


def _combine_app_lifespans(lifespans: list) -> Any:
    """Combine multiple FastAPI app lifespan context managers into one."""
    if len(lifespans) == 1:
        return lifespans[0]

    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def combined_lifespan(app):
        async def _run_nested(index: int):
            if index >= len(lifespans):
                yield
                return

            async with lifespans[index](app):
                async for _ in _run_nested(index + 1):
                    yield

        async for _ in _run_nested(0):
            yield

    return combined_lifespan


class AgentOS:
    def __init__(
        self,
        id: Optional[str] = None,
        name: Optional[str] = None,
        description: Optional[str] = None,
        version: Optional[str] = None,
        agents: Optional[List[Agent]] = None,
        teams: Optional[List[Team]] = None,
        workflows: Optional[List[Workflow]] = None,
        knowledge: Optional[List[Knowledge]] = None,
        interfaces: Optional[List[BaseInterface]] = None,
        a2a_interface: bool = False,
        authorization: bool = False,
        authorization_config: Optional[AuthorizationConfig] = None,
        cors_allowed_origins: Optional[List[str]] = None,
        config: Optional[Union[str, AgentOSConfig]] = None,
        settings: Optional[AgnoAPISettings] = None,
        lifespan: Optional[Any] = None,
        enable_mcp_server: bool = False,
        base_app: Optional[FastAPI] = None,
        on_route_conflict: Literal["preserve_agentos", "preserve_base_app", "error"] = "preserve_agentos",
        tracing: bool = False,
        tracing_db: Optional[Union[BaseDb, AsyncBaseDb]] = None,
        auto_provision_dbs: bool = True,
        run_hooks_in_background: bool = False,
        telemetry: bool = True,
    ):
        """Initialize AgentOS.

        Args:
            id: Unique identifier for this AgentOS instance
            name: Name of the AgentOS instance
            description: Description of the AgentOS instance
            version: Version of the AgentOS instance
            agents: List of agents to include in the OS
            teams: List of teams to include in the OS
            workflows: List of workflows to include in the OS
            knowledge: List of knowledge bases to include in the OS
            interfaces: List of interfaces to include in the OS
            a2a_interface: Whether to expose the OS agents and teams in an A2A server
            config: Configuration file path or AgentOSConfig instance
            settings: API settings for the OS
            lifespan: Optional lifespan context manager for the FastAPI app
            enable_mcp_server: Whether to enable MCP (Model Context Protocol)
            base_app: Optional base FastAPI app to use for the AgentOS. All routes and middleware will be added to this app.
            on_route_conflict: What to do when a route conflict is detected in case a custom base_app is provided.
            auto_provision_dbs: Whether to automatically provision databases
            authorization: Whether to enable authorization
            authorization_config: Configuration for the authorization middleware
            cors_allowed_origins: List of allowed CORS origins (will be merged with default Agno domains)
            tracing: If True, enables OpenTelemetry tracing for all agents and teams in the OS
            tracing_db: Dedicated database for storing and reading traces. Recommended for multi-db setups.
                       If not provided and tracing=True, the first available db from agents/teams/workflows is used.
            run_hooks_in_background: If True, run agent/team pre/post hooks as FastAPI background tasks (non-blocking)
            telemetry: Whether to enable telemetry

        """
        if not agents and not workflows and not teams and not knowledge:
            raise ValueError("Either agents, teams, workflows or knowledge bases must be provided.")

        self.config = load_yaml_config(config) if isinstance(config, str) else config

        self.agents: Optional[List[Agent]] = agents
        self.workflows: Optional[List[Workflow]] = workflows
        self.teams: Optional[List[Team]] = teams
        self.interfaces = interfaces or []
        self.a2a_interface = a2a_interface
        self.knowledge = knowledge
        self.settings: AgnoAPISettings = settings or AgnoAPISettings()
        self.auto_provision_dbs = auto_provision_dbs
        self._app_set = False

        if base_app:
            self.base_app: Optional[FastAPI] = base_app
            self._app_set = True
            self.on_route_conflict = on_route_conflict
        else:
            self.base_app = None
            self._app_set = False
            self.on_route_conflict = on_route_conflict

        self.interfaces = interfaces or []

        self.name = name

        self.id = id
        if not self.id:
            self.id = generate_id(self.name) if self.name else str(uuid4())

        self.version = version
        self.description = description

        self.telemetry = telemetry
        self.tracing = tracing
        self.tracing_db = tracing_db

        self.enable_mcp_server = enable_mcp_server
        self.lifespan = lifespan

        # RBAC
        self.authorization = authorization
        self.authorization_config = authorization_config

        # CORS configuration - merge user-provided origins with defaults from settings
        self.cors_allowed_origins = resolve_origins(cors_allowed_origins, self.settings.cors_origin_list)

        # If True, run agent/team hooks as FastAPI background tasks
        self.run_hooks_in_background = run_hooks_in_background

        # List of all MCP tools used inside the AgentOS
        self.mcp_tools: List[Any] = []
        self._mcp_app: Optional[Any] = None

        self._initialize_agents()
        self._initialize_teams()
        self._initialize_workflows()

        # Check for duplicate IDs
        self._raise_if_duplicate_ids()

        if self.tracing:
            self._setup_tracing()

        if self.telemetry:
            from agno.api.os import OSLaunch, log_os_telemetry

            log_os_telemetry(launch=OSLaunch(os_id=self.id, data=self._get_telemetry_data()))

    def _add_agent_os_to_lifespan_function(self, lifespan):
        """
        Inspect a lifespan function and wrap it to pass agent_os if it accepts it.

        Returns:
            A wrapped lifespan that passes agent_os if the lifespan function expects it.
        """
        # Getting the actual function inside the lifespan
        lifespan_function = lifespan
        if hasattr(lifespan, "__wrapped__"):
            lifespan_function = lifespan.__wrapped__

        try:
            from inspect import signature

            # Inspecting the lifespan function signature to find its parameters
            sig = signature(lifespan_function)
            params = list(sig.parameters.keys())

            # If the lifespan function expects the 'agent_os' parameter, add it
            if "agent_os" in params:
                return partial(lifespan, agent_os=self)
            else:
                return lifespan

        except (ValueError, TypeError):
            return lifespan

    def resync(self, app: FastAPI) -> None:
        """Resync the AgentOS to discover, initialize and configure: agents, teams, workflows, databases and knowledge bases."""
        self._initialize_agents()
        self._initialize_teams()
        self._initialize_workflows()

        # Check for duplicate IDs
        self._raise_if_duplicate_ids()
        self._auto_discover_databases()
        self._auto_discover_knowledge_instances()

        if self.enable_mcp_server:
            from agno.os.mcp import get_mcp_server

            self._mcp_app = get_mcp_server(self)

        self._reprovision_routers(app=app)

    def _reprovision_routers(self, app: FastAPI) -> None:
        """Re-provision all routes for the AgentOS."""
        updated_routers = [
            get_session_router(dbs=self.dbs),
            get_metrics_router(dbs=self.dbs),
            get_knowledge_router(knowledge_instances=self.knowledge_instances),
            get_traces_router(dbs=self.dbs),
            get_memory_router(dbs=self.dbs),
            get_eval_router(dbs=self.dbs, agents=self.agents, teams=self.teams),
        ]

        # Clear all previously existing routes
        app.router.routes = [
            route
            for route in app.router.routes
            if hasattr(route, "path")
            and route.path in ["/docs", "/redoc", "/openapi.json", "/docs/oauth2-redirect"]
            or route.path.startswith("/mcp")  # type: ignore
        ]

        # Add the built-in routes
        self._add_built_in_routes(app=app)

        # Add the updated routes
        for router in updated_routers:
            self._add_router(app, router)

        # Mount MCP if needed
        if self.enable_mcp_server and self._mcp_app:
            app.mount("/", self._mcp_app)

    def _add_built_in_routes(self, app: FastAPI) -> None:
        """Add all AgentOSbuilt-in routes to the given app."""
        # Add the home router if MCP server is not enabled
        if not self.enable_mcp_server:
            self._add_router(app, get_home_router(self))

        self._add_router(app, get_health_router(health_endpoint="/health"))
        self._add_router(app, get_base_router(self, settings=self.settings))
        self._add_router(app, get_agent_router(self, settings=self.settings))
        self._add_router(app, get_team_router(self, settings=self.settings))
        self._add_router(app, get_workflow_router(self, settings=self.settings))
        self._add_router(app, get_websocket_router(self, settings=self.settings))

        # Add A2A interface if relevant
        has_a2a_interface = False
        for interface in self.interfaces:
            if not has_a2a_interface and interface.__class__.__name__ == "A2A":
                has_a2a_interface = True
            interface_router = interface.get_router()
            self._add_router(app, interface_router)
        if self.a2a_interface and not has_a2a_interface:
            from agno.os.interfaces.a2a import A2A

            a2a_interface = A2A(agents=self.agents, teams=self.teams, workflows=self.workflows)
            self.interfaces.append(a2a_interface)
            self._add_router(app, a2a_interface.get_router())

    def _raise_if_duplicate_ids(self) -> None:
        """Check for duplicate IDs within each entity type.

        Raises:
            ValueError: If duplicate IDs are found within the same entity type
        """
        duplicate_ids: List[str] = []

        for entities in [self.agents, self.teams, self.workflows]:
            if not entities:
                continue
            seen_ids: set[str] = set()
            for entity in entities:
                entity_id = entity.id
                if entity_id is None:
                    continue
                if entity_id in seen_ids:
                    if entity_id not in duplicate_ids:
                        duplicate_ids.append(entity_id)
                else:
                    seen_ids.add(entity_id)

        if duplicate_ids:
            raise ValueError(f"Duplicate IDs found in AgentOS: {', '.join(repr(id_) for id_ in duplicate_ids)}")

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

                app_lifespan = combined_lifespan
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

    def _initialize_agents(self) -> None:
        """Initialize and configure all agents for AgentOS usage."""
        if not self.agents:
            return
        for agent in self.agents:
            # Track all MCP tools to later handle their connection
            if agent.tools:
                for tool in agent.tools:
                    # Checking if the tool is an instance of MCPTools, MultiMCPTools, or a subclass of those
                    if hasattr(type(tool), "__mro__"):
                        mro_names = {cls.__name__ for cls in type(tool).__mro__}
                        if mro_names & {"MCPTools", "MultiMCPTools"}:
                            if tool not in self.mcp_tools:
                                self.mcp_tools.append(tool)

            agent.initialize_agent()

            # Required for the built-in routes to work
            agent.store_events = True

            # Propagate run_hooks_in_background setting from AgentOS to agents
            agent._run_hooks_in_background = self.run_hooks_in_background

    def _initialize_teams(self) -> None:
        """Initialize and configure all teams for AgentOS usage."""
        if not self.teams:
            return

        for team in self.teams:
            # Track all MCP tools recursively
            collect_mcp_tools_from_team(team, self.mcp_tools)

            team.initialize_team()

            for member in team.members:
                if isinstance(member, Agent):
                    member.team_id = None
                    member.initialize_agent()
                elif isinstance(member, Team):
                    member.initialize_team()

            # Required for the built-in routes to work
            team.store_events = True

            # Propagate run_hooks_in_background setting to team and all nested members
            team.propagate_run_hooks_in_background(self.run_hooks_in_background)

    def _initialize_workflows(self) -> None:
        """Initialize and configure all workflows for AgentOS usage."""
        if not self.workflows:
            return

        if self.workflows:
            for workflow in self.workflows:
                # Track MCP tools recursively in workflow members
                collect_mcp_tools_from_workflow(workflow, self.mcp_tools)

                if not workflow.id:
                    workflow.id = generate_id_from_name(workflow.name)

                # Required for the built-in routes to work
                workflow.store_events = True

                # Propagate run_hooks_in_background setting to workflow and all its step agents/teams
                workflow.propagate_run_hooks_in_background(self.run_hooks_in_background)

    def _setup_tracing(self) -> None:
        """Set up OpenTelemetry tracing for this AgentOS.

        Uses tracing_db if provided, otherwise falls back to the first available
        database from agents/teams/workflows.
        """
        # Use tracing_db if explicitly provided
        if self.tracing_db is not None:
            setup_tracing_for_os(db=self.tracing_db)
            return

        # Fall back to finding the first available database
        db: Optional[Union[BaseDb, AsyncBaseDb]] = None

        for agent in self.agents or []:
            if agent.db:
                db = agent.db
                break

        if db is None:
            for team in self.teams or []:
                if team.db:
                    db = team.db
                    break

        if db is None:
            for workflow in self.workflows or []:
                if workflow.db:
                    db = workflow.db
                    break

        if db is None:
            log_warning(
                "tracing=True but no database found. "
                "Provide 'tracing_db' parameter or 'db' parameter to at least one agent/team/workflow."
            )
            return

        setup_tracing_for_os(db=db)

    def get_app(self) -> FastAPI:
        if self.base_app:
            fastapi_app = self.base_app

            # Initialize MCP server if enabled
            if self.enable_mcp_server:
                from agno.os.mcp import get_mcp_server

                self._mcp_app = get_mcp_server(self)

            # Collect all lifespans that need to be combined
            lifespans = []

            # The user provided lifespan
            if self.lifespan:
                # Wrap the user lifespan with agent_os parameter
                wrapped_lifespan = self._add_agent_os_to_lifespan_function(self.lifespan)
                lifespans.append(wrapped_lifespan)

            # The provided app's existing lifespan
            if fastapi_app.router.lifespan_context:
                lifespans.append(fastapi_app.router.lifespan_context)

            # The MCP tools lifespan
            if self.mcp_tools:
                lifespans.append(partial(mcp_lifespan, mcp_tools=self.mcp_tools))

            # The /mcp server lifespan
            if self.enable_mcp_server and self._mcp_app:
                lifespans.append(self._mcp_app.lifespan)

            # The async database lifespan
            lifespans.append(partial(db_lifespan, agent_os=self))

            # Combine lifespans and set them in the app
            if lifespans:
                fastapi_app.router.lifespan_context = _combine_app_lifespans(lifespans)

        else:
            lifespans = []

            # User provided lifespan
            if self.lifespan:
                lifespans.append(self._add_agent_os_to_lifespan_function(self.lifespan))

            # MCP tools lifespan
            if self.mcp_tools:
                lifespans.append(partial(mcp_lifespan, mcp_tools=self.mcp_tools))

            # MCP server lifespan
            if self.enable_mcp_server:
                from agno.os.mcp import get_mcp_server

                self._mcp_app = get_mcp_server(self)
                lifespans.append(self._mcp_app.lifespan)

            # Async database initialization lifespan
            lifespans.append(partial(db_lifespan, agent_os=self))  # type: ignore

            final_lifespan = _combine_app_lifespans(lifespans) if lifespans else None
            fastapi_app = self._make_app(lifespan=final_lifespan)

        self._add_built_in_routes(app=fastapi_app)

        self._auto_discover_databases()
        self._auto_discover_knowledge_instances()

        routers = [
            get_session_router(dbs=self.dbs),
            get_memory_router(dbs=self.dbs),
            get_eval_router(dbs=self.dbs, agents=self.agents, teams=self.teams),
            get_metrics_router(dbs=self.dbs),
            get_knowledge_router(knowledge_instances=self.knowledge_instances),
            get_traces_router(dbs=self.dbs),
        ]

        for router in routers:
            self._add_router(fastapi_app, router)

        # Mount MCP if needed
        if self.enable_mcp_server and self._mcp_app:
            fastapi_app.mount("/", self._mcp_app)

        if not self._app_set:

            @fastapi_app.exception_handler(HTTPException)
            async def http_exception_handler(_, exc: HTTPException) -> JSONResponse:
                log_error(f"HTTP exception: {exc.status_code} {exc.detail}")
                return JSONResponse(
                    status_code=exc.status_code,
                    content={"detail": str(exc.detail)},
                )

            @fastapi_app.exception_handler(Exception)
            async def general_exception_handler(_: Request, exc: Exception) -> JSONResponse:
                import traceback

                log_error(f"Unhandled exception:\n{traceback.format_exc(limit=5)}")

                return JSONResponse(
                    status_code=getattr(exc, "status_code", 500),
                    content={"detail": str(exc)},
                )

        # Update CORS middleware
        update_cors_middleware(fastapi_app, self.cors_allowed_origins)  # type: ignore

        # Set agent_os_id and cors_allowed_origins on app state
        # This allows middleware (like JWT) to access these values
        fastapi_app.state.agent_os_id = self.id
        fastapi_app.state.cors_allowed_origins = self.cors_allowed_origins

        # Add JWT middleware if authorization is enabled
        if self.authorization:
            # Set authorization_enabled flag on settings so security key validation is skipped
            self.settings.authorization_enabled = True

            jwt_configured = bool(getenv("JWT_VERIFICATION_KEY") or getenv("JWT_JWKS_FILE"))
            security_key_set = bool(self.settings.os_security_key)
            if jwt_configured and security_key_set:
                log_warning(
                    "Both JWT configuration (JWT_VERIFICATION_KEY or JWT_JWKS_FILE) and OS_SECURITY_KEY are set. "
                    "With authorization=True, only JWT authorization will be used. "
                    "Consider removing OS_SECURITY_KEY from your environment."
                )

            self._add_jwt_middleware(fastapi_app)

        return fastapi_app

    def _add_jwt_middleware(self, fastapi_app: FastAPI) -> None:
        from agno.os.middleware.jwt import JWTMiddleware, JWTValidator

        verify_audience = False
        jwks_file = None
        verification_keys = None
        algorithm = "RS256"

        if self.authorization_config:
            algorithm = self.authorization_config.algorithm or "RS256"
            verification_keys = self.authorization_config.verification_keys
            jwks_file = self.authorization_config.jwks_file
            verify_audience = self.authorization_config.verify_audience or False

        log_info(f"Adding JWT middleware for authorization (algorithm: {algorithm})")

        # Create validator and store on app.state for WebSocket access
        jwt_validator = JWTValidator(
            verification_keys=verification_keys,
            jwks_file=jwks_file,
            algorithm=algorithm,
        )
        fastapi_app.state.jwt_validator = jwt_validator

        # Add middleware to stack
        fastapi_app.add_middleware(
            JWTMiddleware,
            verification_keys=verification_keys,
            jwks_file=jwks_file,
            algorithm=algorithm,
            authorization=self.authorization,
            verify_audience=verify_audience,
        )

    def get_routes(self) -> List[Any]:
        """Retrieve all routes from the FastAPI app.

        Returns:
            List[Any]: List of routes included in the FastAPI app.
        """
        app = self.get_app()

        return app.routes

    def _add_router(self, fastapi_app: FastAPI, router: APIRouter) -> None:
        """Add a router to the FastAPI app, avoiding route conflicts.

        Args:
            router: The APIRouter to add
        """

        conflicts = find_conflicting_routes(fastapi_app, router)
        conflicting_routes = [conflict["route"] for conflict in conflicts]

        if conflicts and self._app_set:
            if self.on_route_conflict == "preserve_base_app":
                # Skip conflicting AgentOS routes, prefer user's existing routes
                for conflict in conflicts:
                    methods_str = ", ".join(conflict["methods"])  # type: ignore
                    log_debug(
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
                    fastapi_app.include_router(filtered_router)

            elif self.on_route_conflict == "preserve_agentos":
                # Log warnings but still add all routes (AgentOS routes will override)
                for conflict in conflicts:
                    methods_str = ", ".join(conflict["methods"])  # type: ignore
                    log_warning(
                        f"Route conflict detected: {methods_str} {conflict['path']} - "
                        f"AgentOS route will override existing custom route"
                    )

                # Remove conflicting routes
                for route in fastapi_app.routes:
                    for conflict in conflicts:
                        if isinstance(route, APIRoute):
                            if route.path == conflict["path"] and list(route.methods) == list(conflict["methods"]):  # type: ignore
                                fastapi_app.routes.pop(fastapi_app.routes.index(route))

                fastapi_app.include_router(router)

            elif self.on_route_conflict == "error":
                conflicting_paths = [conflict["path"] for conflict in conflicts]
                raise ValueError(f"Route conflict detected: {conflicting_paths}")

        else:
            # No conflicts, add router normally
            fastapi_app.include_router(router)

    def _get_telemetry_data(self) -> Dict[str, Any]:
        """Get the telemetry data for the OS"""
        return {
            "agents": [agent.id for agent in self.agents] if self.agents else None,
            "teams": [team.id for team in self.teams] if self.teams else None,
            "workflows": [workflow.id for workflow in self.workflows] if self.workflows else None,
            "interfaces": [interface.type for interface in self.interfaces] if self.interfaces else None,
        }

    def _auto_discover_databases(self) -> None:
        """Auto-discover and initialize the databases used by all contextual agents, teams and workflows."""

        dbs: Dict[str, List[Union[BaseDb, AsyncBaseDb]]] = {}
        knowledge_dbs: Dict[
            str, List[Union[BaseDb, AsyncBaseDb]]
        ] = {}  # Track databases specifically used for knowledge

        for agent in self.agents or []:
            if agent.db:
                self._register_db_with_validation(dbs, agent.db)
            if agent.knowledge and agent.knowledge.contents_db:
                self._register_db_with_validation(knowledge_dbs, agent.knowledge.contents_db)

        for team in self.teams or []:
            if team.db:
                self._register_db_with_validation(dbs, team.db)
            if team.knowledge and team.knowledge.contents_db:
                self._register_db_with_validation(knowledge_dbs, team.knowledge.contents_db)

        for workflow in self.workflows or []:
            if workflow.db:
                self._register_db_with_validation(dbs, workflow.db)

        for knowledge_base in self.knowledge or []:
            if knowledge_base.contents_db:
                self._register_db_with_validation(knowledge_dbs, knowledge_base.contents_db)

        for interface in self.interfaces or []:
            if interface.agent and interface.agent.db:
                self._register_db_with_validation(dbs, interface.agent.db)
            elif interface.team and interface.team.db:
                self._register_db_with_validation(dbs, interface.team.db)

        # Register tracing_db if provided (for traces reading)
        if self.tracing_db is not None:
            self._register_db_with_validation(dbs, self.tracing_db)

        self.dbs = dbs
        self.knowledge_dbs = knowledge_dbs

        # Initialize all discovered databases
        if self.auto_provision_dbs:
            self._pending_async_db_init = True

    def _initialize_sync_databases(self) -> None:
        """Initialize sync databases."""
        from itertools import chain

        unique_dbs = list(
            {
                id(db): db
                for db in chain(
                    chain.from_iterable(self.dbs.values()), chain.from_iterable(self.knowledge_dbs.values())
                )
            }.values()
        )

        for db in unique_dbs:
            if isinstance(db, AsyncBaseDb):
                continue  # Skip async dbs

            try:
                if hasattr(db, "_create_all_tables") and callable(db._create_all_tables):
                    db._create_all_tables()
            except Exception as e:
                log_warning(f"Failed to initialize {db.__class__.__name__} (id: {db.id}): {e}")

    async def _initialize_async_databases(self) -> None:
        """Initialize async databases."""

        from itertools import chain

        unique_dbs = list(
            {
                id(db): db
                for db in chain(
                    chain.from_iterable(self.dbs.values()), chain.from_iterable(self.knowledge_dbs.values())
                )
            }.values()
        )

        for db in unique_dbs:
            if not isinstance(db, AsyncBaseDb):
                continue  # Skip sync dbs

            try:
                if hasattr(db, "_create_all_tables") and callable(db._create_all_tables):
                    await db._create_all_tables()
            except Exception as e:
                log_warning(f"Failed to initialize async {db.__class__.__name__} (id: {db.id}): {e}")

    def _get_db_table_names(self, db: BaseDb) -> Dict[str, str]:
        """Get the table names for a database"""
        table_names = {
            "session_table_name": db.session_table_name,
            "culture_table_name": db.culture_table_name,
            "memory_table_name": db.memory_table_name,
            "metrics_table_name": db.metrics_table_name,
            "evals_table_name": db.eval_table_name,
            "knowledge_table_name": db.knowledge_table_name,
        }
        return {k: v for k, v in table_names.items() if v is not None}

    def _register_db_with_validation(
        self, registered_dbs: Dict[str, List[Union[BaseDb, AsyncBaseDb]]], db: Union[BaseDb, AsyncBaseDb]
    ) -> None:
        """Register a database in the contextual OS after validating it is not conflicting with registered databases"""
        if db.id in registered_dbs:
            registered_dbs[db.id].append(db)
        else:
            registered_dbs[db.id] = [db]

    def _auto_discover_knowledge_instances(self) -> None:
        """Auto-discover the knowledge instances used by all contextual agents, teams and workflows."""
        seen_ids = set()
        knowledge_instances: List[Knowledge] = []

        def _add_knowledge_if_not_duplicate(knowledge: "Knowledge") -> None:
            """Add knowledge instance if it's not already in the list (by object identity or db_id)."""
            # Use database ID if available, otherwise use object ID as fallback
            if not knowledge.contents_db:
                return
            if knowledge.contents_db.id in seen_ids:
                return
            seen_ids.add(knowledge.contents_db.id)
            knowledge_instances.append(knowledge)

        for agent in self.agents or []:
            if agent.knowledge:
                _add_knowledge_if_not_duplicate(agent.knowledge)

        for team in self.teams or []:
            if team.knowledge:
                _add_knowledge_if_not_duplicate(team.knowledge)

        for knowledge_base in self.knowledge or []:
            _add_knowledge_if_not_duplicate(knowledge_base)

        self.knowledge_instances = knowledge_instances

    def _get_session_config(self) -> SessionConfig:
        session_config = self.config.session if self.config and self.config.session else SessionConfig()

        if session_config.dbs is None:
            session_config.dbs = []

        dbs_with_specific_config = [db.db_id for db in session_config.dbs]
        for db_id, dbs in self.dbs.items():
            if db_id not in dbs_with_specific_config:
                # Collect unique table names from all databases with the same id
                unique_tables = list(set(db.session_table_name for db in dbs))
                session_config.dbs.append(
                    DatabaseConfig(
                        db_id=db_id,
                        domain_config=SessionDomainConfig(display_name=db_id),
                        tables=unique_tables,
                    )
                )

        return session_config

    def _get_memory_config(self) -> MemoryConfig:
        memory_config = self.config.memory if self.config and self.config.memory else MemoryConfig()

        if memory_config.dbs is None:
            memory_config.dbs = []

        dbs_with_specific_config = [db.db_id for db in memory_config.dbs]

        for db_id, dbs in self.dbs.items():
            if db_id not in dbs_with_specific_config:
                # Collect unique table names from all databases with the same id
                unique_tables = list(set(db.memory_table_name for db in dbs))
                memory_config.dbs.append(
                    DatabaseConfig(
                        db_id=db_id,
                        domain_config=MemoryDomainConfig(display_name=db_id),
                        tables=unique_tables,
                    )
                )

        return memory_config

    def _get_knowledge_config(self) -> KnowledgeConfig:
        knowledge_config = self.config.knowledge if self.config and self.config.knowledge else KnowledgeConfig()

        if knowledge_config.dbs is None:
            knowledge_config.dbs = []

        dbs_with_specific_config = [db.db_id for db in knowledge_config.dbs]

        # Only add databases that are actually used for knowledge contents
        for db_id in self.knowledge_dbs.keys():
            if db_id not in dbs_with_specific_config:
                knowledge_config.dbs.append(
                    DatabaseConfig(
                        db_id=db_id,
                        domain_config=KnowledgeDomainConfig(display_name=db_id),
                    )
                )

        return knowledge_config

    def _get_metrics_config(self) -> MetricsConfig:
        metrics_config = self.config.metrics if self.config and self.config.metrics else MetricsConfig()

        if metrics_config.dbs is None:
            metrics_config.dbs = []

        dbs_with_specific_config = [db.db_id for db in metrics_config.dbs]

        for db_id, dbs in self.dbs.items():
            if db_id not in dbs_with_specific_config:
                # Collect unique table names from all databases with the same id
                unique_tables = list(set(db.metrics_table_name for db in dbs))
                metrics_config.dbs.append(
                    DatabaseConfig(
                        db_id=db_id,
                        domain_config=MetricsDomainConfig(display_name=db_id),
                        tables=unique_tables,
                    )
                )

        return metrics_config

    def _get_evals_config(self) -> EvalsConfig:
        evals_config = self.config.evals if self.config and self.config.evals else EvalsConfig()

        if evals_config.dbs is None:
            evals_config.dbs = []

        dbs_with_specific_config = [db.db_id for db in evals_config.dbs]

        for db_id, dbs in self.dbs.items():
            if db_id not in dbs_with_specific_config:
                # Collect unique table names from all databases with the same id
                unique_tables = list(set(db.eval_table_name for db in dbs))
                evals_config.dbs.append(
                    DatabaseConfig(
                        db_id=db_id,
                        domain_config=EvalsDomainConfig(display_name=db_id),
                        tables=unique_tables,
                    )
                )

        return evals_config

    def _get_traces_config(self) -> TracesConfig:
        traces_config = self.config.traces if self.config and self.config.traces else TracesConfig()

        if traces_config.dbs is None:
            traces_config.dbs = []

        dbs_with_specific_config = [db.db_id for db in traces_config.dbs]

        # If tracing_db is explicitly set, only use that database for traces
        if self.tracing_db is not None:
            if self.tracing_db.id not in dbs_with_specific_config:
                traces_config.dbs.append(
                    DatabaseConfig(
                        db_id=self.tracing_db.id,
                        domain_config=TracesDomainConfig(display_name=self.tracing_db.id),
                    )
                )
        else:
            # Fall back to all discovered databases
            for db_id in self.dbs.keys():
                if db_id not in dbs_with_specific_config:
                    traces_config.dbs.append(
                        DatabaseConfig(
                            db_id=db_id,
                            domain_config=TracesDomainConfig(display_name=db_id),
                        )
                    )

        return traces_config

    def serve(
        self,
        app: Union[str, FastAPI],
        *,
        host: str = "localhost",
        port: int = 7777,
        reload: bool = False,
        reload_includes: Optional[List[str]] = None,
        reload_excludes: Optional[List[str]] = None,
        workers: Optional[int] = None,
        access_log: bool = False,
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

        panel_group = [
            Align.center(f"[bold cyan]{public_endpoint}[/bold cyan]"),
            Align.center(f"\n\n[bold dark_orange]OS running on:[/bold dark_orange] http://{host}:{port}"),
        ]
        if self.authorization:
            panel_group.append(
                Align.center("\n\n[bold chartreuse3]:lock: JWT Authorization Enabled[/bold chartreuse3]")
            )
        elif bool(self.settings.os_security_key):
            panel_group.append(Align.center("\n\n[bold chartreuse3]:lock: Security Key Enabled[/bold chartreuse3]"))

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

        # Adding *.yaml to reload_includes to reload the app when the yaml config file changes.
        if reload and reload_includes is not None:
            reload_includes = ["*.yaml", "*.yml"]

        uvicorn.run(
            app=app,
            host=host,
            port=port,
            reload=reload,
            reload_includes=reload_includes,
            reload_excludes=reload_excludes,
            workers=workers,
            access_log=access_log,
            lifespan="on",
            **kwargs,
        )
