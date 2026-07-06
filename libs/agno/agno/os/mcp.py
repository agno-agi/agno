"""Router for MCP interface providing Model Context Protocol endpoints."""

import functools
import inspect
import logging
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any, Callable, Dict, Iterator, List, Literal, Optional, Union
from uuid import uuid4

from fastmcp import Context, FastMCP
from fastmcp.server.http import (
    StarletteWithLifespan,
)
from fastmcp.tools import ToolResult

from agno.db.base import SessionType
from agno.os.mcp_results import build_run_tool_result, trim_session_run
from agno.os.schema import (
    AgentSummaryResponse,
    PaginatedResponse,
    PaginationInfo,
    SessionSchema,
    TeamSummaryResponse,
    WorkflowSummaryResponse,
)
from agno.os.services import runs as run_service
from agno.os.services import sessions as session_service
from agno.os.utils import (
    get_db,
    resolve_agent,
    resolve_team,
    resolve_workflow,
)
from agno.remote.base import BaseRemote, RemoteDb
from agno.run.agent import RunEvent, RunOutput
from agno.run.team import TeamRunEvent, TeamRunOutput
from agno.run.workflow import WorkflowRunEvent, WorkflowRunOutput

if TYPE_CHECKING:
    from agno.os.app import AgentOS
    from agno.os.config import MCPServerConfig

logger = logging.getLogger(__name__)

# Built-in MCP tools are tagged by domain so they can be scoped as a group. The canonical
# tag set lives in agno/os/config.py next to the MCPServerConfig fields that consume it --
# single source of truth so adding a new tag is a one-place change.
from agno.os.config import MCP_BUILTIN_TAGS as _BUILTIN_TOOL_TAGS  # noqa: E402


def _enabled_builtin_tags(config: "Optional[MCPServerConfig]") -> set:
    """Resolve which built-in tool tags should be registered, given the MCP config.

    Returns the full set of built-in tags when no config is provided, preserving the
    default behavior (all built-in tools registered).
    """
    if config is None:
        return set(_BUILTIN_TOOL_TAGS)
    if not config.enable_builtin_tools:
        return set()
    # An explicitly empty include_tags set means "no built-in tools", so test against
    # None rather than truthiness.
    enabled = set(config.include_tags) if config.include_tags is not None else set(_BUILTIN_TOOL_TAGS)
    if config.exclude_tags:
        enabled -= set(config.exclude_tags)
    return enabled


def _builtin_tool_registrar(mcp: FastMCP, config: "Optional[MCPServerConfig]"):
    """Return a drop-in replacement for ``mcp.tool`` that scopes the built-in tools.

    When a tool's tags are enabled by the config, the tool is registered as usual.
    Otherwise the decorator is a no-op (the function is returned unregistered), so
    scoping happens at registration time without depending on FastMCP tool-removal APIs.
    """
    enabled_tags = _enabled_builtin_tags(config)

    def register(*args: Any, **kwargs: Any):
        tags = kwargs.get("tags") or set()
        if tags & enabled_tags:
            return mcp.tool(*args, **kwargs)

        def _skip(fn: Any) -> Any:
            return fn

        return _skip

    return register


def _register_custom_tools(mcp: FastMCP, config: "Optional[MCPServerConfig]") -> None:
    """Register any user-provided custom tools on the MCP server."""
    if config is None or not config.tools:
        return
    for tool in config.tools:
        _register_custom_tool(mcp, tool)


def _register_custom_tool(mcp: FastMCP, tool: Any) -> None:
    """Register a single custom tool, supporting plain callables and Agno tools/Functions."""
    from fastmcp.tools import Tool

    # Agno tool / Function: a callable ``entrypoint`` plus name/description metadata.
    entrypoint = getattr(tool, "entrypoint", None)
    if callable(entrypoint):
        name = getattr(tool, "name", None) or getattr(entrypoint, "__name__", None)
        description = getattr(tool, "description", None)
        mcp.add_tool(Tool.from_function(_inject_user_id(entrypoint), name=name, description=description))
        return

    # Plain callable: name/description inferred from ``__name__``/docstring.
    if callable(tool):
        mcp.add_tool(Tool.from_function(_inject_user_id(tool)))
        return

    raise TypeError(
        f"Cannot register MCP tool of type {type(tool).__name__!r}; expected a callable or an Agno tool/Function."
    )


def _inject_user_id(fn: Callable) -> Callable:
    """Inject the authenticated caller's user_id into a custom tool, hidden from clients.

    If ``fn`` declares a ``user_id`` parameter, return a wrapper that fills it with the
    resolved JWT subject at call time and drops it from the wrapper's signature -- so it
    does not appear in the MCP tool schema and cannot be supplied (or spoofed) by callers.
    Tools that do not declare ``user_id`` are returned unchanged.
    """
    try:
        sig = inspect.signature(fn)
    except (ValueError, TypeError):
        return fn
    if "user_id" not in sig.parameters:
        return fn

    visible_params = [p for name, p in sig.parameters.items() if name != "user_id"]
    new_sig = sig.replace(parameters=visible_params)

    if inspect.iscoroutinefunction(fn):

        @functools.wraps(fn)
        async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
            kwargs["user_id"] = _resolve_user_id(None)
            return await fn(*args, **kwargs)

        async_wrapper.__signature__ = new_sig  # type: ignore[attr-defined]
        return async_wrapper

    @functools.wraps(fn)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        kwargs["user_id"] = _resolve_user_id(None)
        return fn(*args, **kwargs)

    wrapper.__signature__ = new_sig  # type: ignore[attr-defined]
    return wrapper


def _resolve_user_id(caller_user_id: Optional[str]) -> Optional[str]:
    """Bind user_id to the JWT subject when an authenticated request is in flight."""
    from fastmcp.server.dependencies import get_http_request

    try:
        request = get_http_request()
    except RuntimeError:
        return caller_user_id

    state_user_id = getattr(getattr(request, "state", None), "user_id", None)
    if state_user_id is not None:
        return state_user_id
    return caller_user_id


