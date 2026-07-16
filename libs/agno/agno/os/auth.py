import asyncio
import hmac
from functools import lru_cache
from os import getenv
from typing import Any, Dict, List, Literal, Optional, Set

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from starlette.concurrency import run_in_threadpool

from agno.os.scopes import (
    get_accessible_resource_ids,
    get_default_scope_mappings,
    has_required_scopes,
)
from agno.os.service_accounts import TOKEN_PREFIX as SERVICE_ACCOUNT_TOKEN_PREFIX
from agno.os.service_accounts import ServiceAccountVerification, authenticate_service_account_request
from agno.os.settings import AgnoAPISettings

# Create a global HTTPBearer instance
security = HTTPBearer(auto_error=False)


@lru_cache(maxsize=1)
def _default_scope_mappings() -> Dict[str, List[str]]:
    """The default route→scope mappings, built once (they are static data) so the
    per-request service-account path does not rebuild the dict on every call."""
    return get_default_scope_mappings()


# Scopes granted to the internal service token (used by the scheduler executor).
# Shared constant so auth.py and jwt.py stay in sync.
INTERNAL_SERVICE_SCOPES: List[str] = [
    "agents:read",
    "agents:run",
    "teams:read",
    "teams:run",
    "workflows:read",
    "workflows:run",
    "schedules:read",
    "schedules:write",
    "schedules:delete",
]


def get_auth_token_from_request(request: Request) -> Optional[str]:
    """
    Extract the JWT/Bearer token from the Authorization header.

    This is used to forward the auth token to remote agents/teams/workflows
    when making requests through the gateway.

    Args:
        request: The FastAPI request object

    Returns:
        The bearer token string if present, None otherwise

    Usage:
        auth_token = get_auth_token_from_request(request)
        if auth_token and isinstance(agent, RemoteAgent):
            await agent.arun(message, auth_token=auth_token)
    """
    auth_header = request.headers.get("Authorization")
    if auth_header and auth_header.lower().startswith("bearer "):
        return auth_header[7:]  # Remove "Bearer " prefix
    return None


async def _authenticate_service_account(
    request: Request, token: str, treat_unverifiable_as_anonymous: bool = False
) -> bool:
    """Verify a service account token (agno_pat_...) and attach its identity to the request.

    Runs for requests that carry an ``agno_pat_`` bearer but were not already
    authenticated by the auth middleware. On success, request.state gets the same
    identity the middleware would attach (user_id = the ``sa:<name>`` principal,
    the account's scopes) and the scopes are enforced against the route. Scope
    enforcement is never skipped: service account scopes are ACL data owned by
    this AgentOS instance, unlike JWT claims.

    ``treat_unverifiable_as_anonymous`` selects what happens when the token can
    NOT be verified (unknown, expired, revoked, or verification unavailable):

    - ``False`` (instances with auth configured): the request is rejected.
    - ``True`` (open instances -- no security key, no JWT): the token is ignored
      and the request proceeds anonymously, the same as any other unrecognized
      header on a server without auth. This keeps a stale token left behind in a
      client from locking out an instance that has no auth on it.

    A token that DOES verify is never ignored: it attributes the request and its
    scopes apply, in both modes.
    """
    verifier = getattr(request.app.state, "service_account_verifier", None)
    if verifier is None:
        if treat_unverifiable_as_anonymous:
            return True
        raise HTTPException(status_code=401, detail="Service accounts are not enabled on this AgentOS instance")

    admin_scope_raw = getattr(request.app.state, "admin_scope", None)
    admin_scope = admin_scope_raw if isinstance(admin_scope_raw, str) else None

    error = await authenticate_service_account_request(
        request,
        token,
        verifier=verifier,
        scope_mappings=_default_scope_mappings(),
        admin_scope=admin_scope,
    )
    if error is not None:
        status_code, detail, required_scopes = error
        if status_code == 403:
            # The token verified, so the account's ACL applies: insufficient scopes
            # reject the request even on an otherwise-open instance.
            raise HTTPException(status_code=403, detail=build_insufficient_permissions_detail(required_scopes))
        if treat_unverifiable_as_anonymous:
            return True
        raise HTTPException(status_code=status_code, detail=detail)

    return True


def _is_jwt_configured() -> bool:
    """Check if JWT authentication is configured via environment variables.

    This covers cases where JWT middleware is set up manually (not via authorization=True).
    """
    return bool(getenv("JWT_VERIFICATION_KEY") or getenv("JWT_JWKS_FILE"))


