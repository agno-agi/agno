import json
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, Generic, List, Literal, Optional, TypeVar, Union

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    SerializerFunctionWrapHandler,
    field_validator,
    model_serializer,
    model_validator,
)

from agno.agent import Agent
from agno.agent.factory import AgentFactory
from agno.agent.protocol import AgentProtocol
from agno.agent.remote import RemoteAgent
from agno.db.base import SessionType
from agno.db.utils import detect_session_type
from agno.os.config import (
    ChatConfig,
    CompanySectionConfig,
    EvalsConfig,
    KnowledgeConfig,
    LearningConfig,
    Manifest,
    MemoryConfig,
    MetricsConfig,
    SessionConfig,
    TracesConfig,
)
from agno.os.scopes import split_scope
from agno.os.utils import extract_input_media, get_run_input, get_session_name, to_utc_datetime
from agno.run.base import CancellationStage
from agno.session import AgentSession, TeamSession, WorkflowSession
from agno.team.factory import TeamFactory
from agno.team.remote import RemoteTeam
from agno.team.team import Team
from agno.workflow.factory import WorkflowFactory
from agno.workflow.remote import RemoteWorkflow
from agno.workflow.workflow import Workflow


class ErrorResponse(BaseModel):
    """Body of a non-validation error (4xx/5xx that carry a string ``detail``).

    Mirrors what ``agno.os.app._error_body`` actually emits: ``detail`` is always present;
    ``error_id``/``error_type`` appear only when the error carries an identity
    (``AgnoError``/``AgnoHTTPException`` subclasses), and a plain ``HTTPException`` (or the
    auth middleware) yields ``detail`` alone. There is deliberately no ``error_code`` field:
    no handler has ever emitted one, so documenting it advertised a key clients never receive.
    """

    detail: str = Field(..., description="Human-readable error message")
    error_id: Optional[str] = Field(
        None, description="Stable identifier for the specific error, present only when the error carries one"
    )
    error_type: Optional[str] = Field(
        None, description="Category of the error, present only when the error carries one"
    )


class BadRequestResponse(ErrorResponse):
    model_config = ConfigDict(json_schema_extra={"example": {"detail": "Bad request"}})


class NotFoundResponse(ErrorResponse):
    model_config = ConfigDict(json_schema_extra={"example": {"detail": "Not found"}})


class UnauthorizedResponse(ErrorResponse):
    model_config = ConfigDict(json_schema_extra={"example": {"detail": "Unauthorized access"}})


class UnauthenticatedResponse(ErrorResponse):
    model_config = ConfigDict(json_schema_extra={"example": {"detail": "Unauthenticated access"}})


class InternalServerErrorResponse(ErrorResponse):
    model_config = ConfigDict(json_schema_extra={"example": {"detail": "Internal server error"}})


class ValidationErrorDetail(BaseModel):
    """One field-level error inside a 422 body, matching FastAPI's default shape."""

    loc: List[Union[str, int]] = Field(..., description="Path to the offending field, e.g. ['body', 'endpoint']")
    msg: str = Field(..., description="Human-readable error message")
    type: str = Field(..., description="Error type identifier, e.g. 'value_error' or 'missing'")


class ValidationErrorResponse(BaseModel):
    """422 body. Two runtime shapes share this status code, and the same endpoint can
    return either, so ``detail`` is typed as their union:

    - FastAPI's request-validation handler emits a **list** of field-level errors (built-in
      coercion errors and custom-validator ``ValueError``s alike).
    - A route that raises ``HTTPException(status_code=422, detail="...")`` for a semantic
      check (e.g. an invalid cron expression) emits a **string** through the HTTPException
      handler.
    """

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "detail": [
                    {
                        "type": "value_error",
                        "loc": ["body", "endpoint"],
                        "msg": "Value error, Endpoint must be a path, not a full URL",
                    }
                ]
            }
        }
    )

    detail: Union[str, List[ValidationErrorDetail]] = Field(
        ...,
        description=(
            "A single message for an explicitly raised 422, or a list of field-level errors "
            "for a request-validation failure"
        ),
    )


class ScopeItem(BaseModel):
    """Write shape for one scope grant — the canonical RBAC payload for every scope-bearing API.

    Endpoints that take scopes accept these objects only (a bare string is a validation
    error). ``effect`` is constrained here so every consumer rejects typos at the model
    layer; whether ``deny`` is *semantically* legal stays per-endpoint (roles support
    deny rules, service-account tokens are pure grants and reject it).
    """

    scope: str = Field(..., description="Scope string, e.g. 'agents:*:run'")
    effect: Literal["allow", "deny"] = Field("allow", description="'allow' or 'deny'")


class ScopeSchema(BaseModel):
    """Read shape for one scope — the parsed RBAC payload shared by every scope-bearing API.

    Mirrors the cloud RBAC scope shape ({raw, namespace, sub_namespace, permission, value})
    so a frontend renders scopes from any AgentOS API with one integration.
    """

    id: Optional[str] = Field(
        None,
        description="Scope id (always null here; kept for shape parity with the cloud RBAC API, "
        "which addresses scopes individually)",
    )
    raw: str = Field(..., description="Original scope string, e.g. 'agents:*:run'")
    namespace: str = Field(..., description="Resource namespace, e.g. 'agents'")
    sub_namespace: Optional[str] = Field(None, description="Specific resource id or wildcard '*'")
    permission: str = Field(..., description="Action, e.g. 'read' / 'run' / 'write'")
    value: str = Field("allow", description="'allow' or 'deny'")

    @classmethod
    def from_raw(cls, raw: str, value: str = "allow") -> "ScopeSchema":
        namespace, sub_namespace, permission = split_scope(raw)
        return cls(raw=raw, namespace=namespace, sub_namespace=sub_namespace, permission=permission, value=value)


class HealthResponse(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={"example": {"status": "ok", "instantiated_at": "2025-06-10T12:00:00Z"}}
    )

    status: str = Field(..., description="Health status of the service")
    instantiated_at: datetime = Field(..., description="Timestamp when service was instantiated")


class InterfaceResponse(BaseModel):
    type: str = Field(..., description="Type of the interface")
    version: str = Field(..., description="Version of the interface")
    route: str = Field(..., description="API route path")


class ManagerResponse(BaseModel):
    type: str = Field(..., description="Type of the manager")
    name: str = Field(..., description="Name of the manager")
    version: str = Field(..., description="Version of the manager")
    route: str = Field(..., description="API route path")


class Model(BaseModel):
    id: Optional[str] = Field(None, description="Model identifier")
    provider: Optional[str] = Field(None, description="Model provider name")


def _extract_model(entity: Any) -> Optional[Model]:
    """Pull id/provider off an entity's model, if present."""
    raw = getattr(entity, "model", None)
    if raw is None:
        return None
    model_id = getattr(raw, "id", None)
    provider = getattr(raw, "provider", None)
    if model_id is None and provider is None:
        return None
    return Model(id=model_id, provider=provider)


class FileSystemSummary(BaseModel):
    backend_type: str = Field(..., description="Filesystem backend type")
    db_id: Optional[str] = Field(None, description="Database identifier for a database-backed filesystem")
    db_schema: Optional[str] = Field(None, description="Database schema containing filesystem rows")
    table_name: Optional[str] = Field(None, description="Database table containing filesystem rows")
    namespace: str = Field(
        ...,
        description="Canonical namespace resolved for the caller; placeholders remain when identity is unavailable",
    )
    user_isolation: bool = Field(..., description="Whether the namespace is partitioned by user identity")
    max_file_bytes: int = Field(..., description="Maximum UTF-8 bytes per file")
    max_namespace_bytes: int = Field(..., description="Maximum bytes across the namespace")
    description: Optional[str] = Field(
        None,
        description="What the store is for, as written for the model. When several stores share an entry, "
        "the declared one's, else the first agent's by id",
    )


class FileSystemAgent(BaseModel):
    id: str = Field(..., description="ID of an agent using this filesystem namespace")
    access: Literal["full", "read_only"] = Field(
        default="full",
        description="Agent access to this namespace. Omitted for full access; tool-specific restrictions still apply.",
    )

    @model_serializer(mode="wrap")
    def _serialize_access(self, handler: SerializerFunctionWrapHandler):  # type: ignore[no-untyped-def]
        # Leave the return type unspecified so OpenAPI retains this model's fields.
        data = handler(self)
        if self.access == "full":
            data.pop("access", None)
        return data