def _forwarded_auth_headers() -> Optional[Dict[str, str]]:
    """The caller's bearer token as an Authorization header for downstream RemoteDb calls.

    Mirrors the REST routers, which forward the inbound token on every RemoteDb call so
    a JWT/PAT-protected downstream AgentOS accepts the request.
    """
    from fastmcp.server.dependencies import get_http_request

    from agno.os.auth import get_auth_token_from_request

    try:
        request = get_http_request()
    except RuntimeError:
        return None
    token = get_auth_token_from_request(request)
    return {"Authorization": f"Bearer {token}"} if token else None


def _scoped_caller_user_id() -> Optional[str]:
    """The caller's user_id when they are a non-admin, isolation-scoped principal, else None.

    Reuses the REST scoping rule (:func:`get_scoped_user_id`): admins and
    non-isolated deployments return None (no per-run ownership gate), while a
    scoped user returns their id so run-lifecycle tools can enforce ownership.
    """
    from fastmcp.server.dependencies import get_http_request

    from agno.os.middleware.user_scope import get_scoped_user_id

    try:
        request = get_http_request()
    except RuntimeError:
        return None
    return get_scoped_user_id(request)


def _scoped_read_user_id(caller_user_id: Optional[str]) -> Optional[str]:
    """The user_id a session-read tool should filter by.

    Mirrors the REST session routes (``resolve_db_and_scope(fallback_user_id=user_id)``): a
    scoped, non-admin caller under user isolation is pinned to their own id, while admins and
    non-isolation deployments honour the client-supplied ``user_id``. This differs from
    :func:`_resolve_user_id` (used by the run tools for attribution), which always forces the
    authenticated id -- so an admin can still read another user's sessions over MCP, as on REST.
    """
    scoped = _scoped_caller_user_id()
    return scoped if scoped is not None else caller_user_id


@functools.lru_cache(maxsize=1)
def _tool_scope_mappings() -> Dict[str, List[str]]:
    """The default route→scope mappings, built once (they are static data)."""
    from agno.os.scopes import get_default_scope_mappings

    return get_default_scope_mappings()


def _require_tool_scopes(method: str, path: str) -> None:
    """Enforce the caller's scopes against the REST route this tool call is equivalent to.

    The MCP tools are an alternate transport for the REST surface, so authorization
    reuses the REST mechanism verbatim: map the tool call onto its REST route and run
    ``check_route_scopes`` with the same mappings (per-resource scopes and the admin
    bypass behave identically). Service-account scopes are ACL data enforced in every
    deployment mode, mirroring ``agno.os.auth._authenticate_service_account``; JWT
    scopes are enforced when authorization is enabled. Anonymous callers (open or
    security-key deployments) carry no scopes and pass.

    Custom ``scope_mappings`` passed to a manually-installed JWTMiddleware apply to the
    literal request path (``/mcp``), not to these synthetic routes -- the tool gate
    always enforces the default mappings.
    """
    from fastmcp.server.dependencies import get_http_request

    from agno.os.auth import build_insufficient_permissions_detail
    from agno.os.scopes import check_route_scopes

    try:
        request = get_http_request()
    except RuntimeError:
        return

    state = request.state
    is_service_account = getattr(state, "service_account_name", None) is not None
    if not is_service_account and not getattr(state, "authorization_enabled", False):
        return

    admin_scope_raw = getattr(state, "admin_scope", None)
    admin_scope = admin_scope_raw if isinstance(admin_scope_raw, str) else None
    scope_check = check_route_scopes(
        list(getattr(state, "scopes", None) or []),
        _tool_scope_mappings(),
        method,
        path,
        admin_scope=admin_scope,
    )
    if not scope_check.allowed:
        raise Exception(build_insufficient_permissions_detail(scope_check.required_scopes))


async def _enforce_run_continuation_allowed(db: Any, run_id: str) -> None:
    """Block continuing a run that is awaiting admin approval.

    The REST ``/continue`` routes gate this with ``require_approval_resolved``; the MCP
    ``continue_run`` tool must apply the same gate or a run's initiator could self-approve
    an admin-required pause by continuing over MCP instead of REST. Both share
    ``run_continuation_blocked_reason`` so the policy cannot drift.
    """
    from fastmcp.server.dependencies import get_http_request

    from agno.os.auth import run_continuation_blocked_reason

    try:
        request = get_http_request()
    except RuntimeError:
        # No HTTP request in scope (e.g. stdio transport): request.state auth context is
        # unavailable, so there is nothing to enforce here.
        return

    state = request.state
    reason = await run_continuation_blocked_reason(
        db,
        run_id,
        authorization_enabled=bool(getattr(state, "authorization_enabled", False)),
        user_scopes=list(getattr(state, "scopes", None) or []),
    )
    if reason:
        raise Exception(reason)


# Events forwarded to the client as progress notifications during agent/team runs.
# Content deltas are deliberately excluded: MCP progress is a status channel, and
# per-token notifications would flood clients that request a progress token.
_TOOL_CALL_PROGRESS_EVENTS = frozenset(
    {
        RunEvent.tool_call_started.value,
        RunEvent.tool_call_completed.value,
        TeamRunEvent.tool_call_started.value,
        TeamRunEvent.tool_call_completed.value,
    }
)

# Error events captured so a failed run surfaces its real error message. The streaming
# error paths yield only these events -- the final run output is never yielded on failure.
_RUN_ERROR_EVENTS = frozenset({RunEvent.run_error.value, TeamRunEvent.run_error.value})


async def _report_progress(ctx: Context, progress: float, message: str, total: Optional[float] = None) -> None:
    """Send a progress notification; a failure here must never break the run.

    FastMCP no-ops when the client did not send a progressToken, so this is safe to
    call unconditionally.
    """
    try:
        await ctx.report_progress(progress=progress, total=total, message=message)
    except Exception:
        logger.debug("Failed to send MCP progress notification", exc_info=True)


