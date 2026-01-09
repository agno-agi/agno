"""Schemas related to the AgentOS configuration"""

from contextlib import asynccontextmanager
from typing import Any, Generic, List, Literal, Optional, TypeVar, Union

from fastapi import FastAPI
from pydantic import BaseModel, Field, field_validator

from agno.db.base import AsyncBaseDb, BaseDb
from agno.os.app import AgentOS
from agno.os.interfaces.base import BaseInterface

# -- New classes --


class AuthorizationConfig(BaseModel):
    """Configuration for the JWT middleware"""

    verification_keys: Optional[List[str]] = None
    jwks_file: Optional[str] = None
    algorithm: Optional[str] = None
    verify_audience: Optional[bool] = None


class BackgroundTasksConfig(BaseModel):
    run_hooks_in_background: bool = False


class DatabasesConfig(BaseModel):
    default_db: Optional[Union[BaseDb, AsyncBaseDb]] = None
    auto_provision_dbs: bool = True
    auto_migrate: bool = False


class FastAPIConfig(BaseModel):
    app: Optional[FastAPI] = None
    cors_origin_list: Optional[List[str]] = Field(default=None, validate_default=True)
    enable_docs: bool = True
    lifespan: Optional[Any] = None
    on_route_conflict: Literal["preserve_agentos", "preserve_base_app", "error"] = "preserve_agentos"

    @field_validator("cors_origin_list", mode="before")
    def set_cors_origin_list(cls, cors_origin_list):
        valid_cors = cors_origin_list or []

        # Add Agno domains to cors origin list
        valid_cors.extend(
            [
                "http://localhost:3000",
                "https://agno.com",
                "https://www.agno.com",
                "https://app.agno.com",
                "https://os-stg.agno.com",
                "https://os.agno.com",
            ]
        )

        return valid_cors

    # -- Lifespans --

    @staticmethod
    @asynccontextmanager
    async def mcp_lifespan(_, mcp_tools):
        """Manage MCP connection lifecycle inside a FastAPI app"""
        for tool in mcp_tools:
            await tool.connect()

        yield

        for tool in mcp_tools:
            await tool.close()

    @staticmethod
    @asynccontextmanager
    async def http_client_lifespan(_):
        """Manage httpx client lifecycle for proper connection pool cleanup."""
        from agno.utils.http import aclose_default_clients

        yield

        await aclose_default_clients()

    @staticmethod
    @asynccontextmanager
    async def db_lifespan(app: FastAPI, agent_os: AgentOS):
        """Initializes databases in the event loop and closes them on shutdown."""
        if agent_os.auto_provision_dbs:
            agent_os._initialize_sync_databases()
            await agent_os._initialize_async_databases()

        yield

        await agent_os._close_databases()

    @staticmethod
    def _combine_app_lifespans(lifespans: list) -> Any:
        """Combine multiple FastAPI app lifespan context managers into one."""
        if len(lifespans) == 1:
            return lifespans[0]

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


class AgentOSConfig(BaseModel):
    """Complete configuration for an AgentOS instance"""

    fastapi_config: Optional[FastAPIConfig] = None
    databases_config: Optional[DatabasesConfig] = None
    background_tasks_config: Optional[BackgroundTasksConfig] = None
    interfaces: Optional[List[BaseInterface]] = None
    a2a_interface: bool = False
    enable_mcp_server: bool = False
    authorization: bool = False
    authorization_config: Optional[AuthorizationConfig] = None
    tracing: bool = False
    telemetry: bool = True

    @classmethod
    def from_path(cls, config_file_path: str) -> "AgentOSConfig":
        """Load a YAML config file and return the configuration as an AgentOSConfig instance."""
        from pathlib import Path

        # Validate the path points to a YAML file
        path = Path(config_file_path)
        if path.suffix.lower() not in [".yaml", ".yml"]:
            raise ValueError(f"Config file must have a .yaml or .yml extension, got: {config_file_path}")

        import yaml

        # Load the YAML file and init the instance
        with open(config_file_path, "r") as f:
            return cls.model_validate(yaml.safe_load(f))


# -- Old classes --


class EvalsDomainConfig(BaseModel):
    """Configuration for the Evals domain of the AgentOS"""

    display_name: Optional[str] = None
    available_models: Optional[List[str]] = None


class SessionDomainConfig(BaseModel):
    """Configuration for the Session domain of the AgentOS"""

    display_name: Optional[str] = None


class KnowledgeDomainConfig(BaseModel):
    """Configuration for the Knowledge domain of the AgentOS"""

    display_name: Optional[str] = None


class MetricsDomainConfig(BaseModel):
    """Configuration for the Metrics domain of the AgentOS"""

    display_name: Optional[str] = None


class MemoryDomainConfig(BaseModel):
    """Configuration for the Memory domain of the AgentOS"""

    display_name: Optional[str] = None


class TracesDomainConfig(BaseModel):
    """Configuration for the Traces domain of the AgentOS"""

    display_name: Optional[str] = None


DomainConfigType = TypeVar("DomainConfigType")


class DatabaseConfig(BaseModel, Generic[DomainConfigType]):
    """Configuration for a domain when used with the contextual database"""

    db_id: str
    domain_config: Optional[DomainConfigType] = None
    tables: Optional[List[str]] = None


class EvalsConfig(EvalsDomainConfig):
    """Configuration for the Evals domain of the AgentOS"""

    dbs: Optional[List[DatabaseConfig[EvalsDomainConfig]]] = None


class SessionConfig(SessionDomainConfig):
    """Configuration for the Session domain of the AgentOS"""

    dbs: Optional[List[DatabaseConfig[SessionDomainConfig]]] = None


class MemoryConfig(MemoryDomainConfig):
    """Configuration for the Memory domain of the AgentOS"""

    dbs: Optional[List[DatabaseConfig[MemoryDomainConfig]]] = None


class KnowledgeConfig(KnowledgeDomainConfig):
    """Configuration for the Knowledge domain of the AgentOS"""

    dbs: Optional[List[DatabaseConfig[KnowledgeDomainConfig]]] = None


class MetricsConfig(MetricsDomainConfig):
    """Configuration for the Metrics domain of the AgentOS"""

    dbs: Optional[List[DatabaseConfig[MetricsDomainConfig]]] = None


class TracesConfig(TracesDomainConfig):
    """Configuration for the Traces domain of the AgentOS"""

    dbs: Optional[List[DatabaseConfig[TracesDomainConfig]]] = None


class ChatConfig(BaseModel):
    """Configuration for the Chat page of the AgentOS"""

    quick_prompts: dict[str, list[str]]

    # Limit the number of quick prompts to 3 (per agent/team/workflow)
    @field_validator("quick_prompts")
    @classmethod
    def limit_lists(cls, v):
        for key, lst in v.items():
            if len(lst) > 3:
                raise ValueError(f"Too many quick prompts for '{key}', maximum allowed is 3")
        return v


class _AgentOSConfig(BaseModel):
    """General configuration for an AgentOS instance"""

    available_models: Optional[List[str]] = None
    chat: Optional[ChatConfig] = None
    evals: Optional[EvalsConfig] = None
    knowledge: Optional[KnowledgeConfig] = None
    memory: Optional[MemoryConfig] = None
    session: Optional[SessionConfig] = None
    metrics: Optional[MetricsConfig] = None
    traces: Optional[TracesConfig] = None