class FileSystemNamespace(FileSystemSummary):
    id: str = Field(
        ...,
        description=(
            "Identifier to pass as filesystem_id to the /filesystem routes: the namespace, "
            "with the backend added when two filesystems share a namespace"
        ),
    )
    declared: bool = Field(False, description="Whether the filesystem is declared on the AgentOS")
    company: bool = Field(False, description="Whether this is the Company filesystem")
    available: Optional[bool] = Field(
        None,
        description=(
            "False when an agent failed to load and the id, a numbered one, cannot be opened until it does. "
            "Omitted otherwise"
        ),
    )
    file_count: Optional[int] = Field(
        None, description="Files the caller can read, at any depth. Set by /filesystem/namespaces; omitted when unknown"
    )
    folder_count: Optional[int] = Field(
        None, description="Distinct folders of those files, at any depth. Omitted when file_count is"
    )
    total_bytes: Optional[int] = Field(None, description="Size of those files. Omitted when file_count is")
    agents: List[FileSystemAgent] = Field(
        ...,
        description="Agents using this filesystem namespace and their access; empty when no agent holds it",
    )

    @model_validator(mode="before")
    @classmethod
    def _id_from_namespace(cls, data: Any) -> Any:
        # An AgentOS that sends no id addresses the filesystem by its namespace.
        if isinstance(data, dict) and "id" not in data and "namespace" in data:
            return {**data, "id": data["namespace"]}
        return data


class FileSystemConfig(BaseModel):
    enabled: Optional[bool] = Field(None, description="At least one file system is listed for the caller")
    namespaces: List[FileSystemNamespace] = Field(
        default_factory=list,
        description="Filesystem namespaces with their backend details, limits, and linked agents",
    )


def _extract_filesystem(filesystem: Any, agent: Any = None, user_id: Optional[str] = None) -> FileSystemSummary:
    """Describe a filesystem, with its namespace resolved for the caller.

    ``agent`` is the agent holding it, or None for a filesystem declared on the AgentOS.
    """
    # Partitioned by the run's user, or isolated by a namespace naming the user.
    user_isolation = bool(filesystem.user_scoped) or filesystem._namespace_carries_user
    filesystem = filesystem.resolve(user_id=user_id, agent_id=getattr(agent, "id", None))
    backend = filesystem.backend
    backend_db = getattr(backend, "db", None)
    if backend_db is not None or hasattr(backend, "db_engine"):
        backend_type = "db"
    elif hasattr(backend, "root"):
        backend_type = "local"
    else:
        backend_type = type(backend).__name__
    return FileSystemSummary(
        backend_type=backend_type,
        db_id=getattr(backend_db, "id", None),
        db_schema=getattr(backend, "db_schema", None),
        table_name=getattr(backend, "table_name", None),
        namespace=filesystem.namespace,
        user_isolation=user_isolation,
        max_file_bytes=filesystem.max_file_bytes,
        max_namespace_bytes=filesystem.max_namespace_bytes,
        description=filesystem.description,
    )


def _builtin_component_metadata(component: Any) -> Optional[Dict[str, Any]]:
    """Expose framework identity without publishing arbitrary metadata in summaries."""
    from agno.registry._reserved import is_framework_owned

    if is_framework_owned(component):
        return {"_agno": {"internal": True, "id": component.id}}
    return None


class AgentSummaryResponse(BaseModel):
    id: Optional[str] = Field(None, description="Unique identifier for the agent")
    name: Optional[str] = Field(None, description="Name of the agent")
    description: Optional[str] = Field(None, description="Description of the agent")
    db_id: Optional[str] = Field(None, description="Database identifier")
    model: Optional[Model] = Field(None, description="Model used by the agent")
    metadata: Optional[Dict[str, Any]] = Field(None, description="Additional metadata")
    sandboxed: bool = False

    @classmethod
    def from_agent(cls, agent: Union[Agent, AgentProtocol, RemoteAgent, AgentFactory]) -> "AgentSummaryResponse":
        from agno.agents.base import BaseExternalAgent

        agent_db = getattr(agent, "db", None)
        # Built-in adapters expose sdk. The framework fallback is only for third-party adapters that
        # satisfy AgentProtocol structurally and predate the rename; drop it with the framework alias.
        sdk = getattr(agent, "sdk", None) or getattr(agent, "framework", None)
        metadata = _builtin_component_metadata(agent)
        if sdk:
            metadata = {**(metadata or {}), "sdk": sdk}
        if isinstance(agent, AgentFactory):
            return cls(
                id=agent.id,
                name=agent.name,
                description=agent.description,
                db_id=agent.db.id if agent.db else None,
                model=_extract_model(agent),
            )
        return cls(
            id=agent.id,
            name=agent.name,
            description=getattr(agent, "description", None),
            db_id=agent_db.id if agent_db else None,
            model=_extract_model(agent),
            metadata=metadata,
            sandboxed=isinstance(agent, BaseExternalAgent) and agent.sandbox is not None,
        )


class TeamSummaryResponse(BaseModel):
    id: Optional[str] = Field(None, description="Unique identifier for the team")
    name: Optional[str] = Field(None, description="Name of the team")
    description: Optional[str] = Field(None, description="Description of the team")
    db_id: Optional[str] = Field(None, description="Database identifier")
    mode: Optional[str] = Field(None, description="Team execution mode (coordinate, route, broadcast, tasks)")
    model: Optional[Model] = Field(None, description="Model used by the team leader")

    metadata: Optional[Dict[str, Any]] = Field(None, description="Framework component metadata")
    sandboxed: bool = False

    @classmethod
    def from_team(cls, team: Union[Team, RemoteTeam, TeamFactory]) -> "TeamSummaryResponse":
        if isinstance(team, TeamFactory):
            return cls(
                id=team.id,
                name=team.name,
                description=team.description,
                db_id=team.db.id if team.db else None,
                model=_extract_model(team),
            )
        db_id = team.db.id if team.db else None
        mode = team.mode.value if hasattr(team, "mode") and team.mode else None
        return cls(
            id=team.id,
            name=team.name,
            description=team.description,
            db_id=db_id,
            mode=mode,
            model=_extract_model(team),
            metadata=_builtin_component_metadata(team),
        )


class WorkflowSummaryResponse(BaseModel):
    id: Optional[str] = Field(None, description="Unique identifier for the workflow")
    name: Optional[str] = Field(None, description="Name of the workflow")
    description: Optional[str] = Field(None, description="Description of the workflow")
    db_id: Optional[str] = Field(None, description="Database identifier")
    is_factory: bool = Field(False, description="Whether this workflow is a factory")
    factory_input_schema: Optional[Dict[str, Any]] = Field(None, description="JSON Schema for factory_input")
    is_component: bool = Field(False, description="Whether this workflow was created via Builder")
    current_version: Optional[int] = Field(None, description="Current published version number")
    stage: Optional[str] = Field(None, description="Stage of the loaded config (draft/published)")
    sandboxed: bool = False

    @classmethod
    def from_workflow(
        cls,
        workflow: Union[Workflow, RemoteWorkflow, WorkflowFactory],
        is_component: bool = False,
    ) -> "WorkflowSummaryResponse":
        if isinstance(workflow, WorkflowFactory):
            factory_input_schema = None
            if workflow.input_schema is not None:
                try:
                    factory_input_schema = workflow.input_schema.model_json_schema()
                except Exception:
                    pass
            return cls(
                id=workflow.id,
                name=workflow.name,
                description=workflow.description,
                db_id=workflow.db.id if workflow.db else None,
                is_factory=True,
                factory_input_schema=factory_input_schema,
            )
        db_id = workflow.db.id if workflow.db else None
        return cls(
            id=workflow.id,
            name=workflow.name,
            description=workflow.description,
            db_id=db_id,
            is_component=is_component,
            current_version=getattr(workflow, "_version", None),
            stage=getattr(workflow, "_stage", None),
        )


class McpOAuthInfo(BaseModel):
    """OAuth discovery details for an MCP endpoint protected by ``AgentOS(mcp_auth=...)``."""

    authorization_servers: Optional[List[str]] = Field(
        None, description="Issuer URL(s) of the authorization server(s) protecting the MCP endpoint"
    )
    resource: Optional[str] = Field(None, description="RFC 9728 resource URL advertised for the MCP endpoint")


class McpInfo(BaseModel):
    """MCP server availability for the /info endpoint."""

    enabled: bool = Field(False, description="Whether the MCP server is enabled on this OS instance")
    path: Optional[str] = Field(None, description="Path where the MCP server is mounted, null when disabled")
    oauth: Optional[McpOAuthInfo] = Field(
        None, description="OAuth discovery details when the MCP endpoint is OAuth-protected, null otherwise"
    )
    tool_run_endpoint: bool = Field(
        False,
        description=(
            "Whether this deployment serves the plain-HTTP tool runner at "
            "`{path}/server/tools/{tool_name}/run`. False both when the MCP server is off and "
            "when it is on with `MCPConfig(tool_run_endpoint=False)`, so a client can tell upfront "
            "whether running a tool is possible instead of discovering it on the call."
        ),
    )