def _describe_tool_call_event(event: Any) -> str:
    tool = getattr(event, "tool", None)
    tool_name = getattr(tool, "tool_name", None) or "tool"
    verb = "started" if str(getattr(event, "event", "")).endswith("Started") else "completed"
    return f"Tool call {verb}: {tool_name}"


async def _consume_agentic_stream(ctx: Context, stream: Any, label: str) -> Union[RunOutput, TeamRunOutput]:
    """Drive a streaming agent/team run and return its final output.

    The stream must be created with ``stream=True, stream_events=True,
    yield_run_output=True`` so tool-call events can be forwarded as progress
    notifications and the final ``RunOutput`` / ``TeamRunOutput`` arrives as the
    last yielded item. On failure the stream yields only a run-error event -- its
    message is captured so the client sees the real error, not a generic one.
    """
    final: Optional[Union[RunOutput, TeamRunOutput]] = None
    error_message: Optional[str] = None
    ticks = 0
    await _report_progress(ctx, 0.0, f"{label} started")
    async for item in stream:
        if isinstance(item, (RunOutput, TeamRunOutput)):
            final = item
            continue
        event = getattr(item, "event", None)
        if event in _TOOL_CALL_PROGRESS_EVENTS:
            ticks += 1
            await _report_progress(ctx, float(ticks), _describe_tool_call_event(item))
        elif event in _RUN_ERROR_EVENTS:
            error_message = getattr(item, "content", None) or "Run failed"
    if final is None:
        raise Exception(
            str(error_message) if error_message else f"{label} finished without producing a final run output"
        )
    return final


@contextmanager
def _detached_trace_context() -> Iterator[None]:
    """Run a component in a fresh OTel root trace, detached from FastMCP's tool-call span.

    FastMCP wraps every tool call in an identity-less ``tools/call ...`` SERVER span. Left
    attached, the agno run span nests under it, and the trace layer -- which reads a trace's
    identity (run_id / session_id / user_id / agent_id) from its root span -- takes it from
    that context-less protocol span instead of the run, so runs invoked over MCP land with a
    NULL, mislabeled trace. Detaching to an invalid parent makes the run span its own root,
    so the run is attributed exactly like the REST run routes (which have no wrapping span).

    No-op when OpenTelemetry is not installed.
    """
    try:
        from opentelemetry import context as otel_context  # type: ignore
        from opentelemetry import trace as otel_trace  # type: ignore
    except ImportError:
        yield
        return

    token = otel_context.attach(otel_trace.set_span_in_context(otel_trace.INVALID_SPAN))
    try:
        yield
    finally:
        otel_context.detach(token)


async def _run_agentic_component(
    ctx: Context, component: Any, message: str, user_id: Optional[str], session_id: Optional[str], label: str
) -> Union[RunOutput, TeamRunOutput]:
    """Shared run path for agents and teams: stream with progress for native components,
    plain await for everything else.

    Only native ``Agent`` / ``Team`` instances take the streaming path: remotes proxy to
    another AgentOS over HTTP and ``AgentProtocol`` implementations follow the protocol's
    streaming contract -- in both cases the streaming ``arun`` never yields the final
    output object, so they run non-streaming (no intermediate progress, same result
    contract).
    """
    from agno.agent.agent import Agent
    from agno.team.team import Team

    with _detached_trace_context():
        if not isinstance(component, (Agent, Team)):
            return await component.arun(message, user_id=user_id, session_id=session_id)

        stream = component.arun(
            message,
            user_id=user_id,
            session_id=session_id,
            stream=True,
            stream_events=True,
            yield_run_output=True,
        )
        return await _consume_agentic_stream(ctx, stream, label=label)


def _describe_step_event(event: Any, total_steps: Optional[float]) -> str:
    verb = "started" if str(getattr(event, "event", "")).endswith("Started") else "completed"
    step_name = getattr(event, "step_name", None) or "step"
    step_index = getattr(event, "step_index", None)
    if isinstance(step_index, tuple) and step_index and isinstance(step_index[0], int):
        step_index = step_index[0]
    if isinstance(step_index, int) and total_steps:
        return f"Step {verb}: {step_name} ({step_index + 1}/{int(total_steps)})"
    return f"Step {verb}: {step_name}"


async def _consume_workflow_stream(
    ctx: Context,
    workflow: Any,
    stream: Any,
    total_steps: Optional[float],
    user_id: Optional[str],
) -> WorkflowRunOutput:
    """Drive a streaming workflow run and return its final output.

    Workflow streams do not support ``yield_run_output``. Completed runs carry the
    full ``WorkflowRunOutput`` on the terminal event; paused / cancelled / step-error
    runs end the stream with NO workflow-level terminal event, so the persisted run
    is fetched back via ``workflow.aget_run_output`` -- the same source of truth the
    REST router uses. Events from nested workflows (``nested_depth > 0``) are skipped:
    terminal handling and progress apply to the outer run only, and a nested failure
    the outer workflow recovers from must not abort it.

    Progress values are a plain monotonic counter (the MCP spec requires each
    notification's progress to increase); the step k/n detail lives in the message.
    """
    from agno.run.workflow import BaseWorkflowRunOutputEvent

    final: Optional[WorkflowRunOutput] = None
    error_message: Optional[str] = None
    run_id: Optional[str] = None
    session_id: Optional[str] = None
    ticks = 0.0
    await _report_progress(ctx, 0.0, "Workflow started")
    async for item in stream:
        if isinstance(item, WorkflowRunOutput):
            final = item
            continue
        if getattr(item, "nested_depth", 0):
            continue
        if isinstance(item, BaseWorkflowRunOutputEvent):
            run_id = getattr(item, "run_id", None) or run_id
            session_id = getattr(item, "session_id", None) or session_id
        event = getattr(item, "event", None)
        if event in (WorkflowRunEvent.step_started.value, WorkflowRunEvent.step_completed.value):
            ticks += 1.0
            await _report_progress(ctx, ticks, _describe_step_event(item, total_steps))
        elif event == WorkflowRunEvent.workflow_completed.value:
            final = getattr(item, "run_output", None) or final
        elif event == WorkflowRunEvent.workflow_error.value:
            # Do not raise mid-stream: closing the generator here would skip the
            # workflow's own error-status persistence. Capture and settle after.
            error_message = getattr(item, "error", None) or "Workflow run failed"
    if final is None and run_id is not None:
        try:
            final = await workflow.aget_run_output(run_id=run_id, session_id=session_id, user_id=user_id)
        except Exception:
            logger.debug("Could not fetch persisted workflow run %s after stream end", run_id, exc_info=True)
    if final is None:
        raise Exception(
            str(error_message) if error_message else "Workflow run finished without producing a final run output"
        )
    return final


