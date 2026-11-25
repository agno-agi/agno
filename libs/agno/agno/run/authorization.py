"""Caller authority for tools, independent of the transport that starts a run.

Authority is supplied by trusted application code, never by model arguments,
session state or run metadata. Context variables preserve it across delegation
and asyncio thread workers without changing every component's run signature.
Request identity alone does not tighten existing tool permissions. Manager tool
execution activates operation checks, which then follow its delegated work.
"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, replace
from functools import wraps
from inspect import isasyncgen, iscoroutinefunction, isgenerator, signature
from typing import TYPE_CHECKING, Any, Callable, Dict, Iterator, List, Literal, Optional, overload

if TYPE_CHECKING:
    from agno.os.authz.provider import AuthorizationContext, AuthorizationProvider


@dataclass
class RunAuthorization:
    provider: AuthorizationProvider
    context: AuthorizationContext
    # PATs use their own ACL even when the application uses managed roles.
    service_account: bool = False
    # Requests carry identity without changing existing tools' permission contract.
    # Manager tool execution activates checks for its nested work. Explicit
    # RunAuthorization instances enforce by default for trusted Python callers.
    enforce_tools: bool = True
    # A schedule fired this run with the saved authority of the person who created it. Nobody is present.
    scheduled: bool = False
    # Loaded from an authority that was stored with a schedule, a Routine or a Task acceptance,
    # not built from a live request. A live caller's authority that only passes through the job
    # queue or an internal hop is not saved.
    saved: bool = False

    def _saved_scopes_reach_mini_agent(self, ctx: AuthorizationContext, scopes: List[str]) -> bool:
        """Whether this saved authority reaches Mini Agent on scopes that name no component.

        A wildcard scope does not reach a built-in component. An authority saved before that rule
        carries the scopes its author's token had then, and a token that could run every agent
        could run Mini Agent. Work saved then keeps running: for Mini Agent, the saved scopes are
        asked as they were, with no component named. This holds for saved authority only: saving
        or editing a Routine, or accepting a Task, asks for Mini Agent by name. Mini Agent runs
        nothing but Routines and Tasks, so no other work is reached this way."""
        if not self.saved or not getattr(self.provider, "enforces_token_scopes", False):
            return False
        # Running a Routine or a Task starts Mini Agent and reads the run back. Nothing else is asked
        if ctx.action not in ("run", "read"):
            return False
        from agno.os.scopes import has_required_scopes
        from agno.registry._reserved import MANAGER_RESOURCES, MINI_AGENT_ID

        if f"{ctx.resource_type}/{ctx.resource_id}" != MANAGER_RESOURCES[MINI_AGENT_ID]:
            return False
        return has_required_scopes(list(ctx.scopes or []), scopes, admin_scope=ctx.admin_scope)

    def authorizes_route(self, ctx: AuthorizationContext, scopes: List[str]) -> bool:
        """Whether this authority satisfies a route's required scopes, in the context given."""
        return self.provider.authorize_route(ctx, scopes) or self._saved_scopes_reach_mini_agent(ctx, scopes)

    async def aauthorizes_route(self, ctx: AuthorizationContext, scopes: List[str]) -> bool:
        """Async twin of :meth:`authorizes_route`."""
        return await self.provider.aauthorize_route(ctx, scopes) or self._saved_scopes_reach_mini_agent(ctx, scopes)

    def _decision(self, resource: str, action: str, resource_id: Optional[str]):
        ctx = replace(self.context, resource_type=resource, resource_id=resource_id, action=action)
        if resource == "agent_os" and action == "admin":
            ctx = replace(ctx, resource_type=None, resource_id=None, action=None)
            return ctx, [self.context.admin_scope or "agent_os:admin"]
        if resource not in ("agents", "teams", "workflows"):
            # Match REST's non-resource route contract. A custom provider's
            # check() may defer unknown resources; authorize_route() must decide
            # these global permissions explicitly rather than granting by default.
            ctx = replace(ctx, resource_type=None, resource_id=None, action=None)
        return ctx, [f"{resource}:{action}"]

    def require(self, resource: str, action: str, resource_id: Optional[str] = None) -> None:
        ctx, scopes = self._decision(resource, action, resource_id)
        if not self.authorizes_route(ctx, scopes):
            permission = f"{resource}:{resource_id}:{action}" if resource_id else scopes[0]
            raise PermissionError(f"Permission required: {permission}")

    async def arequire(self, resource: str, action: str, resource_id: Optional[str] = None) -> None:
        ctx, scopes = self._decision(resource, action, resource_id)
        if not await self.aauthorizes_route(ctx, scopes):
            permission = f"{resource}:{resource_id}:{action}" if resource_id else scopes[0]
            raise PermissionError(f"Permission required: {permission}")

    def snapshot(self) -> Dict[str, Any]:
        from dataclasses import asdict

        return {
            # Roles an application grants a run are kept only when set, so every other snapshot stays unchanged
            "context": {k: v for k, v in asdict(self.context).items() if k != "roles" or v is not None},
            "service_account": self.service_account,
            "enforce_tools": self.enforce_tools,
            **({"scheduled": True} if self.scheduled else {}),
            # A saved authority stays saved when its run goes through the job queue or an internal hop
            **({"saved": True} if self.saved else {}),
        }