class InfoResponse(BaseModel):
    """Response schema for the /info endpoint returning lightweight OS metadata."""

    os_id: str = Field(..., description="Unique identifier for the OS instance")
    name: Optional[str] = Field(None, description="Name of the OS instance")
    os_version: str = Field(..., description="Version of this AgentOS instance")
    agno_version: str = Field(..., description="Version of the agno framework")
    agent_count: int = Field(0, description="Number of agents registered in the OS")
    team_count: int = Field(0, description="Number of teams registered in the OS")
    workflow_count: int = Field(0, description="Number of workflows registered in the OS")
    mcp: McpInfo = Field(default_factory=McpInfo, description="MCP server availability for this OS instance")
    auth_mode: Literal["none", "security_key", "jwt"] = Field(
        "none",
        description=(
            "Authentication mode enforced on the REST/WS plane of this OS instance. MCP OAuth, "
            "when enabled, is described separately under `mcp.oauth`."
        ),
    )
    user_isolation: bool = Field(
        False,
        description=(
            "Whether per-user data isolation is switched on for this OS instance. Read it together "
            "with `auth_mode`: under `jwt` the token names the user, so a client sends nothing extra. "
            "Under `none` or `security_key` the OS cannot tell who a request is for, so a client that "
            "wants each user to see only their own data sends that user's id as `user_id` on every "
            "request, reads included, not only on runs."
        ),
    )


class QueueCapabilities(BaseModel):
    """Deployment-level background-run capabilities: what a client may rely on
    when deciding whether to render queue-aware UI (e.g. a chat tray).

    Reported as EFFECTIVE behavior, not raw settings: queue_per_session is
    true only when a durable queue actually enforces the per-session gate -
    a queue_per_session flag without durable=True, or with a custom store
    that does not serialize sessions, gates nothing and is reported false. Readable by any authenticated caller (deployment
    capability, not operator data - the admin-scoped /queue surface stays
    the only view of actual jobs).

    durable and queue_per_session describe submissions the durable queue can carry. A
    background submission the queue cannot carry (media uploads, payloads
    plain JSON cannot store, factory-backed or off-registry components)
    executes in-process on the accepting replica, outside the gate and
    without durability, and the server logs each such bypass; the client
    still receives 202 PENDING. A caller that sends those knows it is
    sending them; the capability does not change per submission."""

    durable: bool = Field(
        ...,
        description="Accepted background runs survive crashes and deploys (ticketed queue with a worker)",
    )
    queue_per_session: bool = Field(
        ...,
        description="Same-session background submissions execute at most one at a time, FIFO by submission; "
        "false when no durable queue enforces the gate",
    )
    cross_container: bool = Field(
        False,
        description="Background runs can be cancelled and their events read from any replica, "
        "because cancellation and the event stream are both shared rather than in-process",
    )


class AuthorizationReport(BaseModel):
    """How requests to this AgentOS are authenticated and authorized.

    Reported as EFFECTIVE behavior, not constructor arguments: each value is read from
    what the running app enforces. `enabled`, `mode` and `user_isolation` are returned to
    every caller that can read /config. The remaining fields are returned only to an
    administrator of this AgentOS, so their absence beside a present `enabled` means the
    caller may not see them, while an absent block means the server predates the report.

    Every field is optional so a client parses responses from servers that omit it.
    Holds no keys, key counts, key locations, audience or issuer values, or role scopes."""

    enabled: Optional[bool] = Field(
        None,
        description="Scopes or roles are enforced on requests. False when callers are only authenticated, or not at all",
    )
    mode: Optional[Literal["none", "security_key", "jwt"]] = Field(
        None, description="Authentication mode on the REST/WS plane, the same value /info reports as `auth_mode`"
    )
    user_isolation: Optional[bool] = Field(
        None, description="Per-user data isolation is switched on, the same value /info reports"
    )
    managed_roles: Optional[bool] = Field(
        None,
        description="Roles managed on this AgentOS decide requests. False under scope-only authorization "
        "and when a custom authorization provider decides alone. Administrators only",
    )
    roles_from_token: Optional[bool] = Field(
        None,
        description="A caller's roles can also come from a claim on their token, so the stored assignments "
        "do not list every role a user holds. Administrators only",
    )
    default_role: Optional[str] = Field(
        None,
        description="Name of the role a newly provisioned user receives; absent when no default is set. "
        "Administrators only",
    )
    token_scopes_trusted: Optional[bool] = Field(
        None,
        description="The scopes carried on a caller's token count toward access decisions: true only when "
        "a scope plane actually runs, alone or beside managed roles. Administrators only",
    )
    audience_verified: Optional[bool] = Field(
        None,
        description="A token's audience claim is checked against this AgentOS before the token is accepted. "
        "Administrators only",
    )


class FeatureStatus(BaseModel):
    """Whether one optional AgentOS feature is running."""

    enabled: Optional[bool] = Field(None, description="The feature is running on this AgentOS")


class UserDirectoryStatus(FeatureStatus):
    """The user directory: the roster of users and the switch that disables one."""

    auto_provision: Optional[bool] = Field(None, description="A user is added to the directory on their first request")
    fail_closed: Optional[bool] = Field(
        None, description="A request is refused when the directory cannot be read to check the user"
    )


class AuditStatus(FeatureStatus):
    """The audit trails: changes to roles and users, and access decisions.

    `enabled` means events are being recorded. The `*_readable` fields say whether the
    matching trail can be read back through this AgentOS: a trail is recorded but not
    readable when the sink only writes (a log sink) or the routes that serve it are not
    mounted."""

    changes_readable: Optional[bool] = Field(
        None, description="GET /authz/audit serves the change trail instead of answering 404"
    )
    decisions_readable: Optional[bool] = Field(
        None, description="GET /authz/decisions serves the decision trail instead of answering 404"
    )


class MediaStorageStatus(FeatureStatus):
    """Where the media routes read stored media from."""

    backend: Optional[str] = Field(None, description="Storage backend: s3, gcs or local")


class PublicStatus(FeatureStatus):
    """The public surface: components served to outside callers under public input and rate limits."""

    agents: Optional[List[str]] = Field(None, description="IDs of the agents anonymous callers can run")
    teams: Optional[List[str]] = Field(None, description="IDs of the teams anonymous callers can run")
    workflows: Optional[List[str]] = Field(
        None, description="IDs of the public workflows. Callers still need a bearer token, unlike agents and teams"
    )
    mcp: Optional[bool] = Field(
        None,
        description="The MCP server is on the public surface. Anonymous only without mcp_auth; "
        "/info carries the OAuth details when sign-in is required",
    )


class KnowledgeReport(KnowledgeConfig):
    """The /config knowledge block. KnowledgeConfig is also operator input, so `enabled` lives here only."""

    enabled: Optional[bool] = Field(None, description="At least one knowledge instance is served")


class TracesReport(TracesConfig):
    """The /config traces block. TracesConfig is also operator input, so `enabled` lives here only."""

    enabled: Optional[bool] = Field(
        None, description="Runs are traced and the spans stored by this AgentOS; dbs lists where to read them"
    )