def _http_request_or_none() -> Optional[Any]:
    """The in-flight Starlette request, or None when there is none (e.g. stdio transport)."""
    from fastmcp.server.dependencies import get_http_request

    try:
        return get_http_request()
    except RuntimeError:
        return None


def _session_id_or_new(session_id: Optional[str]) -> str:
    """Return the caller's session_id, or mint a fresh one when it is omitted.

    The run tools must not forward ``session_id=None`` to ``arun``: a component that is
    reused across calls -- a shared ``AgentProtocol``/``RemoteAgent``/``RemoteTeam``, a
    remote workflow, or any instance not deep-copied per call -- would fall back to the
    sticky per-instance session that ``initialize_session`` caches on it, collapsing every
    "sessionless" run into one ever-growing conversation and leaking history between
    unrelated requests. The REST run routes mint a uuid per run for exactly this reason
    (see ``routers/agents/router.py``); the MCP run tools do the same so the documented
    contract -- "omit session_id to start a new one" -- holds regardless of how the
    component was resolved. An explicit session_id is always honoured, so continuing a
    conversation still works.
    """
    if session_id is None or session_id == "":
        return str(uuid4())
    return session_id


def _classify_lifecycle_target(
    agent_id: Optional[str], team_id: Optional[str], workflow_id: Optional[str]
) -> "tuple[Literal['agents', 'teams', 'workflows'], str]":
    """Map the exactly-one component id to its (type, id), without resolving it.

    Kept separate from resolution so the scope gate runs before we deep-copy or invoke a
    factory for the target.
    """
    provided = [
        (kind, cid) for kind, cid in (("agents", agent_id), ("teams", team_id), ("workflows", workflow_id)) if cid
    ]
    if len(provided) != 1:
        raise Exception("Provide exactly one of agent_id, team_id, or workflow_id")
    return provided[0]  # type: ignore[return-value]


async def _resolve_run_component(
    os: "AgentOS",
    kind: "Literal['agents', 'teams', 'workflows']",
    component_id: str,
    *,
    user_id: Optional[str],
    session_id: Optional[str],
) -> Any:
    """Resolve a component for a run/lifecycle tool exactly as the REST routes do.

    Delegates to the shared ``resolve_agent`` / ``resolve_team`` / ``resolve_workflow``
    helpers so the MCP surface matches REST on all three axes the low-level lookup
    otherwise dropped:

    - ``create_fresh=True`` (via the resolvers): each run gets a ``deep_copy()`` instead of
      the shared singleton, so concurrent MCP runs cannot contaminate each other's state.
    - ``db=os.db, registry=os.registry``: components registered in the DB registry (not the
      in-memory list) resolve and run, just like over REST.
    - factory ``RequestContext`` built from the in-flight HTTP request, so ``AgentFactory``
      entries resolve instead of raising.

    The resolvers raise ``HTTPException``; MCP tools surface plain exceptions, so map it.
    """
    from fastapi import HTTPException

    request = _http_request_or_none()
    try:
        if kind == "agents":
            return await resolve_agent(
                component_id, os.agents, os.db, os.registry, request=request, user_id=user_id, session_id=session_id
            )
        if kind == "teams":
            return await resolve_team(
                component_id,
                os.teams,
                db=os.db,
                registry=os.registry,
                request=request,
                user_id=user_id,
                session_id=session_id,
            )
        return await resolve_workflow(
            component_id,
            os.workflows,
            db=os.db,
            registry=os.registry,
            request=request,
            user_id=user_id,
            session_id=session_id,
        )
    except HTTPException as e:
        # Keep the id in the not-found message (the resolvers say only "Agent not found"),
        # matching the pre-v2.7 MCP error text and giving the client the id it passed.
        if e.status_code == 404:
            singular = {"agents": "Agent", "teams": "Team", "workflows": "Workflow"}[kind]
            raise Exception(f"{singular} {component_id} not found")
        raise Exception(e.detail if isinstance(e.detail, str) else str(e.detail))


def _make_run_ownership_verifier(os: "AgentOS"):
    """Bind the run-lifecycle ownership verifier to an AgentOS.

    continue_run and cancel_run must, for a scoped (non-admin) caller, prove the run lives
    in a session they own -- the same gate the REST cancel/continue endpoints enforce
    before touching a run.
    """

    async def verify(
        component: Any,
        component_type: Literal["agents", "teams", "workflows"],
        component_id: str,
        session_id: Optional[str],
        run_id: str,
    ):
        if component is None:
            raise Exception(f"Component {component_id} not found")
        scoped_user_id = _scoped_caller_user_id()
        if scoped_user_id is None:
            return
        if isinstance(component, BaseRemote):
            # Remote components keep their sessions on the remote OS: there is no local
            # session to prove ownership against (BaseRemote has no aget_session), and
            # the forwarded call would not carry this caller's identity for the remote
            # to check either. Fail closed rather than let a scoped caller act on
            # another user's run; admins (scoped_user_id None) pass through above.
            raise Exception(
                "Run ownership cannot be verified for remote components; an administrator can act on this run."
            )
        if not session_id:
            raise Exception("session_id is required to act on this run")
        try:
            await session_service.verify_run_ownership(
                component,
                session_id=session_id,
                run_id=run_id,
                user_id=scoped_user_id,
                component_type=component_type,
                component_id=component_id,
            )
        except session_service.RunOwnershipError as e:
            raise Exception(str(e))

    return verify