def _has_jwt_middleware(app: Any) -> bool:
    """Check whether the app has JWTMiddleware installed via ``add_middleware``.

    Covers deployments that wire JWT auth by calling ``app.add_middleware(JWTMiddleware, ...)``
    directly instead of via ``AgentOS(authorization=True)`` or JWT env vars.
    """
    if app is None:
        return False
    try:
        from agno.os.middleware.jwt import JWTMiddleware, jwt_kwargs_have_key_source
    except ImportError:
        return False
    user_middleware = getattr(app, "user_middleware", None) or []
    for mw in user_middleware:
        cls = getattr(mw, "cls", None)
        if not (isinstance(cls, type) and issubclass(cls, JWTMiddleware)):
            continue
        # Only count instances that actually validate JWTs: AgentOS installs the same
        # middleware class as the auth layer for security-key / service-account-only
        # modes, constructed without any JWT source. (Env-var-configured JWT is
        # detected separately by _is_jwt_configured.)
        if jwt_kwargs_have_key_source(getattr(mw, "kwargs", None) or {}):
            return True
    return False


def get_effective_auth_mode(
    settings: Optional[AgnoAPISettings],
    authorization: bool = False,
    app: Any = None,
) -> Literal["none", "security_key", "jwt"]:
    """Return the REST/WS authentication mode effectively enforced by the OS.

    This describes the REST/WS plane only. ``mcp_auth`` is deliberately NOT consulted:
    it protects the MCP endpoint alone (its own OAuth surface is described separately
    under ``/info``'s ``mcp.oauth`` block), so folding it in here would mislabel a
    deployment -- reporting "oauth" while REST is actually open, or masking a real "jwt"
    REST posture. Consumers read this to pick REST/WS credentials, so it must reflect the
    REST plane. The precedence mirrors ``get_authentication_dependency``: JWT (via
    authorization=True on AgentOS, JWT environment variables, or a manually installed
    ``JWTMiddleware``) over the security key over no auth.

    Args:
        settings: The API settings containing the security key and authorization flag
        authorization: The AgentOS authorization flag (JWT middleware enabled)
        app: The Starlette/FastAPI app instance; when provided, its middleware stack
            is inspected so a manually-installed ``JWTMiddleware`` is detected.

    Returns:
        "jwt" when JWT authorization is effectively active, "security_key" when only the
        OS security key is enforced, "none" when REST authentication is disabled.
    """
    if (
        authorization
        or (settings is not None and settings.authorization_enabled)
        or _is_jwt_configured()
        or _has_jwt_middleware(app)
    ):
        return "jwt"
    if settings is not None and settings.os_security_key:
        return "security_key"
    return "none"


def get_authentication_dependency(settings: AgnoAPISettings):
    """
    Create an authentication dependency function for FastAPI routes.

    This handles security key authentication (OS_SECURITY_KEY).
    When JWT authorization is enabled (via authorization=True, JWT environment variables,
    or manually added JWT middleware), this dependency is skipped as JWT middleware
    handles authentication.

    Args:
        settings: The API settings containing the security key and authorization flag

    Returns:
        A dependency function that can be used with FastAPI's Depends()
    """

    async def auth_dependency(request: Request, credentials: HTTPAuthorizationCredentials = Depends(security)) -> bool:
        # If JWT authorization is enabled via settings (authorization=True on AgentOS)
        if settings and settings.authorization_enabled:
            return True

        # Check if JWT middleware has already handled authentication
        if getattr(request.state, "authenticated", False):
            return True

        # Service account tokens (agno_pat_...) are dispatched by prefix: they never
        # reach the JWT validator or the security-key comparison below. With auth
        # configured (security key or JWT), a PAT must verify or the request is
        # rejected. On an open instance a PAT that verifies still provides
        # attribution and scope enforcement, while one that cannot be verified is
        # ignored like any other unrecognized header on a server without auth.
        token = credentials.credentials if credentials else None
        if token and token.startswith(SERVICE_ACCOUNT_TOKEN_PREFIX):
            instance_has_auth = bool(settings and settings.os_security_key) or _is_jwt_configured()
            return await _authenticate_service_account(
                request, token, treat_unverifiable_as_anonymous=not instance_has_auth
            )

        # Also skip if JWT is configured via environment variables
        if _is_jwt_configured():
            return True

        # If no security key is set, skip authentication entirely
        if not settings or not settings.os_security_key:
            return True

        # If security is enabled but no authorization header provided, fail
        if not credentials:
            raise HTTPException(status_code=401, detail="Authorization header required")

        token = credentials.credentials

        # Check internal service token (used by scheduler executor)
        internal_token = getattr(request.app.state, "internal_service_token", None)
        if internal_token and hmac.compare_digest(token, internal_token):
            request.state.authenticated = True
            request.state.user_id = "__scheduler__"
            request.state.scopes = list(INTERNAL_SERVICE_SCOPES)
            return True

        # Verify the token against security key
        if token != settings.os_security_key:
            raise HTTPException(status_code=401, detail="Invalid authentication token")

        # A valid security key is a trusted, unscoped root. Mark it authenticated like the
        # internal-token path above, so downstream gates that distinguish an authenticated
        # root from an anonymous open-mode caller (e.g. service-account minting) treat it as
        # a real credential rather than falling through to the fail-closed anonymous branch.
        request.state.authenticated = True
        return True

    return auth_dependency


