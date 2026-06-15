"""Schemas related to the AgentOS configuration"""

from typing import Any, Callable, Dict, Generic, List, Optional, Set, TypeVar

from pydantic import BaseModel, ConfigDict, Field, field_validator


class MCPServerConfig(BaseModel):
    """Configuration for the AgentOS MCP server (served at ``/mcp``).

    Pair this with ``AgentOS(enable_mcp_server=True, mcp_config=...)`` to register
    your own tools, scope the built-in tools, gate the channel, and add middleware.
    With no ``mcp_config`` provided the MCP server behaves exactly as before: all
    built-in tools are registered and no extra gate or middleware is added.

    The built-in tools are tagged so they can be scoped as a group:
      - ``"core"``    -> ``get_agentos_config``, ``run_agent``, ``run_team``, ``run_workflow``
      - ``"session"`` -> session CRUD tools
      - ``"memory"``  -> memory CRUD tools
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    # Custom tools to register on the MCP server. Each entry may be a plain callable
    # (name/description inferred from ``__name__``/docstring) or an Agno tool/``Function``
    # (name/description taken from the tool, entrypoint used as the callable).
    #
    # Identity: a custom tool may declare a ``user_id`` parameter. AgentOS fills it with
    # the authenticated caller's id (the JWT subject) and hides it from the client-facing
    # schema, so clients cannot spoof it. Tools that need the full request can declare a
    # FastMCP ``Context`` parameter, which FastMCP injects natively.
    tools: Optional[List[Any]] = None

    # Master switch for the ~19 built-in tools. Set to False to ship ONLY your own tools.
    enable_builtin_tools: bool = True

    # Finer scoping over the built-ins via their tags ({"core", "session", "memory"}).
    # When ``include_tags`` is set, only built-ins carrying one of those tags are registered.
    # ``exclude_tags`` is then subtracted. Both are ignored when ``enable_builtin_tools`` is False.
    include_tags: Optional[Set[str]] = None
    exclude_tags: Optional[Set[str]] = None

    # Per-call gate for the MCP channel. Given the authenticated caller's user_id (the JWT
    # subject, or None when unauthenticated), return True to allow the request and False to
    # reject it with 401 -- before any tool or model runs. Runs after JWT verification.
    # Example: ``authorize=lambda user_id: user_id in OWNER_IDS`` for an owner-only channel.
    authorize: Optional[Callable[[Optional[str]], bool]] = None

    # Extra ASGI/Starlette middleware to add to the MCP app (e.g. DNS-rebinding protection).
    # Provide ``starlette.middleware.Middleware`` instances; they run outermost, ahead of the
    # JWT and ``authorize`` layers, in the order listed.
    middleware: Optional[List[Any]] = None


class AuthorizationConfig(BaseModel):
    """Configuration for the JWT middleware"""

    verification_keys: Optional[List[str]] = None
    jwks_file: Optional[str] = None
    algorithm: Optional[str] = None
    verify_audience: Optional[bool] = None
    audience: Optional[str] = None
    admin_scope: Optional[str] = None
    # Opt-in per-user data isolation. When True, AgentOS:
    #   - threads the JWT sub as ``user_id`` on every user-scoped DB read
    #     (sessions, memory, traces) for non-admin callers
    #   - coerces ``user_id`` on writes (sessions / memories / traces) so a
    #     non-admin caller cannot persist rows attributed to another user
    #   - enforces session/run ownership on cancel/resume/continue routes
    #   - requires session_id (and workflow_id on WS reconnect) for non-admins
    # When False (default) JWT/RBAC still apply, but routes operate on the
    # unscoped DB and don't add per-user ownership gates on top of RBAC.
    user_isolation: bool = False


class EvalsDomainConfig(BaseModel):
    """Configuration for the Evals domain of the AgentOS"""

    display_name: Optional[str] = None


class SessionDomainConfig(BaseModel):
    """Configuration for the Session domain of the AgentOS"""

    display_name: Optional[str] = None


class KnowledgeDomainConfig(BaseModel):
    """Configuration for the Knowledge domain of the AgentOS"""

    display_name: Optional[str] = None


class KnowledgeInstanceConfig(BaseModel):
    """Configuration for a single knowledge instance"""

    id: str
    name: str
    description: Optional[str] = None
    db_id: str
    table: str


class MetricsDomainConfig(BaseModel):
    """Configuration for the Metrics domain of the AgentOS"""

    display_name: Optional[str] = None


class MemoryDomainConfig(BaseModel):
    """Configuration for the Memory domain of the AgentOS"""

    display_name: Optional[str] = None


class LearningDomainConfig(BaseModel):
    """Configuration for the Learning domain of the AgentOS"""

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


class LearningConfig(LearningDomainConfig):
    """Configuration for the Learning domain of the AgentOS"""

    dbs: Optional[List[DatabaseConfig[LearningDomainConfig]]] = None


class KnowledgeDatabaseConfig(BaseModel):
    """Configuration for a knowledge database with its tables"""

    db_id: str
    domain_config: Optional[KnowledgeDomainConfig] = None
    tables: List[str] = []


class KnowledgeConfig(KnowledgeDomainConfig):
    """Configuration for the Knowledge domain of the AgentOS"""

    dbs: Optional[List[KnowledgeDatabaseConfig]] = None
    knowledge_instances: Optional[List[KnowledgeInstanceConfig]] = None


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


class Manifest(BaseModel):
    """OS-level UI metadata for an agent/team/workflow.

    Fields here are AgentOS UI metadata only. ``description`` is unrelated to
    ``Agent.description`` / ``Team.description`` / ``Workflow.description``,
    which are sent to the model.

    Rendering surfaces:
    - ``description``, ``labels``: home/landing card
    - ``quick_prompts``: chat page (max 3)
    """

    description: Optional[str] = None
    labels: Optional[List[str]] = None
    quick_prompts: Optional[List[str]] = None

    @field_validator("quick_prompts")
    @classmethod
    def _limit_quick_prompts(cls, v):
        if v is not None and len(v) > 3:
            raise ValueError("Too many quick prompts, maximum allowed is 3")
        return v


class AgentOSConfig(BaseModel):
    """General configuration for an AgentOS instance"""

    available_models: Optional[List[str]] = None
    chat: Optional[ChatConfig] = None
    manifest: Optional[Dict[str, Manifest]] = Field(
        default=None,
        description="Per-entity UI metadata keyed by agent/team/workflow id",
    )
    evals: Optional[EvalsConfig] = None
    knowledge: Optional[KnowledgeConfig] = None
    memory: Optional[MemoryConfig] = None
    learning: Optional[LearningConfig] = None
    session: Optional[SessionConfig] = None
    metrics: Optional[MetricsConfig] = None
    traces: Optional[TracesConfig] = None