_AUTHORITY: ContextVar[Optional[Callable[[], Optional[RunAuthorization]]]] = ContextVar(
    "agno_run_authorization", default=None
)


def current_authorization() -> Optional[RunAuthorization]:
    factory = _AUTHORITY.get()
    return factory() if factory is not None else None


@contextmanager
def authorization_scope(factory: Callable[[], Optional[RunAuthorization]]) -> Iterator[None]:
    token = _AUTHORITY.set(factory)
    try:
        yield
    finally:
        _AUTHORITY.reset(token)


def _caller_authorization(run_context: Any = None) -> Optional[RunAuthorization]:
    # An active request/worker always wins over a stale RunContext on a resume.
    if _AUTHORITY.get() is not None:
        return current_authorization()
    value = getattr(run_context, "authorization", None)
    return value if isinstance(value, RunAuthorization) else None


def authorization_for(run_context: Any = None) -> Optional[RunAuthorization]:
    """Return authority only when operation checks are active for this execution."""
    authority = _caller_authorization(run_context)
    if authority is None:
        return None
    return authority if authority.enforce_tools else None


def require_permission(resource: str, action: str, resource_id: Optional[str] = None, run_context: Any = None) -> None:
    authority = authorization_for(run_context)
    if authority is not None:
        authority.require(resource, action, resource_id)


async def arequire_permission(
    resource: str, action: str, resource_id: Optional[str] = None, run_context: Any = None
) -> None:
    authority = authorization_for(run_context)
    if authority is not None:
        await authority.arequire(resource, action, resource_id)


def requires_permission(resource: Optional[str] = None, action: Optional[str] = None) -> Callable:
    """Gate an operation inside an enforced caller scope without model-supplied authority."""

    def decorate(function: Callable) -> Callable:
        sig = signature(function)

        def context(args: Any, kwargs: Any) -> Any:
            bound = sig.bind(*args, **kwargs).arguments
            return bound.get("_agno_run_context", bound.get("run_context"))

        if iscoroutinefunction(function):

            @wraps(function)
            async def bound_async(*args: Any, **kwargs: Any) -> Any:
                authority = _caller_authorization(context(args, kwargs))
                if authority is not None and authority.enforce_tools and resource is not None and action is not None:
                    await authority.arequire(resource, action)
                with authorization_scope(lambda: authority):
                    return await function(*args, **kwargs)

            setattr(bound_async, "_agno_authorization_sensitive", True)
            return bound_async

        @wraps(function)
        def sync_call(*args: Any, **kwargs: Any) -> Any:
            authority = _caller_authorization(context(args, kwargs))
            if authority is not None and authority.enforce_tools and resource is not None and action is not None:
                authority.require(resource, action)
            with authorization_scope(lambda: authority):
                return function(*args, **kwargs)

        setattr(sync_call, "_agno_authorization_sensitive", True)
        return sync_call

    return decorate


def require_task_authority(metadata: Any, authority: Optional[RunAuthorization]) -> None:
    """Refuse to go on with a run that a Company Task started, once it has left the Task's authority.

    Mini Agent runs components only inside a Task, under the Task's limits. The dispatch lineage stored
    on such a run names Mini Agent. A continuation holds the caller's own authority, not the Task's.
    """
    from agno.db.schemas.scheduler import DISPATCH_CHAIN_METADATA_KEY
    from agno.registry._reserved import MINI_AGENT_ID

    chain = metadata.get(DISPATCH_CHAIN_METADATA_KEY) if isinstance(metadata, dict) else None
    if not isinstance(chain, list) or f"agent:{MINI_AGENT_ID}" not in chain:
        return
    from agno.company.execution import _ExecutorAuthorization

    if not isinstance(authority, _ExecutorAuthorization):
        raise PermissionError(
            "This run was started by a Company Task and cannot continue outside it. "
            "Send the Task back, or run the component yourself."
        )