class ConfigResponse(BaseModel):
    """Response schema for the general config endpoint.

    Each optional feature is one top-level block that says whether it is on, reported
    as EFFECTIVE behavior: a feature that was requested but could not start is off.
    Most carry `enabled`; three keep the off signal older clients read: `company` is
    null, `interfaces` is empty and `queue.durable` is false. `user_directory`, `audit`
    and `public` go to administrators only. The data blocks (session, memory, learning,
    metrics, evals) say where each domain is stored and are not features."""

    os_id: str = Field(..., description="Unique identifier for the OS instance")
    name: Optional[str] = Field(None, description="Name of the OS instance")
    description: Optional[str] = Field(None, description="Description of the OS instance")
    available_models: List[Model] = Field(
        default_factory=list,
        description="Unique models (id + provider) in use by agents and teams in this OS",
    )
    os_database: Optional[str] = Field(None, description="ID of the database used for the OS instance")
    databases: List[str] = Field(..., description="List of database IDs used by the components of the OS instance")
    chat: Optional[ChatConfig] = Field(None, description="Chat configuration")
    manifest: Optional[Dict[str, Manifest]] = Field(
        None,
        description="Per-entity UI metadata keyed by agent/team/workflow id",
    )

    session: Optional[SessionConfig] = Field(None, description="Session configuration")
    metrics: Optional[MetricsConfig] = Field(None, description="Metrics configuration")
    memory: Optional[MemoryConfig] = Field(None, description="Memory configuration")
    learning: Optional[LearningConfig] = Field(None, description="Learning configuration")
    company: Optional[CompanySectionConfig] = Field(None, description="Company configuration")
    filesystem: Optional[FileSystemConfig] = Field(None, description="Filesystem configuration")
    knowledge: Optional[KnowledgeReport] = Field(None, description="Knowledge configuration")
    evals: Optional[EvalsConfig] = Field(None, description="Evaluations configuration")
    traces: Optional[TracesReport] = Field(None, description="Traces configuration")
    # Optional for CLIENT compatibility (the SDK parses this same schema, and
    # older servers omit the field); the server always populates it.
    queue: Optional[QueueCapabilities] = Field(None, description="Background-run queue capabilities")
    authorization: Optional[AuthorizationReport] = Field(
        None, description="How requests are authenticated and authorized; detail fields for administrators only"
    )
    scheduler: Optional[FeatureStatus] = Field(None, description="Scheduled runs are polled and executed")
    mcp: Optional[FeatureStatus] = Field(
        None, description="The MCP server is served; /info carries its path and OAuth details"
    )
    manager: Optional[FeatureStatus] = Field(
        None, description="The OS Manager team is served; teams[] carries it as an internal team"
    )
    media_storage: Optional[MediaStorageStatus] = Field(
        None, description="Stored media is served from a storage backend instead of only the database"
    )
    telemetry: Optional[FeatureStatus] = Field(
        None,
        description="Usage telemetry is sent to Agno: the AgentOS launch ping, or run telemetry "
        "from a local agent, team or workflow",
    )
    temporary_runs: Optional[FeatureStatus] = Field(
        None, description="The run routes accept store_run=false, a run that is answered but not saved"
    )
    user_directory: Optional[UserDirectoryStatus] = Field(None, description="User directory. Administrators only")
    audit: Optional[AuditStatus] = Field(None, description="Audit trails. Administrators only")
    public: Optional[PublicStatus] = Field(
        None, description="Components served under public limits. Administrators only"
    )

    agents: List[AgentSummaryResponse] = Field(..., description="List of registered agents")
    teams: List[TeamSummaryResponse] = Field(..., description="List of registered teams")
    workflows: List[WorkflowSummaryResponse] = Field(..., description="List of registered workflows")
    interfaces: List[InterfaceResponse] = Field(..., description="List of available interfaces")

    @model_serializer(mode="wrap")
    def _serialize_config(self, handler: SerializerFunctionWrapHandler) -> Dict[str, Any]:
        data = handler(self)
        # Clients use an explicit null to hide Company when it is not configured.
        data.setdefault("company", None)
        return data


class ModelResponse(BaseModel):
    name: Optional[str] = Field(None, description="Name of the model")
    model: Optional[str] = Field(None, description="Model identifier")
    provider: Optional[str] = Field(None, description="Model provider name")


class WorkflowRunRequest(BaseModel):
    input: Dict[str, Any] = Field(..., description="Input parameters for the workflow run")
    user_id: Optional[str] = Field(None, description="User identifier for the workflow run")
    session_id: Optional[str] = Field(None, description="Session identifier for context persistence")


def _agent_metadata(
    metadata: Optional[Dict[str, Any]], agent_data: Optional[Dict[str, Any]]
) -> Optional[Dict[str, Any]]:
    """Expose the persisted adapter identity without changing stored user metadata.
    A malformed agent_data (not a mapping) means no label rather than a failed read."""
    sdk = (agent_data.get("sdk") or agent_data.get("framework")) if isinstance(agent_data, dict) else None
    if isinstance(sdk, str) and sdk:
        return {**(metadata or {}), "sdk": sdk}
    return dict(metadata) if metadata is not None else None


class SessionSchema(BaseModel):
    session_id: str = Field(..., description="Unique identifier for the session")
    session_name: str = Field(..., description="Human-readable name for the session")
    session_state: Optional[dict] = Field(None, description="Current state data of the session")
    created_at: Optional[datetime] = Field(None, description="Timestamp when session was created")
    updated_at: Optional[datetime] = Field(None, description="Timestamp when session was last updated")
    # Enhanced fields for richer list responses
    session_type: Optional[str] = Field(None, description="Type of session: agent, team, or workflow")
    user_id: Optional[str] = Field(None, description="User ID associated with the session")
    agent_id: Optional[str] = Field(None, description="Agent ID if this is an agent session")
    team_id: Optional[str] = Field(None, description="Team ID if this is a team session")
    workflow_id: Optional[str] = Field(None, description="Workflow ID if this is a workflow session")
    session_summary: Optional[dict] = Field(None, description="Summary of session interactions")
    metrics: Optional[dict] = Field(None, description="Session metrics")
    total_tokens: Optional[int] = Field(None, description="Total tokens used in this session")
    metadata: Optional[dict] = Field(None, description="Additional metadata")

    @classmethod
    def from_dict(cls, session: Dict[str, Any]) -> "SessionSchema":
        session_name = session.get("session_name")
        if not session_name:
            session_name = get_session_name(session)
        session_data = session.get("session_data", {}) or {}

        created_at = to_utc_datetime(session.get("created_at", 0))
        updated_at = to_utc_datetime(session.get("updated_at", created_at))

        # Extract metrics from session_data
        metrics = session_data.get("session_metrics", None)
        total_tokens = metrics.get("total_tokens") if metrics else None

        # Extract summary
        summary = session.get("summary")
        if summary and hasattr(summary, "to_dict"):
            summary = summary.to_dict()

        # Determine session_type using shared util
        session_type_str: Optional[str] = detect_session_type(session)

        return cls(
            session_id=session.get("session_id", ""),
            session_name=session_name,
            session_state=session_data.get("session_state", None),
            created_at=created_at,
            updated_at=updated_at,
            session_type=session_type_str,
            user_id=session.get("user_id"),
            agent_id=session.get("agent_id"),
            team_id=session.get("team_id"),
            workflow_id=session.get("workflow_id"),
            session_summary=summary,
            metrics=metrics,
            total_tokens=total_tokens,
            metadata=_agent_metadata(session.get("metadata"), session.get("agent_data"))
            if session_type_str == SessionType.AGENT.value
            else session.get("metadata"),
        )


class DeleteSessionRequest(BaseModel):
    session_ids: List[str] = Field(..., description="List of session IDs to delete", min_length=1)
    session_types: List[SessionType] = Field(..., description="Types of sessions to delete", min_length=1)


class CreateSessionRequest(BaseModel):
    session_id: Optional[str] = Field(None, description="Optional session ID (generated if not provided)")
    session_name: Optional[str] = Field(None, description="Name for the session")
    session_state: Optional[Dict[str, Any]] = Field(None, description="Initial session state")
    metadata: Optional[Dict[str, Any]] = Field(None, description="Additional metadata")
    user_id: Optional[str] = Field(None, description="User ID associated with the session")
    agent_id: Optional[str] = Field(None, description="Agent ID if this is an agent session")
    team_id: Optional[str] = Field(None, description="Team ID if this is a team session")
    workflow_id: Optional[str] = Field(None, description="Workflow ID if this is a workflow session")


class UpdateSessionRequest(BaseModel):
    session_name: Optional[str] = Field(None, description="Updated session name")
    session_state: Optional[Dict[str, Any]] = Field(None, description="Updated session state")
    metadata: Optional[Dict[str, Any]] = Field(None, description="Updated metadata")
    summary: Optional[Dict[str, Any]] = Field(None, description="Session summary")


class AgentSessionDetailSchema(BaseModel):
    user_id: Optional[str] = Field(None, description="User ID associated with the session")
    agent_session_id: str = Field(..., description="Unique agent session identifier")
    session_id: str = Field(..., description="Session identifier")
    session_name: str = Field(..., description="Human-readable session name")
    session_summary: Optional[dict] = Field(None, description="Summary of session interactions")
    session_state: Optional[dict] = Field(None, description="Current state of the session")
    agent_id: Optional[str] = Field(None, description="Agent ID used in this session")
    total_tokens: Optional[int] = Field(None, description="Total tokens used in this session")
    agent_data: Optional[dict] = Field(None, description="Agent-specific data")
    metrics: Optional[dict] = Field(None, description="Session metrics")
    metadata: Optional[dict] = Field(None, description="Additional metadata")
    chat_history: Optional[List[dict]] = Field(None, description="Complete chat history")
    created_at: Optional[datetime] = Field(None, description="Session creation timestamp")
    updated_at: Optional[datetime] = Field(None, description="Last update timestamp")

    @classmethod
    def from_session(cls, session: AgentSession) -> "AgentSessionDetailSchema":
        session_name = get_session_name({**session.to_dict(), "session_type": "agent"})
        created_at = datetime.fromtimestamp(session.created_at, tz=timezone.utc) if session.created_at else None
        updated_at = datetime.fromtimestamp(session.updated_at, tz=timezone.utc) if session.updated_at else created_at
        return cls(
            user_id=session.user_id,
            agent_session_id=session.session_id,
            session_id=session.session_id,
            session_name=session_name,
            session_summary=session.summary.to_dict() if session.summary else None,
            session_state=session.session_data.get("session_state", None) if session.session_data else None,
            agent_id=session.agent_id if session.agent_id else None,
            agent_data=session.agent_data,
            total_tokens=session.session_data.get("session_metrics", {}).get("total_tokens")
            if session.session_data
            else None,
            metrics=session.session_data.get("session_metrics", {}) if session.session_data else None,  # type: ignore
            metadata=_agent_metadata(session.metadata, session.agent_data),
            chat_history=[message.to_dict() for message in session.get_chat_history()],
            created_at=to_utc_datetime(created_at),
            updated_at=to_utc_datetime(updated_at),
        )


