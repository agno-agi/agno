from os import getenv
from typing import Any, Dict, List, Optional, Tuple, Union
from uuid import uuid4

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from rich import box
from rich.panel import Panel
from starlette.middleware.cors import CORSMiddleware
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
from agno.os.router import get_base_router
from agno.os.routers.evals import get_eval_router
from agno.os.routers.knowledge import get_knowledge_router
from agno.os.routers.memory import get_memory_router
from agno.os.routers.metrics import get_metrics_router
from agno.os.routers.session import get_session_router
from agno.os.settings import AgnoAPISettings
from agno.os.utils import generate_id
from agno.team.team import Team
from agno.workflow.workflow import Workflow


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
        config: Optional[Union[str, AgentOSConfig]] = None,
        settings: Optional[AgnoAPISettings] = None,
        fastapi_app: Optional[FastAPI] = None,
        telemetry: bool = True,
    ):
        if not agents and not workflows and not teams:
            raise ValueError("Either agents, teams or workflows must be provided.")

        self.config = self._load_yaml_config(config) if isinstance(config, str) else config
        self.description = description

        self.agents: Optional[List[Agent]] = agents
        self.workflows: Optional[List[Workflow]] = workflows
        self.teams: Optional[List[Team]] = teams
        self.interfaces = interfaces or []

        self.settings: AgnoAPISettings = settings or AgnoAPISettings()
        self.fastapi_app: Optional[FastAPI] = fastapi_app

        self.interfaces = interfaces or []

        self.os_id: Optional[str] = os_id
        self.description = description

        self.telemetry = telemetry

        self.interfaces_loaded: List[Tuple[str, str]] = []

        if self.agents:
            for agent in self.agents:
                agent.initialize_agent()

                # Required for the built-in routes to work
                agent.store_events = True

        if self.teams:
            for team in self.teams:
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
                if not workflow.id:
                    workflow.id = generate_id(workflow.name)

        if self.telemetry:
            from agno.api.os import OSLaunch, log_os_telemetry

            log_os_telemetry(launch=OSLaunch(os_id=self.os_id, data=self._get_telemetry_data()))

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

        for agent in self.agents or []:
            if agent.db:
                dbs[agent.db.id] = agent.db
            if agent.knowledge and agent.knowledge.contents_db:
                dbs[agent.knowledge.contents_db.id] = agent.knowledge.contents_db

        for team in self.teams or []:
            if team.db:
                dbs[team.db.id] = team.db
            if team.knowledge and team.knowledge.contents_db:
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
                            display_name="Sessions" if not multiple_dbs else "Sessions " + db_id
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
                            display_name="Memory" if not multiple_dbs else "Memory " + db_id
                        ),
                    )
                )

        return memory_config

    def _get_knowledge_config(self) -> KnowledgeConfig:
        knowledge_config = self.config.knowledge if self.config and self.config.knowledge else KnowledgeConfig()

        if knowledge_config.dbs is None:
            knowledge_config.dbs = []

        multiple_dbs: bool = len(self.dbs.keys()) > 1
        dbs_with_specific_config = [db.db_id for db in knowledge_config.dbs]

        for db_id in self.dbs.keys():
            if db_id not in dbs_with_specific_config:
                knowledge_config.dbs.append(
                    DatabaseConfig(
                        db_id=db_id,
                        domain_config=KnowledgeDomainConfig(
                            display_name="Knowledge" if not multiple_dbs else "Knowledge " + db_id
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
                            display_name="Metrics" if not multiple_dbs else "Metrics " + db_id
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
                        domain_config=EvalsDomainConfig(display_name="Evals" if not multiple_dbs else "Evals " + db_id),
                    )
                )

        return evals_config

    def _setup_routers(self) -> None:
        """Add all routers to the FastAPI app."""
        if not self.dbs or not self.fastapi_app:
            return

        routers = [
            get_session_router(dbs=self.dbs),
            get_memory_router(dbs=self.dbs),
            get_eval_router(dbs=self.dbs, agents=self.agents, teams=self.teams),
            get_metrics_router(dbs=self.dbs),
            get_knowledge_router(knowledge_instances=self.knowledge_instances),
        ]

        for router in routers:
            self.fastapi_app.include_router(router)

    def set_os_id(self) -> str:
        # If os_id is already set, keep it instead of overriding with UUID
        if self.os_id is None:
            self.os_id = str(uuid4())

        return self.os_id

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

        self._auto_discover_databases()
        self._auto_discover_knowledge_instances()
        self._setup_routers()

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

        if getenv("AGNO_API_RUNTIME", "").lower() == "stg":
            public_endpoint = "https://os-stg.agno.com/"
        else:
            public_endpoint = "https://os.agno.com/"

        # Create a terminal panel to announce OS initialization and provide useful info
        from rich.align import Align
        from rich.console import Console, Group

        aligned_endpoint = Align.center(f"[bold cyan]{public_endpoint}[/bold cyan]")
        connection_endpoint = f"\n\n[bold dark_orange]Running on:[/bold dark_orange] http://{host}:{port}"

        console = Console()
        console.print(
            Panel(
                Group(aligned_endpoint, connection_endpoint),
                title="AgentOS",
                expand=False,
                border_style="dark_orange",
                box=box.DOUBLE_EDGE,
                padding=(2, 2),
            )
        )

        uvicorn.run(app=app, host=host, port=port, reload=reload, **kwargs)