@contextmanager
def _tool_authorization(function: Any) -> Iterator[Optional[RunAuthorization]]:
    """Activate operation checks for manager tools and preserve them through delegation."""
    authority = _caller_authorization(function._run_context)
    require_task_authority(getattr(function._run_context, "metadata", None), authority)
    if authority is not None and not authority.enforce_tools:
        from agno.registry._reserved import RESERVED_MANAGER_IDS

        # These IDs are framework-reserved across registration and rehydration.
        # Unlike metadata, they survive per-run component copies without a new flag.
        owners = (function._agent, function._team)
        if any(getattr(owner, "id", None) in RESERVED_MANAGER_IDS for owner in owners):
            authority = replace(authority, enforce_tools=True)
    with authorization_scope(lambda: authority):
        yield authority


def _authorized_tool_result(result: Any, authority: Optional[RunAuthorization]) -> Any:
    """Keep lazy tool work authorized without leaking its scope to the consumer."""
    if authority is None or not authority.enforce_tools:
        return result
    if isgenerator(result):

        def iterate():
            try:
                while True:
                    with authorization_scope(lambda: authority):
                        try:
                            value = next(result)
                        except StopIteration:
                            return
                    yield value
            finally:
                with authorization_scope(lambda: authority):
                    result.close()

        return iterate()
    if isasyncgen(result):

        async def aiterate():
            try:
                while True:
                    with authorization_scope(lambda: authority):
                        try:
                            value = await result.__anext__()
                        except StopAsyncIteration:
                            return
                    yield value
            finally:
                with authorization_scope(lambda: authority):
                    await result.aclose()

        return aiterate()
    return result


AUTHORIZATION_KEY = "_agno_authorization"
AUTHORIZATION_HEADER = "X-Agno-Run-Authorization"


def authorization_snapshot() -> Optional[Dict[str, Any]]:
    authority = current_authorization()
    return authority.snapshot() if authority is not None else None


@overload
def stamp_authorization(payload: Optional[Dict[str, Any]], *, include_trusted: Literal[True]) -> Dict[str, Any]: ...


@overload
def stamp_authorization(
    payload: Optional[Dict[str, Any]], *, include_trusted: Literal[False] = False
) -> Optional[Dict[str, Any]]: ...


def stamp_authorization(
    payload: Optional[Dict[str, Any]], *, include_trusted: bool = False
) -> Optional[Dict[str, Any]]:
    """Overwrite caller-supplied authority at a trusted persistence boundary."""
    cleaned = {key: value for key, value in (payload or {}).items() if key != AUTHORIZATION_KEY}
    snapshot = authorization_snapshot()
    if snapshot is not None or include_trusted:
        cleaned[AUTHORIZATION_KEY] = snapshot
    return cleaned if cleaned or payload is not None else None


def _run_endpoint_target(endpoint: str, method: str) -> Any:
    """The (type, id) a schedule endpoint runs, read from the path as the server will route it."""
    import posixpath
    from urllib.parse import unquote, urlsplit

    from agno.db.schemas.scheduler import RUN_ENDPOINT_RE

    if method.upper() != "POST":
        return None
    # Decoded and normalised first: "/agents/mini%61gent/runs" reaches the same agent as its plain form
    return RUN_ENDPOINT_RE.fullmatch(posixpath.normpath(unquote(urlsplit(endpoint).path)))


def require_schedule_target(endpoint: str, method: str = "POST") -> None:
    match = _run_endpoint_target(endpoint, method)
    if match is None:
        require_permission("agent_os", "admin")
    else:
        require_permission(match.group(1), "run", match.group(2))


async def arequire_schedule_target(endpoint: str, method: str = "POST") -> None:
    match = _run_endpoint_target(endpoint, method)
    if match is None:
        await arequire_permission("agent_os", "admin")
    else:
        await arequire_permission(match.group(1), "run", match.group(2))


def public_payload(payload: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Keep persisted caller claims out of tool results and API responses."""
    if payload is None:
        return None
    return {
        key: value for key, value in payload.items() if key not in {AUTHORIZATION_KEY, "_agno_company_acceptance"}
    } or None