class TeamSessionDetailSchema(BaseModel):
    session_id: str = Field(..., description="Unique session identifier")
    session_name: str = Field(..., description="Human-readable session name")
    user_id: Optional[str] = Field(None, description="User ID associated with the session")
    team_id: Optional[str] = Field(None, description="Team ID used in this session")
    session_summary: Optional[dict] = Field(None, description="Summary of team interactions")
    session_state: Optional[dict] = Field(None, description="Current state of the session")
    metrics: Optional[dict] = Field(None, description="Session metrics")
    team_data: Optional[dict] = Field(None, description="Team-specific data")
    metadata: Optional[dict] = Field(None, description="Additional metadata")
    chat_history: Optional[List[dict]] = Field(None, description="Complete chat history")
    created_at: Optional[datetime] = Field(None, description="Session creation timestamp")
    updated_at: Optional[datetime] = Field(None, description="Last update timestamp")
    total_tokens: Optional[int] = Field(None, description="Total tokens used in this session")

    @classmethod
    def from_session(cls, session: TeamSession) -> "TeamSessionDetailSchema":
        session_dict = session.to_dict()
        session_name = get_session_name({**session_dict, "session_type": "team"})
        created_at = datetime.fromtimestamp(session.created_at, tz=timezone.utc) if session.created_at else None
        updated_at = datetime.fromtimestamp(session.updated_at, tz=timezone.utc) if session.updated_at else created_at
        return cls(
            session_id=session.session_id,
            team_id=session.team_id,
            session_name=session_name,
            session_summary=session_dict.get("summary") if session_dict.get("summary") else None,
            user_id=session.user_id,
            team_data=session.team_data,
            session_state=session.session_data.get("session_state", None) if session.session_data else None,
            total_tokens=session.session_data.get("session_metrics", {}).get("total_tokens")
            if session.session_data
            else None,
            metrics=session.session_data.get("session_metrics", {}) if session.session_data else None,
            metadata=session.metadata,
            chat_history=[message.to_dict() for message in session.get_chat_history()],
            created_at=to_utc_datetime(created_at),
            updated_at=to_utc_datetime(updated_at),
        )


class WorkflowSessionDetailSchema(BaseModel):
    user_id: Optional[str] = Field(None, description="User ID associated with the session")
    workflow_id: Optional[str] = Field(None, description="Workflow ID used in this session")
    workflow_name: Optional[str] = Field(None, description="Name of the workflow")
    session_id: str = Field(..., description="Unique session identifier")
    session_name: str = Field(..., description="Human-readable session name")

    session_data: Optional[dict] = Field(None, description="Complete session data")
    session_state: Optional[dict] = Field(None, description="Current workflow state")
    workflow_data: Optional[dict] = Field(None, description="Workflow-specific data")
    metadata: Optional[dict] = Field(None, description="Additional metadata")

    created_at: Optional[datetime] = Field(None, description="Session creation timestamp")
    updated_at: Optional[datetime] = Field(None, description="Last update timestamp")

    @classmethod
    def from_session(cls, session: WorkflowSession) -> "WorkflowSessionDetailSchema":
        session_dict = session.to_dict()
        session_name = get_session_name({**session_dict, "session_type": "workflow"})
        created_at = datetime.fromtimestamp(session.created_at, tz=timezone.utc) if session.created_at else None
        updated_at = datetime.fromtimestamp(session.updated_at, tz=timezone.utc) if session.updated_at else created_at
        return cls(
            session_id=session.session_id,
            user_id=session.user_id,
            workflow_id=session.workflow_id,
            workflow_name=session.workflow_name,
            session_name=session_name,
            session_data=session.session_data,
            session_state=session.session_data.get("session_state", None) if session.session_data else None,
            workflow_data=session.workflow_data,
            metadata=session.metadata,
            created_at=to_utc_datetime(created_at),
            updated_at=to_utc_datetime(updated_at),
        )


# One text for the three run schemas, built from the enum so it cannot drift
# from the members a client may receive
CANCELLATION_STAGE_DESCRIPTION = (
    "For CANCELLED runs, where the run was when it was cancelled: "
    + ", ".join(member.value for member in CancellationStage)
    + ". Absent means unknown."
)


class CompactionSchema(BaseModel):
    """What one compaction did to the context, without the summary text or the archived messages."""

    id: Optional[str] = Field(None, description="Unique identifier for the compaction record")
    run_id: Optional[str] = Field(
        None, description="Run that compacted its own context. Not set for a manual compaction, which no run made"
    )
    messages_compacted: int = Field(0, description="Number of history messages the compaction replaced")
    tokens_before: Optional[int] = Field(None, description="Context size before the compaction, in tokens")
    tokens_after: Optional[int] = Field(None, description="Context size after the compaction, in tokens")
    created_at: Optional[datetime] = Field(None, description="Compaction creation timestamp")
    archived: bool = Field(False, description="Whether the replaced messages were stored and can be read back")

    @classmethod
    def from_dict(cls, record: Dict[str, Any]) -> "CompactionSchema":
        return cls(
            id=record.get("compaction_id"),
            run_id=record.get("run_id"),
            messages_compacted=record.get("messages_compacted") or 0,
            tokens_before=record.get("tokens_before"),
            tokens_after=record.get("tokens_after"),
            created_at=to_utc_datetime(record.get("created_at")),
            archived=bool(record.get("archived_messages")),
        )


class RunSchema(BaseModel):
    run_id: str = Field(..., description="Unique identifier for the run")
    run_index: Optional[int] = Field(None, description="0-based position of the run in its session")
    parent_run_id: Optional[str] = Field(None, description="Parent run ID if this is a nested run")
    agent_id: Optional[str] = Field(None, description="Agent ID that executed this run")
    user_id: Optional[str] = Field(None, description="User ID associated with the run")
    status: Optional[str] = Field(None, description="Run status (PENDING, RUNNING, COMPLETED, ERROR, etc.)")
    cancellation_stage: Optional[str] = Field(None, description=CANCELLATION_STAGE_DESCRIPTION)
    run_input: Optional[str] = Field(None, description="Input provided to the run")
    content: Optional[Union[str, dict]] = Field(None, description="Output content from the run")
    run_response_format: Optional[str] = Field(None, description="Format of the response (text/json)")
    reasoning_content: Optional[str] = Field(None, description="Reasoning content if reasoning was enabled")
    reasoning_steps: Optional[List[dict]] = Field(None, description="List of reasoning steps")
    metrics: Optional[dict] = Field(None, description="Performance and usage metrics")
    metadata: Optional[dict] = Field(None, description="Run metadata, including sdk for external agent sessions")
    messages: Optional[List[dict]] = Field(None, description="Message history for the run")
    tools: Optional[List[dict]] = Field(None, description="Tools used in the run")
    events: Optional[List[dict]] = Field(None, description="Events generated during the run")
    created_at: Optional[datetime] = Field(None, description="Run creation timestamp")
    references: Optional[List[dict]] = Field(None, description="References cited in the run")
    citations: Optional[Dict[str, Any]] = Field(
        None, description="Citations from the model (e.g., from Gemini grounding/search)"
    )
    reasoning_messages: Optional[List[dict]] = Field(None, description="Reasoning process messages")
    session_state: Optional[dict] = Field(None, description="Session state at the end of the run")
    images: Optional[List[dict]] = Field(None, description="Images included in the run")
    videos: Optional[List[dict]] = Field(None, description="Videos included in the run")
    audio: Optional[List[dict]] = Field(None, description="Audio files included in the run")
    files: Optional[List[dict]] = Field(None, description="Files included in the run")
    response_audio: Optional[dict] = Field(None, description="Audio response if generated")
    input_media: Optional[Dict[str, Any]] = Field(None, description="Input media attachments")
    followups: Optional[List[str]] = Field(None, description="Followup suggestions generated after the run")
    # set when the run was created via /continue (fork /
    # regenerate / time-travel) or via /sessions/{id}/branch. Client consumes
    # these to render parent → child relationships in the run timeline.
    forked_from_run_id: Optional[str] = Field(
        None, description="If this run was forked from another run, the source run's ID"
    )
    forked_from_message_index: Optional[int] = Field(
        None,
        description="If this run was forked, the message index at which the source was truncated; for a run copied by a session branch and continued, the index where the continued work starts",
    )
    forked_from_session_id: Optional[str] = Field(
        None,
        description="If this run was created via session branch, the source session's ID; cleared once the copied run is continued in this session",
    )
    regenerated_from: Optional[str] = Field(
        None, description="If this run was produced via regenerate=true, the source run's ID"
    )
    last_checkpoint_at_message_index: Optional[int] = Field(
        None, description="Message index of the most recent mid-run checkpoint (checkpoint='tool-batch' runs)"
    )

    @classmethod
    def from_dict(cls, run_dict: Dict[str, Any], *, session: Optional[Dict[str, Any]] = None) -> "RunSchema":
        run_input = get_run_input(run_dict)
        run_response_format = "text" if run_dict.get("content_type", "str") == "str" else "json"
        agent_data = None
        # Member/step runs must not inherit another agent's session identity.
        if (
            session is not None
            and detect_session_type(session) == SessionType.AGENT.value
            and run_dict.get("agent_id") in (None, session.get("agent_id"))
        ):
            agent_data = session.get("agent_data")

        return cls(
            run_id=run_dict.get("run_id", ""),
            parent_run_id=run_dict.get("parent_run_id", ""),
            agent_id=run_dict.get("agent_id", ""),
            user_id=run_dict.get("user_id", ""),
            status=run_dict.get("status"),
            cancellation_stage=run_dict.get("cancellation_stage"),
            run_input=run_input,
            content=run_dict.get("content", ""),
            run_response_format=run_response_format,
            reasoning_content=run_dict.get("reasoning_content", ""),
            reasoning_steps=run_dict.get("reasoning_steps", []),
            metrics=run_dict.get("metrics", {}),
            metadata=_agent_metadata(run_dict.get("metadata"), agent_data),
            messages=[message for message in run_dict.get("messages", [])] if run_dict.get("messages") else None,
            tools=[tool for tool in run_dict.get("tools", [])] if run_dict.get("tools") else None,
            events=[event for event in run_dict["events"]] if run_dict.get("events") else None,
            references=run_dict.get("references", []),
            citations=run_dict.get("citations", None),
            reasoning_messages=run_dict.get("reasoning_messages", []),
            session_state=run_dict.get("session_state"),
            images=run_dict.get("images", []),
            videos=run_dict.get("videos", []),
            audio=run_dict.get("audio", []),
            files=run_dict.get("files", []),
            response_audio=run_dict.get("response_audio", None),
            input_media=extract_input_media(run_dict),
            followups=run_dict.get("followups", None),
            created_at=to_utc_datetime(run_dict.get("created_at")),
            forked_from_run_id=run_dict.get("forked_from_run_id"),
            forked_from_message_index=run_dict.get("forked_from_message_index"),
            forked_from_session_id=run_dict.get("forked_from_session_id"),
            regenerated_from=run_dict.get("regenerated_from"),
            last_checkpoint_at_message_index=run_dict.get("last_checkpoint_at_message_index"),
        )