def validate_websocket_token(token: str, settings: AgnoAPISettings) -> bool:
    """
    Validate a bearer token for WebSocket authentication (legacy os_security_key method).

    When JWT authorization is enabled (via authorization=True or JWT environment variables),
    this validation is skipped as JWT middleware handles authentication.

    Args:
        token: The bearer token to validate
        settings: The API settings containing the security key and authorization flag

    Returns:
        True if the token is valid or authentication is disabled, False otherwise
    """
    # If JWT authorization is enabled, skip security key validation
    if settings and settings.authorization_enabled:
        return True

    # Also skip if JWT is configured via environment variables (manual JWT middleware setup)
    if _is_jwt_configured():
        return True

    # If no security key is set, skip authentication entirely
    if not settings or not settings.os_security_key:
        return True

    # Verify the token matches the configured security key
    return token == settings.os_security_key


async def verify_websocket_service_account(
    token: str, app: Any, client_key: Optional[str] = None
) -> Optional[ServiceAccountVerification]:
    """Verify a service-account token (``agno_pat_...``) for WebSocket authentication.

    The REST dependency accepts service account tokens in every deployment mode, so the
    WebSocket path must too. Returns the full verification result (None when no verifier
    is configured) rather than a bare pass/fail: the caller needs ``result.account`` --
    its principal and scopes -- to populate the WebSocket auth context so the same RBAC
    and attribution gates that police JWTs apply to PATs.
    """
    verifier = getattr(app.state, "service_account_verifier", None)
    if verifier is None:
        return None
    return await verifier.verify(token, client_key=client_key)


def build_insufficient_permissions_detail(required_scopes: Optional[List[str]]) -> str:
    """Format a 403 detail string, appending the required scope(s) when known."""
    base = "Insufficient permissions"
    if required_scopes:
        return f"{base}. Required scope(s): {', '.join(required_scopes)}"
    return base


def get_accessible_resources(request: Request, resource_type: str) -> Set[str]:
    """
    Get the set of resource IDs the user has access to based on their scopes.

    This function is used to filter lists of resources (agents, teams, workflows)
    based on the user's scopes from their JWT token.

    Args:
        request: The FastAPI request object (contains request.state.scopes)
        resource_type: Type of resource ("agents", "teams", "workflows")

    Returns:
        Set of resource IDs the user can access. Returns {"*"} for wildcard access.

    Usage:
        accessible_ids = get_accessible_resources(request, "agents")
        if "*" not in accessible_ids:
            agents = [a for a in agents if a.id in accessible_ids]

    Examples:
        >>> # User with specific agent access
        >>> # Token scopes: ["agent-os:my-os:agents:my-agent:read"]
        >>> get_accessible_resources(request, "agents")
        {'my-agent'}

        >>> # User with wildcard access
        >>> # Token scopes: ["agent-os:my-os:agents:*:read"] or ["admin"]
        >>> get_accessible_resources(request, "agents")
        {'*'}

        >>> # User with agent-os level access (global resource scope)
        >>> # Token scopes: ["agent-os:my-os:agents:read"]
        >>> get_accessible_resources(request, "agents")
        {'*'}
    """
    # Check if accessible_resource_ids is already cached in request state (set by JWT middleware)
    # This happens when user doesn't have global scope but has specific resource scopes
    cached_ids = getattr(request.state, "accessible_resource_ids", None)
    if cached_ids is not None:
        return cached_ids

    # Get user's scopes from request state (set by JWT middleware)
    user_scopes = getattr(request.state, "scopes", [])

    # Honour any custom admin_scope configured on JWTMiddleware (set on
    # request.state by the middleware). Without this, list endpoints reject
    # custom-admin tokens with 403 even though check_resource_access would
    # accept them.
    admin_scope_raw = getattr(request.state, "admin_scope", None)
    admin_scope = admin_scope_raw if isinstance(admin_scope_raw, str) else None

    # Get accessible resource IDs
    accessible_ids = get_accessible_resource_ids(
        user_scopes=user_scopes,
        resource_type=resource_type,
        admin_scope=admin_scope,
    )

    return accessible_ids