def build_mcp_server(
    os: "AgentOS",
) -> FastMCP:
    """Build the FastMCP server for an AgentOS.

    Registers the built-in tools (scoped by ``os.mcp_config``) and any custom tools.
    Split out from :func:`get_mcp_server` so the tool surface can be exercised directly
    by an in-memory MCP client in tests, without the HTTP/JWT layer.
    """
    mcp_config: "Optional[MCPServerConfig]" = getattr(os, "mcp_config", None)

    # Create an MCP server
    mcp = FastMCP(os.name or "AgentOS")

    # Decorator used to register the built-in tools. Honors ``mcp_config`` scoping;
    # behaves exactly like ``mcp.tool`` when no config (or default config) is provided.
    register_builtin_tool = _builtin_tool_registrar(mcp, mcp_config)

    # How the run tools serialize their results ("trimmed" keeps the frontend model's
    # context clean; "full" is the escape hatch for programmatic clients).
    result_mode = mcp_config.result_mode if mcp_config is not None else "trimmed"

    # Component resolution + ownership gate shared by continue_run and cancel_run.
    _verify_run_ownership = _make_run_ownership_verifier(os)

    @register_builtin_tool(
        name="get_agentos_config",
        description=(
            "Discover this AgentOS: the agents, teams, and workflows available to run (with their ids "
            "and descriptions), and the database ids used by the session tools. Call this first to learn "
            "what you can operate. The payload is deliberately compact -- the full configuration lives on "
            "the REST /config endpoint."
        ),
        tags={"core"},
        annotations={"readOnlyHint": True, "idempotentHint": True},
    )  # type: ignore
    async def config() -> Dict[str, Any]:
        _require_tool_scopes("GET", "/config")
        from agno.db.base import BaseDb

        request = _http_request_or_none()
        # Filter the roster to the caller's per-resource scopes, exactly as the REST list
        # routes do -- but only when authorization is enforced (open/dev instances and
        # unscoped tokens see everything). A caller scoped to one agent must not be able to
        # enumerate the whole deployment here when it cannot over GET /agents.
        authorization_enabled = bool(getattr(getattr(request, "state", None), "authorization_enabled", False))

        def _accessible(resources: Any, resource_type: str) -> List[Any]:
            items = list(resources or [])
            if authorization_enabled and request is not None and items:
                from agno.os.auth import filter_resources_by_access

                return filter_resources_by_access(request, items, resource_type)
            return items

        agents_out = [AgentSummaryResponse.from_agent(a).model_dump() for a in _accessible(os.agents, "agents")]
        teams_out = [TeamSummaryResponse.from_team(t).model_dump() for t in _accessible(os.teams, "teams")]
        workflows_out = [
            WorkflowSummaryResponse.from_workflow(w).model_dump() for w in _accessible(os.workflows, "workflows")
        ]

        # Surface components registered in the DB registry too, so anything created there is
        # discoverable -- and therefore runnable -- over MCP, matching the REST list routes.
        if os.db is not None and isinstance(os.db, BaseDb):
            from agno.agent.agent import get_agents
            from agno.team.team import get_teams
            from agno.workflow.workflow import get_workflows

            registry = os.registry
            agent_exclude = (registry.get_agent_ids() if registry else None) or None
            for a in _accessible(
                get_agents(db=os.db, registry=registry, exclude_component_ids=agent_exclude), "agents"
            ):
                try:
                    agents_out.append(AgentSummaryResponse.from_agent(a).model_dump())
                except Exception:
                    logger.exception("Error summarizing DB agent for get_agentos_config")
            team_exclude = (registry.get_team_ids() if registry else None) or None
            for t in _accessible(get_teams(db=os.db, registry=registry, exclude_component_ids=team_exclude), "teams"):
                try:
                    teams_out.append(TeamSummaryResponse.from_team(t).model_dump())
                except Exception:
                    logger.exception("Error summarizing DB team for get_agentos_config")
            for w in _accessible(get_workflows(db=os.db, registry=registry), "workflows"):
                try:
                    workflows_out.append(WorkflowSummaryResponse.from_workflow(w, is_component=True).model_dump())
                except Exception:
                    logger.exception("Error summarizing DB workflow for get_agentos_config")

        return {
            "os_id": os.id or "AgentOS",
            "description": os.description,
            # A db shared by several components is registered once per component in os.dbs,
            # so collect the ids into a set to list each database once -- matching the REST /config route.
            "databases": list({db.id for db_id, dbs in os.dbs.items() for db in dbs}),
            "agents": agents_out,
            "teams": teams_out,
            "workflows": workflows_out,
        }

    # ==================== Core Run Tools ====================

    @register_builtin_tool(
        name="run_agent",
        description=(
            "Run an agent with a message and get its response. Pass a session_id from get_sessions to "
            "continue that conversation; omit it to start a new one (the session_id comes back in "
            "structuredContent). If the result status is PAUSED, resolve the returned requirements and "
            "call continue_run. Agent ids come from get_agentos_config."
        ),
        tags={"core"},
        annotations={"readOnlyHint": False, "openWorldHint": True},
    )  # type: ignore
    async def run_agent(
        agent_id: str,
        message: str,
        ctx: Context,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> ToolResult:
        _require_tool_scopes("POST", f"/agents/{agent_id}/runs")
        user_id = _resolve_user_id(user_id)
        agent = await _resolve_run_component(os, "agents", agent_id, user_id=user_id, session_id=session_id)
        # Mint a fresh session per call when omitted (matches REST), never the sticky default.
        session_id = _session_id_or_new(session_id)
        run_output = await _run_agentic_component(
            ctx, agent, message, user_id, session_id, label=f"Agent {agent.name or agent_id}"
        )
        return build_run_tool_result(run_output, result_mode)

    @register_builtin_tool(
        name="run_team",
        description=(
            "Run a team of agents with a message and get its response. Same session and PAUSED semantics "
            "as run_agent. Team ids come from get_agentos_config."
        ),
        tags={"core"},
        annotations={"readOnlyHint": False, "openWorldHint": True},
    )  # type: ignore
    async def run_team(
        team_id: str,
        message: str,
        ctx: Context,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> ToolResult:
        _require_tool_scopes("POST", f"/teams/{team_id}/runs")
        user_id = _resolve_user_id(user_id)
        team = await _resolve_run_component(os, "teams", team_id, user_id=user_id, session_id=session_id)
        # Mint a fresh session per call when omitted (matches REST), never the sticky default.
        session_id = _session_id_or_new(session_id)
        run_output = await _run_agentic_component(
            ctx, team, message, user_id, session_id, label=f"Team {team.name or team_id}"
        )
        return build_run_tool_result(run_output, result_mode)

    @register_builtin_tool(
        name="run_workflow",
        description=(
            "Run a workflow with an input message and get its result. Can be long-running: progress is "
            "reported per step when the client supports it. Same session and PAUSED semantics as "
            "run_agent. Workflow ids come from get_agentos_config."
        ),
        tags={"core"},
        annotations={"readOnlyHint": False, "openWorldHint": True},
    )  # type: ignore
    async def run_workflow(
        workflow_id: str,
        message: str,
        ctx: Context,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> ToolResult:
        from agno.workflow.remote import RemoteWorkflow

        _require_tool_scopes("POST", f"/workflows/{workflow_id}/runs")
        user_id = _resolve_user_id(user_id)
        workflow = await _resolve_run_component(os, "workflows", workflow_id, user_id=user_id, session_id=session_id)
        # Mint a fresh session per call when omitted (matches REST), never the sticky default.
        session_id = _session_id_or_new(session_id)
        # Detach from FastMCP's tool-call span so the workflow run is its own root trace.
        with _detached_trace_context():
            if isinstance(workflow, RemoteWorkflow):
                run_output = await workflow.arun(message, user_id=user_id, session_id=session_id)
                return build_run_tool_result(run_output, result_mode)
            steps = getattr(workflow, "steps", None)
            total_steps = float(len(steps)) if isinstance(steps, (list, tuple)) and steps else None
            stream = workflow.arun(
                message,
                user_id=user_id,
                session_id=session_id,
                stream=True,
                stream_events=True,
            )
            run_output = await _consume_workflow_stream(ctx, workflow, stream, total_steps, user_id)
        return build_run_tool_result(run_output, result_mode)

    # ==================== Run Lifecycle Tools ====================

    @register_builtin_tool(
        name="continue_run",
        description=(
            "Resume a PAUSED run after resolving its requirements (human-in-the-loop). "
            "When a run tool returns status=PAUSED, its structuredContent carries the unresolved "
            "requirements; set the resolution fields on them (e.g. confirmation=true) and pass them "
            "back here unchanged otherwise. Provide exactly one of agent_id / team_id / workflow_id "
            "(the component that owns the run) plus the run_id and session_id from the paused result."
        ),
        tags={"core"},
        annotations={"readOnlyHint": False, "destructiveHint": False},
    )  # type: ignore
    async def continue_run(
        run_id: str,
        ctx: Context,
        session_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
        workflow_id: Optional[str] = None,
        requirements: Optional[List[Dict[str, Any]]] = None,
        user_id: Optional[str] = None,
    ) -> ToolResult:
        component_type, component_id = _classify_lifecycle_target(agent_id, team_id, workflow_id)
        _require_tool_scopes("POST", f"/{component_type}/{component_id}/runs/{run_id}/continue")
        user_id = _resolve_user_id(user_id)
        component = await _resolve_run_component(
            os, component_type, component_id, user_id=user_id, session_id=session_id
        )
        await _verify_run_ownership(component, component_type, component_id, session_id, run_id)
        # A run paused on an admin-required approval must be resolved by an admin, not
        # self-continued by its initiator; same gate the REST /continue route enforces.
        await _enforce_run_continuation_allowed(os.db, run_id)
        await _report_progress(ctx, 0.0, f"Continuing run {run_id}")
        try:
            # Detach from FastMCP's tool-call span so the resumed run is its own root trace.
            with _detached_trace_context():
                run_output = await run_service.continue_paused_run(
                    component,
                    run_id=run_id,
                    session_id=session_id,
                    user_id=user_id,
                    requirements=requirements,
                )
        except run_service.RemoteContinuationUnsupported as e:
            raise Exception(str(e))
        return build_run_tool_result(run_output, result_mode)

    @register_builtin_tool(
        name="cancel_run",
        description=(
            "Request cancellation of a running run. Irreversible: the run stops and is marked CANCELLED "
            "(if it has not started yet, the intent is recorded and applied when it does). Provide the "
            "run_id, its session_id, and exactly one of agent_id / team_id / workflow_id."
        ),
        tags={"core"},
        annotations={"destructiveHint": True, "idempotentHint": True},
    )  # type: ignore
    async def cancel_run(
        run_id: str,
        session_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
        workflow_id: Optional[str] = None,
    ) -> str:
        component_type, component_id = _classify_lifecycle_target(agent_id, team_id, workflow_id)
        _require_tool_scopes("POST", f"/{component_type}/{component_id}/runs/{run_id}/cancel")
        component = await _resolve_run_component(os, component_type, component_id, user_id=None, session_id=session_id)
        await _verify_run_ownership(component, component_type, component_id, session_id, run_id)
        await run_service.cancel_component_run(component, run_id)
        return f"Run {run_id} cancellation requested"

    # ==================== Session Tools (read-only) ====================
    # The MCP session surface is deliberately read-only continuity: run tools create
    # sessions implicitly, and destructive session management stays on the REST surface.

    @register_builtin_tool(
        name="get_sessions",
        description=(
            "List past sessions (conversations), newest first. Filter by session_type, component_id "
            "(an agent/team/workflow id from get_agentos_config), user, or session_name. Use a returned "
            "session_id with the run tools to continue that conversation, or with get_session_runs to "
            "read its history. db_id is only needed when get_agentos_config lists multiple databases."
        ),
        tags={"session"},
        annotations={"readOnlyHint": True},
    )  # type: ignore
    async def get_sessions(
        session_type: Literal["agent", "team", "workflow"] = "agent",
        component_id: Optional[str] = None,
        user_id: Optional[str] = None,
        session_name: Optional[str] = None,
        limit: int = 20,
        page: int = 1,
        sort_by: str = "created_at",
        sort_order: Literal["asc", "desc"] = "desc",
        db_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        _require_tool_scopes("GET", "/sessions")
        user_id = _scoped_read_user_id(user_id)
        db = await get_db(os.dbs, db_id)
        session_type_enum = SessionType(session_type)

        if isinstance(db, RemoteDb):
            result = await db.get_sessions(
                session_type=session_type_enum,
                component_id=component_id,
                user_id=user_id,
                session_name=session_name,
                limit=limit,
                page=page,
                sort_by=sort_by,
                sort_order=sort_order,
                db_id=db_id,
                headers=_forwarded_auth_headers(),
            )
            return result.model_dump()

        sessions, total_count = await session_service.get_sessions_page(
            db,
            session_type=session_type_enum,
            component_id=component_id,
            user_id=user_id,
            session_name=session_name,
            limit=limit,
            page=page,
            sort_by=sort_by,
            sort_order=sort_order,
        )
        total_pages = (total_count + limit - 1) // limit if limit > 0 else 0
        return PaginatedResponse(
            data=[SessionSchema.from_dict(session) for session in sessions],
            meta=PaginationInfo(page=page, limit=limit, total_count=total_count, total_pages=total_pages),
        ).model_dump()

    @register_builtin_tool(
        name="get_session_runs",
        description=(
            "Read a session's conversation history: each run's input and response content with its "
            "run_id, status, and timestamp, oldest first. Returns the answer content only, not the full "
            "message transcript. Pass run_id to get that one run in FULL, untrimmed detail -- the complete "
            "message transcript INCLUDING the system prompt/instructions, plus every event and metric. "
            "This is the debugging escape hatch and can be large (a long run returns a lot of tokens), so "
            "request a specific run_id deliberately, not by default. session_type is auto-detected when "
            "omitted; db_id is only needed when get_agentos_config lists multiple databases."
        ),
        tags={"session"},
        annotations={"readOnlyHint": True},
    )  # type: ignore
    async def get_session_runs(
        session_id: str,
        run_id: Optional[str] = None,
        session_type: Optional[Literal["agent", "team", "workflow"]] = None,
        user_id: Optional[str] = None,
        db_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        _require_tool_scopes("GET", f"/sessions/{session_id}/runs")
        user_id = _scoped_read_user_id(user_id)
        db = await get_db(os.dbs, db_id)
        session_type_enum = SessionType(session_type) if session_type else None

        if isinstance(db, RemoteDb):
            runs = await db.get_session_runs(
                session_id=session_id,
                session_type=session_type_enum,
                user_id=user_id,
                db_id=db_id,
                headers=_forwarded_auth_headers(),
            )
        else:
            # SessionNotFoundError propagates as the tool error verbatim ("Session {id} not found").
            runs = await session_service.get_session_runs(
                db, session_id=session_id, session_type=session_type_enum, user_id=user_id
            )

        if run_id is not None:
            for run in runs:
                data = run.model_dump() if hasattr(run, "model_dump") else dict(run)
                if data.get("run_id") == run_id:
                    return [data]
            raise Exception(f"Run {run_id} not found in session {session_id}")
        return [trim_session_run(r) for r in runs]

    # Register any user-provided custom tools. These share the same server, mount (/mcp),
    # lifespan, and JWT middleware as the built-in tools.
    _register_custom_tools(mcp, mcp_config)

    return mcp


def _add_authorize_middleware(mcp_app: StarletteWithLifespan, authorize: Callable[[Optional[str]], bool]) -> None:
    """Gate the MCP server with a per-call ``authorize(user_id) -> bool`` predicate.

    Runs after the JWT middleware (so ``request.state.user_id`` is the verified subject) and
    returns 401 before any tool or model runs when the predicate rejects the caller.
    """
    from starlette.middleware.base import BaseHTTPMiddleware
    from starlette.responses import JSONResponse

    class _MCPAuthorizeMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request, call_next):  # type: ignore[no-untyped-def]
            user_id = getattr(getattr(request, "state", None), "user_id", None)
            if not authorize(user_id):
                return JSONResponse(
                    {"error": "unauthorized", "detail": "Not authorized for the MCP server."},
                    status_code=401,
                )
            return await call_next(request)

    mcp_app.add_middleware(_MCPAuthorizeMiddleware)


# Localhost defaults so a desktop / local MCP server is protected with zero extra config.
_MCP_LOCALHOST_HOSTS = ("127.0.0.1", "localhost", "[::1]")


def _mcp_request_hostname(host_header: str) -> str:
    """Bare hostname from a Host header value, port stripped (keeps the ipv6 brackets)."""
    value = host_header.strip()
    if value.startswith("["):  # ipv6 literal, e.g. [::1]:7777
        end = value.find("]")
        return value[: end + 1] if end != -1 else value
    return value.split(":", 1)[0]


def _mcp_origin_hostname(origin: str) -> str:
    """Bare hostname from an Origin header value (keeps ipv6 brackets to match the defaults)."""
    from urllib.parse import urlparse

    hostname = urlparse(origin).hostname or ""
    return f"[{hostname}]" if ":" in hostname else hostname


def _mcp_host_allowed(hostname: str, allowed: set) -> bool:
    if hostname in allowed:
        return True
    return any(pattern.startswith("*.") and hostname.endswith(pattern[1:]) for pattern in allowed)


def _add_transport_security_middleware(
    mcp_app: StarletteWithLifespan,
    allowed_hosts: List[str],
    allowed_origins: Optional[List[str]],
) -> None:
    """Add built-in DNS-rebinding protection: validate the Host (and Origin when present).

    Allowed hosts always include localhost, so a desktop / local MCP server works out of the box;
    callers list only their deploy or tunnel host. Anything else is rejected with 400 before the
    request reaches the MCP machinery.
    """
    from starlette.middleware.base import BaseHTTPMiddleware
    from starlette.responses import JSONResponse

    host_set = {_mcp_request_hostname(h) for h in list(allowed_hosts) + list(_MCP_LOCALHOST_HOSTS)}
    origin_set = set(allowed_origins or [])

    class _MCPTransportSecurityMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request, call_next):  # type: ignore[no-untyped-def]
            host = _mcp_request_hostname(request.headers.get("host", ""))
            if not _mcp_host_allowed(host, host_set):
                return JSONResponse({"error": "invalid_host", "detail": "Host not allowed."}, status_code=400)
            origin = request.headers.get("origin")
            if (
                origin is not None
                and origin not in origin_set
                and not _mcp_host_allowed(_mcp_origin_hostname(origin), host_set)
            ):
                return JSONResponse({"error": "invalid_origin", "detail": "Origin not allowed."}, status_code=400)
            return await call_next(request)

    mcp_app.add_middleware(_MCPTransportSecurityMiddleware)


def _mcp_server_is_open(os: "AgentOS") -> bool:
    """True when /mcp serves anonymous callers: no auth is effectively enforced.

    Delegates to :func:`get_effective_auth_mode` -- the same detection the auth layer and
    ``/info`` use -- so this agrees with them on every mode: ``AgentOS(authorization=True)``,
    JWT env vars, a manually installed ``JWTMiddleware`` on a ``base_app``, and the security
    key all count as authenticated. Only when it returns "none" does /mcp answer requests
    carrying no bearer token (a service-account verifier alone does NOT close that path --
    PATs are checked only when presented). That anonymous case is the one a rebound web page
    could drive, so it is the case that needs default transport security. Authenticated
    deployments rely on the bearer token instead, so their deployed hostname is not gated.
    """
    from agno.os.auth import get_effective_auth_mode

    return (
        get_effective_auth_mode(
            getattr(os, "settings", None),
            bool(getattr(os, "authorization", False)),
            getattr(os, "base_app", None),
        )
        == "none"
    )


def get_mcp_server(
    os: "AgentOS",
) -> StarletteWithLifespan:
    """Build the MCP HTTP app served at ``/mcp``.

    Wraps :func:`build_mcp_server` with the Streamable HTTP transport and layers on
    the optional ``authorize`` gate, any app-provided middleware, and the built-in
    DNS-rebinding protection from ``mcp_config``.

    Authentication is NOT layered here: the parent app's single ``AuthMiddleware``
    (agno/os/app.py::_add_auth_middleware) runs before Starlette dispatches to this
    mount, so it already verified the token and attached the identity to
    request.state. Per-tool scope enforcement lives in the tools themselves
    (``_require_tool_scopes``).
    """
    mcp = build_mcp_server(os)
    mcp_config: "Optional[MCPServerConfig]" = getattr(os, "mcp_config", None)

    # Use http_app for Streamable HTTP transport (modern MCP standard).
    # fastmcp >= 3.4.3 adds a Host/Origin guard with localhost-only defaults, which 421s
    # deployed hosts before our own middleware runs. Disable it where the parameter exists
    # and run AgentOS's single validation engine instead (the transport-security middleware
    # below), which protects open servers by default and lets deployed hosts opt in via
    # MCPServerConfig.allowed_hosts.
    http_app_kwargs: Dict[str, Any] = {"path": "/mcp"}
    if "host_origin_protection" in inspect.signature(mcp.http_app).parameters:
        http_app_kwargs["host_origin_protection"] = False
    mcp_app = mcp.http_app(**http_app_kwargs)

    # Middleware runs in reverse registration order (last added is outermost / runs first).
    # Target running order: transport security -> app middleware -> authorize gate -> tool.
    # Auth already ran on the parent app, so the gate sees the verified identity.

    # Innermost: per-call authorize gate.
    if mcp_config is not None and mcp_config.authorize is not None:
        # The gate reads request.state.user_id, populated by the parent AuthMiddleware.
        # Without any auth configured that attribute is never set, so the gate sees
        # user_id=None on every call -- an ``authorize=lambda u: u in OWNER_IDS`` gate
        # then rejects everyone (or "allows" everyone if permissive on None). Warn loudly.
        if not os.authorization:
            from agno.utils.log import log_warning

            log_warning(
                "MCPServerConfig.authorize is set but AgentOS(authorization=False); the gate will "
                "be called with user_id=None on every request because no JWT middleware populates "
                "request.state.user_id. Either pass authorization=True with an authorization_config, "
                "or write your authorize() to handle user_id=None explicitly (e.g. for a dev shortcut)."
            )
        _add_authorize_middleware(mcp_app, mcp_config.authorize)

    # App-provided middleware, preserving the order they were listed in.
    if mcp_config is not None and mcp_config.middleware:
        for mw in reversed(mcp_config.middleware):
            cls, args, kwargs = mw
            mcp_app.add_middleware(cls, *args, **kwargs)

    # Outermost: built-in DNS-rebinding protection (runs first, before auth and tools).
    #
    # A configured ``allowed_hosts`` always applies. On top of that, when the server is OPEN
    # (no JWT and no security key, so /mcp answers anonymous callers) we default to
    # localhost-only protection even without ``allowed_hosts`` -- this is the one config a
    # rebound web page could drive, and it restores the safe default fastmcp's own guard gave
    # before we disabled it. Authenticated deployments rely on the bearer token, which a
    # rebinding attacker cannot supply, so protection there stays opt-in: their real hostname
    # is not gated (the 421/400 regression the built-in guard caused) unless they set
    # ``allowed_hosts`` themselves.
    allowed_hosts = mcp_config.allowed_hosts if mcp_config is not None else None
    allowed_origins = mcp_config.allowed_origins if mcp_config is not None else None
    if allowed_hosts is None and _mcp_server_is_open(os):
        allowed_hosts = []
    if allowed_hosts is not None:
        _add_transport_security_middleware(mcp_app, allowed_hosts, allowed_origins)

    return mcp_app