_RUN_PREVIEW_CHARS = 280


class SessionRunPreviewSchema(BaseModel):
    """Lightweight session-run listing entry: the shape a queue tray or
    session sidebar polls for. Deliberately excludes messages, events, media,
    metrics and step results - the full shapes stay on the default listing
    and the single-run endpoint. Previews are truncated to 280 characters."""

    run_id: str = Field(..., description="Unique identifier for the run")
    run_index: Optional[int] = Field(None, description="0-based position of the run in its session")
    parent_run_id: Optional[str] = Field(None, description="Parent run ID if this is a nested run")
    agent_id: Optional[str] = Field(None, description="Agent ID, when this is an agent run")
    team_id: Optional[str] = Field(None, description="Team ID, when this is a team run")
    workflow_id: Optional[str] = Field(None, description="Workflow ID, when this is a workflow run")
    user_id: Optional[str] = Field(None, description="User ID associated with the run")
    status: Optional[str] = Field(
        None, description="Run status (PENDING, RUNNING, PAUSED, COMPLETED, CANCELLED, ERROR, REGENERATED)"
    )
    run_input: Optional[str] = Field(None, description="Input preview, truncated")
    content_preview: Optional[str] = Field(None, description="Output content preview, truncated")
    created_at: Optional[datetime] = Field(None, description="Run creation timestamp")

    @classmethod
    def _preview(cls, value: Any) -> Optional[str]:
        if value is None:
            return None
        # Structured output (output_schema) previews as JSON, matching the full listing's content.
        text = value if isinstance(value, str) else json.dumps(value, default=str)
        return text[:_RUN_PREVIEW_CHARS]

    @classmethod
    def from_run(cls, run: Any) -> "SessionRunPreviewSchema":
        return cls(
            run_id=run.run_id,
            run_index=getattr(run, "run_index", None),
            parent_run_id=getattr(run, "parent_run_id", None),
            agent_id=getattr(run, "agent_id", None),
            team_id=getattr(run, "team_id", None),
            workflow_id=getattr(run, "workflow_id", None),
            user_id=getattr(run, "user_id", None),
            status=getattr(run, "status", None),
            run_input=cls._preview(getattr(run, "run_input", None)),
            content_preview=cls._preview(getattr(run, "content", None)),
            created_at=getattr(run, "created_at", None),
        )


class TeamRunSchema(BaseModel):
    run_id: str = Field(..., description="Unique identifier for the team run")
    run_index: Optional[int] = Field(None, description="0-based position of the run in its session")
    parent_run_id: Optional[str] = Field(None, description="Parent run ID if this is a nested run")
    team_id: Optional[str] = Field(None, description="Team ID that executed this run")
    user_id: Optional[str] = Field(None, description="User ID associated with the run")
    status: Optional[str] = Field(None, description="Run status (PENDING, RUNNING, COMPLETED, ERROR, etc.)")
    cancellation_stage: Optional[str] = Field(None, description=CANCELLATION_STAGE_DESCRIPTION)
    content: Optional[Union[str, dict]] = Field(None, description="Output content from the team run")
    reasoning_content: Optional[str] = Field(None, description="Reasoning content if reasoning was enabled")
    reasoning_steps: Optional[List[dict]] = Field(None, description="List of reasoning steps")
    run_input: Optional[str] = Field(None, description="Input provided to the run")
    run_response_format: Optional[str] = Field(None, description="Format of the response (text/json)")
    metrics: Optional[dict] = Field(None, description="Performance and usage metrics")
    tools: Optional[List[dict]] = Field(None, description="Tools used in the run")
    messages: Optional[List[dict]] = Field(None, description="Message history for the run")
    events: Optional[List[dict]] = Field(None, description="Events generated during the run")
    created_at: Optional[datetime] = Field(None, description="Run creation timestamp")
    references: Optional[List[dict]] = Field(None, description="References cited in the run")
    citations: Optional[Dict[str, Any]] = Field(
        None, description="Citations from the model (e.g., from Gemini grounding/search)"
    )
    reasoning_messages: Optional[List[dict]] = Field(None, description="Reasoning process messages")
    session_state: Optional[dict] = Field(None, description="Session state at the end of the run")
    input_media: Optional[Dict[str, Any]] = Field(None, description="Input media attachments")
    images: Optional[List[dict]] = Field(None, description="Images included in the run")
    videos: Optional[List[dict]] = Field(None, description="Videos included in the run")
    audio: Optional[List[dict]] = Field(None, description="Audio files included in the run")
    files: Optional[List[dict]] = Field(None, description="Files included in the run")
    response_audio: Optional[dict] = Field(None, description="Audio response if generated")
    followups: Optional[List[str]] = Field(None, description="Followup suggestions generated after the run")
    # set when the team run was created via /continue (fork /
    # regenerate / time-travel) or via /sessions/{id}/branch. Client consumes
    # these to render parent → child relationships in the run timeline.
    forked_from_run_id: Optional[str] = Field(
        None, description="If this team run was forked from another run, the source run's ID"
    )
    forked_from_message_index: Optional[int] = Field(
        None,
        description="If this team run was forked, the message index at which the source was truncated; for a run copied by a session branch and continued, the index where the continued work starts",
    )
    forked_from_session_id: Optional[str] = Field(
        None,
        description="If this team run was created via session branch, the source session's ID; cleared once the copied run is continued in this session",
    )
    regenerated_from: Optional[str] = Field(
        None, description="If this team run was produced via regenerate=true, the source run's ID"
    )
    last_checkpoint_at_message_index: Optional[int] = Field(
        None, description="Message index of the most recent mid-run checkpoint (checkpoint='tool-batch' runs)"
    )

    @classmethod
    def from_dict(cls, run_dict: Dict[str, Any]) -> "TeamRunSchema":
        run_input = get_run_input(run_dict)
        run_response_format = "text" if run_dict.get("content_type", "str") == "str" else "json"
        return cls(
            run_id=run_dict.get("run_id", ""),
            parent_run_id=run_dict.get("parent_run_id", ""),
            team_id=run_dict.get("team_id", ""),
            user_id=run_dict.get("user_id"),
            status=run_dict.get("status"),
            cancellation_stage=run_dict.get("cancellation_stage"),
            run_input=run_input,
            content=run_dict.get("content", ""),
            run_response_format=run_response_format,
            reasoning_content=run_dict.get("reasoning_content", ""),
            reasoning_steps=run_dict.get("reasoning_steps", []),
            metrics=run_dict.get("metrics", {}),
            messages=[message for message in run_dict.get("messages", [])] if run_dict.get("messages") else None,
            tools=[tool for tool in run_dict.get("tools", [])] if run_dict.get("tools") else None,
            events=[event for event in run_dict["events"]] if run_dict.get("events") else None,
            created_at=to_utc_datetime(run_dict.get("created_at")),
            references=run_dict.get("references", []),
            citations=run_dict.get("citations", None),
            reasoning_messages=run_dict.get("reasoning_messages", []),
            session_state=run_dict.get("session_state"),
            images=run_dict.get("images", []),
            videos=run_dict.get("videos", []),
            audio=run_dict.get("audio", []),
            files=run_dict.get("files", []),
            response_audio=run_dict.get("response_audio", None),
            input_media=extract_input_media(run_dict),
            followups=run_dict.get("followups", None),
            forked_from_run_id=run_dict.get("forked_from_run_id"),
            forked_from_message_index=run_dict.get("forked_from_message_index"),
            forked_from_session_id=run_dict.get("forked_from_session_id"),
            regenerated_from=run_dict.get("regenerated_from"),
            last_checkpoint_at_message_index=run_dict.get("last_checkpoint_at_message_index"),
        )