def filter_resources_by_access(request: Request, resources: List, resource_type: str) -> List:
    """
    Filter a list of resources based on user's access permissions.

    Args:
        request: The FastAPI request object
        resources: List of resource objects (agents, teams, or workflows) with 'id' attribute
        resource_type: Type of resource ("agents", "teams", "workflows")

    Returns:
        Filtered list of resources the user has access to

    Usage:
        agents = filter_resources_by_access(request, all_agents, "agents")
        teams = filter_resources_by_access(request, all_teams, "teams")
        workflows = filter_resources_by_access(request, all_workflows, "workflows")

    Examples:
        >>> # User with specific access
        >>> agents = [Agent(id="agent-1"), Agent(id="agent-2"), Agent(id="agent-3")]
        >>> # Token scopes: ["agent-os:my-os:agents:agent-1:read", "agent-os:my-os:agents:agent-2:read"]
        >>> filter_resources_by_access(request, agents, "agents")
        [Agent(id="agent-1"), Agent(id="agent-2")]

        >>> # User with wildcard access
        >>> # Token scopes: ["admin"]
        >>> filter_resources_by_access(request, agents, "agents")
        [Agent(id="agent-1"), Agent(id="agent-2"), Agent(id="agent-3")]
    """
    accessible_ids = get_accessible_resources(request, resource_type)

    # Wildcard access - return all resources
    if "*" in accessible_ids:
        return resources

    # Filter to only accessible resources
    return [r for r in resources if r.id in accessible_ids]


def check_resource_access(request: Request, resource_id: str, resource_type: str, action: str = "read") -> bool:
    """
    Check if user has access to a specific resource for a specific action.

    Args:
        request: The FastAPI request object
        resource_id: ID of the resource to check
        resource_type: Type of resource ("agents", "teams", "workflows")
        action: Action to check ("read", "run", etc.)

    Returns:
        True if user has access, False otherwise

    Usage:
        if not check_resource_access(request, agent_id, "agents", "run"):
            raise HTTPException(status_code=403, detail="Access denied")

    Examples:
        >>> # Token scopes: ["agents:my-agent:read", "agents:my-agent:run"]
        >>> check_resource_access(request, "my-agent", "agents", "run")
        True

        >>> # Token scopes: ["agents:my-agent:read"] (no run scope)
        >>> check_resource_access(request, "my-agent", "agents", "run")
        False
    """
    user_scopes = getattr(request.state, "scopes", [])
    # Honour the configured admin scope (set by JWTMiddleware on request.state)
    # so custom-admin tokens are recognised here too. Non-string values (e.g.
    # MagicMock attributes in tests) are ignored.
    admin_scope_raw = getattr(request.state, "admin_scope", None)
    admin_scope = admin_scope_raw if isinstance(admin_scope_raw, str) else None
    accessible_ids = get_accessible_resource_ids(
        user_scopes=user_scopes,
        resource_type=resource_type,
        action=action,
        admin_scope=admin_scope,
    )

    # Wildcard access grants all permissions
    if "*" in accessible_ids:
        return True

    # Check if user has access to this specific resource
    return resource_id in accessible_ids


def require_resource_access(resource_type: str, action: str, resource_id_param: str):
    """
    Create a dependency that checks if the user has access to a specific resource.

    This dependency factory creates a FastAPI dependency that automatically checks
    authorization when authorization is enabled. It extracts the resource ID from
    the path parameters and verifies the user has the required access.

    Args:
        resource_type: Type of resource ("agents", "teams", "workflows")
        action: Action to check ("read", "run")
        resource_id_param: Name of the path parameter containing the resource ID

    Returns:
        A dependency function for use with FastAPI's Depends()

    Usage:
        @router.post("/agents/{agent_id}/runs")
        async def create_agent_run(
            agent_id: str,
            request: Request,
            _: None = Depends(require_resource_access("agents", "run", "agent_id")),
        ):
            ...

        @router.get("/agents/{agent_id}")
        async def get_agent(
            agent_id: str,
            request: Request,
            _: None = Depends(require_resource_access("agents", "read", "agent_id")),
        ):
            ...

    Examples:
        >>> # Creates dependency for checking agent run access
        >>> dep = require_resource_access("agents", "run", "agent_id")

        >>> # Creates dependency for checking team read access
        >>> dep = require_resource_access("teams", "read", "team_id")
    """
    # Map resource_type to singular form for error messages
    resource_singular = {
        "agents": "agent",
        "teams": "team",
        "workflows": "workflow",
    }.get(resource_type, resource_type.rstrip("s"))

    async def dependency(request: Request):
        # Only check authorization if it's enabled
        if not getattr(request.state, "authorization_enabled", False):
            return

        # Get the resource_id from path parameters
        resource_id = request.path_params.get(resource_id_param)
        if resource_id and not check_resource_access(request, resource_id, resource_type, action):
            raise HTTPException(status_code=403, detail=f"Access denied to {action} this {resource_singular}")

    return dependency


def require_approval_resolved(db: Any) -> Any:
    """
    Dependency factory that blocks a run continuation when a pending admin-required
    approval exists for the run.

    Designed to sit alongside ``require_resource_access`` in the route's
    ``dependencies`` list.  Pass the OS-level DB adapter at router-creation time
    (the same pattern used by ``get_approval_router``).

    Usage::

        dependencies=[
            Depends(require_resource_access("agents", "run", "agent_id")),
            Depends(require_approval_resolved(os.db)),
        ]
    """

    async def dependency(request: Request) -> None:
        reason = await run_continuation_blocked_reason(
            db,
            request.path_params.get("run_id"),
            authorization_enabled=getattr(request.state, "authorization_enabled", False),
            user_scopes=getattr(request.state, "scopes", []),
        )
        if reason:
            raise HTTPException(status_code=403, detail=reason)

    return dependency


async def run_continuation_blocked_reason(
    db: Any,
    run_id: Optional[str],
    *,
    authorization_enabled: bool,
    user_scopes: List[str],
) -> Optional[str]:
    """Whether a paused run may NOT be continued yet, as a 403 detail string (else None).

    A run paused on an admin-required approval must not be continued by its own initiator;
    only a separate admin (holding ``approvals:write``) may resolve it. This is the single
    decision shared by the REST ``/continue`` routes (via ``require_approval_resolved``) and
    the MCP ``continue_run`` tool, so the gate cannot drift between transports.

    Fails open only for the approval feature itself: if the db has no approvals support the
    check is skipped, so non-approval deployments are unaffected. It never fails open on the
    authorization decision — that is the caller's ``authorization_enabled`` gate.
    """
    # Mirror require_resource_access: skip entirely when authorization is disabled.
    if not authorization_enabled or db is None or not run_id:
        return None

    # Callers with approvals:write (admins) bypass this gate — they can force-continue a
    # run for operational or debugging purposes.
    if has_required_scopes(user_scopes, ["approvals:write"]):
        return None

    fn = getattr(db, "get_approvals", None)
    if fn is None:
        return None

    try:
        if asyncio.iscoroutinefunction(fn):
            result = await fn(run_id=run_id, status="pending", approval_type="required")
        else:
            # Sync DB drivers do blocking I/O; keep it off the event loop, matching the
            # service-account verifier and the service-accounts router.
            result = await run_in_threadpool(fn, run_id=run_id, status="pending", approval_type="required")
        approvals = result[0] if isinstance(result, tuple) else result
        if approvals:
            return "This run requires admin approval before it can be continued"
    except Exception as exc:
        # DB doesn't support approvals or another transient error — let the run continue
        # so non-approval setups are unaffected.
        from agno.utils.log import log_warning

        log_warning(f"Approval resolution check skipped due to error: {exc}")

    return None