class WorkflowRunSchema(BaseModel):
    run_id: str = Field(..., description="Unique identifier for the workflow run")
    run_index: Optional[int] = Field(None, description="0-based position of the run in its session")
    run_input: Optional[str] = Field(None, description="Input provided to the workflow")
    events: Optional[List[dict]] = Field(None, description="Events generated during the workflow")
    workflow_id: Optional[str] = Field(None, description="Workflow ID that was executed")
    user_id: Optional[str] = Field(None, description="User ID associated with the run")
    content: Optional[Union[str, dict]] = Field(None, description="Output content from the workflow")
    content_type: Optional[str] = Field(None, description="Type of content returned")
    status: Optional[str] = Field(None, description="Status of the workflow run")
    cancellation_stage: Optional[str] = Field(None, description=CANCELLATION_STAGE_DESCRIPTION)
    step_results: Optional[list[dict]] = Field(None, description="Results from each workflow step")
    step_executor_runs: Optional[list[dict]] = Field(None, description="Executor runs for each step")
    step_requirements: Optional[list[dict]] = Field(
        None, description="HITL step requirements (resolved state for historical display)"
    )
    pause_kind: Optional[str] = Field(None, description="Kind of HITL pause: 'step' or 'executor'")
    paused_step_name: Optional[str] = Field(None, description="Name of the step that caused the pause")
    paused_step_index: Optional[int] = Field(None, description="Index of the step that caused the pause")
    metrics: Optional[dict] = Field(None, description="Performance and usage metrics")
    created_at: Optional[datetime] = Field(None, description="Run creation timestamp")
    reasoning_content: Optional[str] = Field(None, description="Reasoning content if reasoning was enabled")
    reasoning_steps: Optional[List[dict]] = Field(None, description="List of reasoning steps")
    references: Optional[List[dict]] = Field(None, description="References cited in the workflow")
    citations: Optional[Dict[str, Any]] = Field(
        None, description="Citations from the model (e.g., from Gemini grounding/search)"
    )
    reasoning_messages: Optional[List[dict]] = Field(None, description="Reasoning process messages")
    images: Optional[List[dict]] = Field(None, description="Images included in the workflow")
    videos: Optional[List[dict]] = Field(None, description="Videos included in the workflow")
    audio: Optional[List[dict]] = Field(None, description="Audio files included in the workflow")
    files: Optional[List[dict]] = Field(None, description="Files included in the workflow")
    response_audio: Optional[dict] = Field(None, description="Audio response if generated")

    @classmethod
    def from_dict(cls, run_response: Dict[str, Any]) -> "WorkflowRunSchema":
        run_input = get_run_input(run_response, is_workflow_run=True)
        return cls(
            run_id=run_response.get("run_id", ""),
            run_input=run_input,
            events=run_response.get("events", []),
            workflow_id=run_response.get("workflow_id", ""),
            user_id=run_response.get("user_id", ""),
            content=run_response.get("content", ""),
            content_type=run_response.get("content_type", ""),
            status=run_response.get("status", ""),
            cancellation_stage=run_response.get("cancellation_stage"),
            metrics=run_response.get("metrics", {}),
            step_results=run_response.get("step_results", []),
            step_executor_runs=run_response.get("step_executor_runs", []),
            step_requirements=run_response.get("step_requirements"),
            pause_kind=run_response.get("pause_kind"),
            paused_step_name=run_response.get("paused_step_name"),
            paused_step_index=run_response.get("paused_step_index"),
            created_at=to_utc_datetime(run_response.get("created_at")),
            reasoning_content=run_response.get("reasoning_content", ""),
            reasoning_steps=run_response.get("reasoning_steps", []),
            references=run_response.get("references", []),
            citations=run_response.get("citations", None),
            reasoning_messages=run_response.get("reasoning_messages", []),
            images=run_response.get("images", []),
            videos=run_response.get("videos", []),
            audio=run_response.get("audio", []),
            files=run_response.get("files", []),
            response_audio=run_response.get("response_audio", None),
        )


T = TypeVar("T")


class SortOrder(str, Enum):
    ASC = "asc"
    DESC = "desc"


class PaginationInfo(BaseModel):
    page: int = Field(0, description="Current page number (1-indexed)", ge=0)
    limit: int = Field(20, description="Number of items per page", ge=1)
    total_pages: int = Field(0, description="Total number of pages", ge=0)
    total_count: int = Field(0, description="Total count of items", ge=0)
    search_time_ms: float = Field(0, description="Search execution time in milliseconds", ge=0)


class PaginatedResponse(BaseModel, Generic[T]):
    """Wrapper to add pagination info to classes used as response models"""

    data: List[T] = Field(..., description="List of items for the current page")
    meta: PaginationInfo = Field(..., description="Pagination metadata")


class RunsPageInfo(BaseModel):
    limit: int = Field(..., description="Maximum number of items in this page", ge=1)
    total_count: int = Field(..., description="Total count of items matching the filters", ge=0)
    has_more: bool = Field(..., description="Whether more items exist beyond this page in the paging direction")
    oldest_run_index: Optional[int] = Field(
        None, description="Oldest top-level run_index on this page; pass it as before_run_index for the older page"
    )
    newest_run_index: Optional[int] = Field(
        None, description="Newest top-level run_index on this page; pass it as after_run_index for the newer page"
    )


class RunsPage(BaseModel, Generic[T]):
    """Wrapper for cursor-paginated responses; callers page with a boundary taken from ``data``."""

    data: List[T] = Field(..., description="List of items for the current page")
    meta: RunsPageInfo = Field(..., description="Pagination metadata")


class ComponentType(str, Enum):
    AGENT = "agent"
    TEAM = "team"
    WORKFLOW = "workflow"


class ComponentGuard(BaseModel):
    """Optional compare-and-set guard for component writes.

    When present, each non-None field is checked against the stored state and
    the write is rejected with 409 on mismatch. None fields skip that half of
    the check; omitting the guard keeps the write last-writer-wins.
    """

    latest_version: Optional[int] = Field(None, description="Expected latest config version")
    current_version: Optional[int] = Field(
        None, description="Expected current (published) version; 0 expects the component to have none yet"
    )

    @field_validator("latest_version", "current_version", mode="before")
    @classmethod
    def _reject_boolean_versions(cls, value: Any) -> Any:
        # Lax coercion would read JSON false as 0, and 0 now means "no live
        # version": a boolean is not a version number, so it is refused rather
        # than silently satisfying (or failing) the guard.
        if isinstance(value, bool):
            raise ValueError("version guards must be integers, not booleans")
        return value


class ComponentCreate(BaseModel):
    name: str = Field(..., description="Display name")
    component_id: Optional[str] = Field(
        None, description="Unique identifier for the entity. Auto-generated from name if not provided."
    )
    component_type: ComponentType = Field(..., description="Type of entity: agent, team, or workflow")
    description: Optional[str] = Field(None, description="Optional description")
    metadata: Optional[Dict[str, Any]] = Field(None, description="Optional metadata")
    # Config parameters are optional, but if provided, they will be used to create the initial config
    config: Optional[Dict[str, Any]] = Field(None, description="Optional configuration")
    label: Optional[str] = Field(None, description="Optional label (e.g., 'stable')")
    stage: str = Field("draft", description="Stage: 'draft' or 'published'")
    notes: Optional[str] = Field(None, description="Optional notes")
    set_current: bool = Field(True, description="Set as current version")


class ComponentResponse(BaseModel):
    component_id: str
    component_type: ComponentType
    name: Optional[str] = None
    user_id: Optional[str] = None
    description: Optional[str] = None
    current_version: Optional[int] = None
    metadata: Optional[Dict[str, Any]] = None
    created_at: int
    updated_at: Optional[int] = None
    # Set only on archived (soft-deleted) rows, so a mixed list can label them.
    deleted_at: Optional[int] = None


class ConfigCreate(BaseModel):
    config: Dict[str, Any] = Field(..., description="The configuration data")
    version: Optional[int] = Field(None, description="Optional version number")
    label: Optional[str] = Field(None, description="Optional label (e.g., 'stable')")
    stage: str = Field("draft", description="Stage: 'draft' or 'published'")
    notes: Optional[str] = Field(None, description="Optional notes")
    links: Optional[List[Dict[str, Any]]] = Field(None, description="Optional links to child components")
    set_current: bool = Field(True, description="Set as current version")
    guard: Optional[ComponentGuard] = Field(None, description="Optional compare-and-set guard")


class ComponentConfigResponse(BaseModel):
    component_id: str
    version: int
    label: Optional[str] = None
    stage: str
    config: Dict[str, Any]
    notes: Optional[str] = None
    created_at: int
    updated_at: Optional[int] = None


class ComponentUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    component_type: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None
    current_version: Optional[int] = None
    guard: Optional[ComponentGuard] = None


class ConfigUpdate(BaseModel):
    config: Optional[Dict[str, Any]] = None
    label: Optional[str] = None
    stage: Optional[str] = None
    notes: Optional[str] = None
    links: Optional[List[Dict[str, Any]]] = None
    guard: Optional[ComponentGuard] = None


class SetCurrentRequest(BaseModel):
    """Body for set-current. Optional: an empty POST keeps working."""

    guard: Optional[ComponentGuard] = Field(None, description="Optional compare-and-set guard")


class ComponentDeleteRequest(BaseModel):
    """Body for delete. Optional: a bodyless DELETE keeps working.

    Delete also accepts the guard as an ``expected_current_version`` query
    param; this shape exists so the guard reads the same as on every other
    guarded component route instead of being silently ignored here.
    """

    guard: Optional[ComponentGuard] = Field(None, description="Optional compare-and-set guard")


class RegistryResourceType(str, Enum):
    """Types of resources that can be stored in a registry."""

    TOOL = "tool"
    MODEL = "model"
    DB = "db"
    VECTOR_DB = "vector_db"
    SCHEMA = "schema"
    FUNCTION = "function"
    AGENT = "agent"
    TEAM = "team"
    WORKFLOW = "workflow"
    KNOWLEDGE = "knowledge"
    MEMORY_MANAGER = "memory_manager"
    SESSION_SUMMARY_MANAGER = "session_summary_manager"
    LEARNING = "learning"
    SANDBOX = "sandbox"


class CallableMetadata(BaseModel):
    """Common metadata for callable components (tools, functions)."""

    name: str = Field(..., description="Callable name")
    description: Optional[str] = Field(None, description="Callable description")
    class_path: str = Field(..., description="Full module path to the class/function")
    module: Optional[str] = Field(None, description="Module where the callable is defined")
    qualname: Optional[str] = Field(None, description="Qualified name of the callable")
    has_entrypoint: bool = Field(..., description="Whether the callable has an executable entrypoint")
    parameters: Dict[str, Any] = Field(default_factory=dict, description="JSON schema of parameters")
    requires_confirmation: Optional[bool] = Field(None, description="Whether execution requires user confirmation")
    external_execution: Optional[bool] = Field(None, description="Whether execution happens externally")
    signature: Optional[str] = Field(None, description="Function signature string")
    return_annotation: Optional[str] = Field(None, description="Return type annotation")


class ToolMetadata(BaseModel):
    """Metadata for tool registry components."""

    class_path: str = Field(..., description="Full module path to the tool class")
    is_toolkit: bool = Field(False, description="Whether this is a toolkit containing multiple functions")
    functions: Optional[List[CallableMetadata]] = Field(
        None, description="Functions in the toolkit (if is_toolkit=True)"
    )

    # Fields for non-toolkit tools (Function or raw callable)
    module: Optional[str] = Field(None, description="Module where the callable is defined")
    qualname: Optional[str] = Field(None, description="Qualified name of the callable")
    has_entrypoint: Optional[bool] = Field(None, description="Whether the tool has an executable entrypoint")
    parameters: Optional[Dict[str, Any]] = Field(None, description="JSON schema of parameters")
    requires_confirmation: Optional[bool] = Field(None, description="Whether execution requires user confirmation")
    external_execution: Optional[bool] = Field(None, description="Whether execution happens externally")
    signature: Optional[str] = Field(None, description="Function signature string")
    return_annotation: Optional[str] = Field(None, description="Return type annotation")


class ModelMetadata(BaseModel):
    """Metadata for model registry components."""

    class_path: str = Field(..., description="Full module path to the model class")
    provider: Optional[str] = Field(None, description="Model provider (e.g., openai, anthropic)")
    model_id: Optional[str] = Field(None, description="Model identifier")


class DbMetadata(BaseModel):
    """Metadata for database registry components."""

    class_path: str = Field(..., description="Full module path to the database class")
    db_id: Optional[str] = Field(None, description="Database identifier")


class VectorDbMetadata(BaseModel):
    """Metadata for vector database registry components."""

    class_path: str = Field(..., description="Full module path to the vector database class")
    vector_db_id: Optional[str] = Field(None, description="Vector database identifier")
    collection: Optional[str] = Field(None, description="Collection name")
    table_name: Optional[str] = Field(None, description="Table name (for SQL-based vector stores)")


class SchemaMetadata(BaseModel):
    """Metadata for schema registry components."""

    class_path: str = Field(..., description="Full module path to the schema class")
    schema_: Optional[Dict[str, Any]] = Field(None, alias="schema", description="JSON schema definition")
    schema_error: Optional[str] = Field(None, description="Error message if schema generation failed")


class FunctionMetadata(CallableMetadata):
    """Metadata for function registry components (workflow conditions, selectors, etc.)."""

    pass


class KnowledgeMetadata(BaseModel):
    """Metadata for knowledge registry components."""

    class_path: str = Field(..., description="Full module path to the knowledge class")
    vector_db_class: Optional[str] = Field(None, description="Class of the vector database used")
    contents_db_class: Optional[str] = Field(None, description="Class of the contents database used")
    max_results: Optional[int] = Field(None, description="Maximum search results")
    num_readers: Optional[int] = Field(None, description="Number of configured readers")


class MemoryManagerMetadata(BaseModel):
    """Metadata for memory manager registry components."""

    class_path: str = Field(..., description="Full module path to the memory manager class")
    owner_id: Optional[str] = Field(None, description="Id of the agent or team that owns this manager")
    owner_type: Optional[str] = Field(None, description="Type of owner: 'agent' or 'team'")
    model_class: Optional[str] = Field(None, description="Class of the model used by the manager")
    model_id: Optional[str] = Field(None, description="Identifier of the model used by the manager")
    db_class: Optional[str] = Field(None, description="Class of the database used by the manager")
    add_memories: Optional[bool] = Field(None, description="Whether the manager can add memories")
    update_memories: Optional[bool] = Field(None, description="Whether the manager can update memories")
    delete_memories: Optional[bool] = Field(None, description="Whether the manager can delete memories")
    clear_memories: Optional[bool] = Field(None, description="Whether the manager can clear memories")


class SessionSummaryManagerMetadata(BaseModel):
    """Metadata for session summary manager registry components."""

    class_path: str = Field(..., description="Full module path to the session summary manager class")
    owner_id: Optional[str] = Field(None, description="Id of the agent or team that owns this manager")
    owner_type: Optional[str] = Field(None, description="Type of owner: 'agent' or 'team'")
    model_class: Optional[str] = Field(None, description="Class of the model used by the manager")
    model_id: Optional[str] = Field(None, description="Identifier of the model used by the manager")
    last_n_runs: Optional[int] = Field(None, description="Number of recent runs included in the summary")
    conversation_limit: Optional[int] = Field(None, description="Max number of messages in summary conversation")


# Union of all metadata types for type hints
RegistryMetadata = Union[
    ToolMetadata,
    ModelMetadata,
    DbMetadata,
    VectorDbMetadata,
    SchemaMetadata,
    FunctionMetadata,
    KnowledgeMetadata,
    MemoryManagerMetadata,
    SessionSummaryManagerMetadata,
]


class RegistryContentResponse(BaseModel):
    name: str
    type: RegistryResourceType
    id: Optional[str] = None
    description: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None
    sandboxed: bool = False
