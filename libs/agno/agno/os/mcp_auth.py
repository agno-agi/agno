"""OAuth on the AgentOS MCP endpoint -- the ``mcp_auth`` seam.

``AgentOS(mcp_auth=<fastmcp AuthProvider>)`` hands authentication for the mounted MCP
app to the provider. fastmcp serves the provider's routes (RFC 9728 discovery and, for
an authorization-server provider, ``/authorize``, ``/token``, ``/register``, ``/revoke``)
inside the MCP sub-app -- which AgentOS mounts at root, so they resolve at the public
URLs -- and wraps the MCP path in the SDK's ``RequireAuthMiddleware``, which emits the
``401`` + ``WWW-Authenticate: Bearer resource_metadata="..."`` challenge OAuth clients
(claude.ai, ChatGPT) use for discovery.

agno adds two things on top of the provider:

- **Bearer coexistence**: the provider is composed via fastmcp's ``MultiAuth`` with the
  service-account verifier and, when the deployment has a JWT config, a JWT verifier --
  so existing ``agno_pat_`` bearers (Claude Code, Cursor, the ``agno connect``
  claude-desktop bridge) and agno-JWT bearers keep working on an OAuth-enabled ``/mcp``.
- **The identity bridge**: fastmcp attaches the verified token to the ASGI scope
  (``scope["user"]``), while the MCP tools read ``request.state``. The bridge
  middleware maps one onto the other with the full contract the tool gates need
  (``user_id``, ``scopes``, ``authorization_enabled``, ``admin_scope``). It must run
  INSIDE fastmcp's authentication middleware, so it is passed via
  ``mcp.http_app(middleware=[...])`` -- never ``add_middleware``, which prepends
  outside authentication where no verified token exists yet.
"""

from typing import TYPE_CHECKING, Any, Dict, List, Optional

from agno.os.middleware.jwt import is_reserved_principal as _is_reserved_principal
from agno.utils.log import log_warning

try:
    from fastmcp.server.auth import AccessToken, AuthProvider, MultiAuth, TokenVerifier
except ImportError as e:  # pragma: no cover - exercised only without the extra installed
    raise ImportError(
        "`fastmcp>=3.4.3` is required for `AgentOS(mcp_auth=...)`. "
        "Please install it using `pip install 'fastmcp>=3.4.3'`."
    ) from e

if TYPE_CHECKING:
    from agno.os.app import AgentOS

# Claim stamped on PAT-verified tokens so the identity bridge can restore the
# service-account fields (request.state.service_account_name) the tool gates read.
SERVICE_ACCOUNT_CLAIM = "agno_service_account"

# Claim stamped by the agno-JWT verifier so the bridge mirrors the parent middleware's
# behavior: JWT scopes are enforced only when RBAC is on (state.authorization_enabled =
# os.authorization), while PAT and OAuth-provider scopes are always enforced.
AUTHORIZATION_ENABLED_CLAIM = "agno_authorization_enabled"

# Marks a token minted by a trusted first-party agno source (the built-in AS) so the
# identity bridge permits it to carry a server-assigned reserved principal (``__oauth__:``).
# An external Tier-2 provider's token never carries it, so a reserved ``sub`` from such a
# token is rejected rather than honored (impersonation guard).
INTERNAL_ISSUER_CLAIM = "agno_mcp_internal_issuer"

# The trust markers the identity bridge acts on. They are set ONLY by first-party sources
# (the PAT verifier, the agno-JWT verifier, and the built-in AS) in a controlled claims
# dict. Any of them appearing on a token verified by an external Tier-2 provider -- or
# smuggled through the agno-JWT verifier's payload -- is untrusted and stripped, so the
# markers are trustworthy by construction rather than by where the bridge happens to look.
RESERVED_MARKER_CLAIMS = (SERVICE_ACCOUNT_CLAIM, AUTHORIZATION_ENABLED_CLAIM, INTERNAL_ISSUER_CLAIM)


class ServiceAccountTokenVerifier(TokenVerifier):
    """Verifies ``agno_pat_`` bearers against the AgentOS service-account store.

    The ``MultiAuth`` verifier that keeps PAT clients working when an OAuth provider
    owns the MCP endpoint. Reuses :class:`~agno.os.service_accounts.ServiceAccountVerifier`
    (hashed lookup, cache, failed-lookup throttle, expiry/revocation) and surfaces the
    account as a fastmcp ``AccessToken`` whose claims carry the ``sa:<name>`` principal
    for the identity bridge. Throttled/unavailable lookups verify as ``None`` (a 401):
    ``MultiAuth.verify_token`` has no channel for 429/503.
    """

    def __init__(self, verifier: Any):
        super().__init__()
        self._verifier = verifier

    async def verify_token(self, token: str) -> Optional[AccessToken]:
        from agno.os.service_accounts import TOKEN_PREFIX

        if not token.startswith(TOKEN_PREFIX):
            return None
        result = await self._verifier.verify(token)
        account = getattr(result, "account", None)
        if not result.ok or account is None:
            return None
        return AccessToken(
            token=token,
            client_id=account.principal,
            scopes=list(account.scopes or []),
            # Expiry and revocation are enforced by the verifier on every lookup.
            expires_at=None,
            claims={"sub": account.principal, SERVICE_ACCOUNT_CLAIM: account.name},
        )


class JWTBearerTokenVerifier(TokenVerifier):
    """Verifies agno JWT bearers (the deployment's existing PEM / local-JWKS config).

    The second ``MultiAuth`` verifier: keeps existing agno-JWT clients working when an
    OAuth provider owns the MCP endpoint. Mirrors the parent ``AuthMiddleware``'s JWT
    handling: the same validator and audience constraints, the reserved-principal
    rejection, and the authorization flag (JWT scopes are enforced only when RBAC is
    on, unlike PAT scopes which are first-party ACL data).
    """

    def __init__(
        self,
        validator: Any,
        expected_audience: Any = None,
        authorization: bool = False,
    ) -> None:
        super().__init__()
        self._validator = validator
        # Already resolved (configured audience or the AgentOS id) by the caller via
        # jwt.resolve_expected_audience, so REST and /mcp cannot disagree on it.
        self._expected_audience = expected_audience
        self._authorization = authorization

    async def verify_token(self, token: str) -> Optional[AccessToken]:
        from agno.os.middleware.jwt import is_reserved_principal

        try:
            payload = self._validator.validate_token(token, self._expected_audience)
        except Exception:
            return None
        claims = self._validator.extract_claims(payload)
        user_id = claims.get("user_id")
        if is_reserved_principal(user_id):
            log_warning(f"Rejected JWT claiming a reserved principal on the MCP endpoint: {user_id!r}")
            return None
        # Strip agno's trust markers from the incoming payload before re-asserting the
        # ones this verifier owns (sub, the authorization flag). Otherwise a signature-valid
        # JWT that happens to carry ``agno_service_account`` / ``agno_mcp_internal_issuer``
        # (common when the trusted key is an IdP that reflects user-influenced custom claims)
        # would reach the identity bridge as a first-party trust signal. ``sub`` is set to
        # user_id here and client_id below falls back to "agno-jwt" only as the pydantic-
        # required client_id string -- the bridge keys identity off ``sub``.
        safe_claims = {k: v for k, v in payload.items() if k not in RESERVED_MARKER_CLAIMS}
        return AccessToken(
            token=token,
            client_id=str(user_id) if user_id is not None else "agno-jwt",
            scopes=list(claims.get("scopes") or []),
            expires_at=payload.get("exp"),
            claims={**safe_claims, "sub": user_id, AUTHORIZATION_ENABLED_CLAIM: self._authorization},
        )


class MCPIdentityBridgeMiddleware:
    """Copies the fastmcp-verified identity onto ``request.state`` for the MCP tools.

    The tool gates are fail-open on a missing flag: ``_require_tool_scopes`` and the
    run-continuation gate skip enforcement unless ``request.state.authorization_enabled``
    (or a service-account identity) is present -- so the bridge sets the full contract,
    not just ``user_id``. Unauthenticated requests (the OAuth flow endpoints, the 401
    challenge on the MCP path) pass through untouched.
    """

    def __init__(self, app: Any, admin_scope: Optional[str] = None, user_isolation: bool = False) -> None:
        self.app = app
        self.admin_scope = admin_scope
        self.user_isolation = user_isolation

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if scope["type"] == "http":
            access_token = getattr(scope.get("user"), "access_token", None)
            if access_token is not None:
                claims = getattr(access_token, "claims", None) or {}
                # Fall back to client_id only when the token has no ``sub`` KEY at all
                # (external Tier-2 tokens). The agno-JWT verifier always sets ``sub`` (as
                # None when the JWT has no subject), so a subject-less agno JWT bridges to
                # user_id=None -- exactly as it does on the parent REST AuthMiddleware --
                # instead of collapsing every such caller onto the shared "agno-jwt"
                # client_id principal (which user-isolation would treat as one identity).
                if "sub" in claims:
                    user_id = claims.get("sub")
                else:
                    user_id = getattr(access_token, "client_id", None)
                service_account_name = claims.get(SERVICE_ACCOUNT_CLAIM)
                # A token must not claim a server-reserved principal (sa:/oauth:/scheduler)
                # unless it comes from a trusted first-party source that owns that
                # namespace: the PAT verifier (sa:) or the built-in AS (__oauth__:). An
                # external Tier-2 provider's token carrying such a sub is an impersonation
                # attempt -- leave the identity unset so the fail-closed tool gates deny.
                trusted_internal = service_account_name is not None or bool(claims.get(INTERNAL_ISSUER_CLAIM))
                if not trusted_internal and _is_reserved_principal(user_id):
                    log_warning(f"MCP token claims a reserved principal {user_id!r}; refusing to bridge its identity")
                    await self.app(scope, receive, send)
                    return
                # request.state is backed by scope["state"]; the mounted sub-app and the
                # parent share it, so the tools read these exactly as they do under the
                # parent AuthMiddleware.
                state = scope.setdefault("state", {})
                state["authenticated"] = True
                state["user_id"] = user_id
                state["session_id"] = claims.get("session_id")
                state["scopes"] = list(getattr(access_token, "scopes", None) or [])
                state["authorization_enabled"] = bool(claims.get(AUTHORIZATION_ENABLED_CLAIM, True))
                if self.admin_scope:
                    state["admin_scope"] = self.admin_scope
                state["user_isolation_enabled"] = self.user_isolation
                if service_account_name is not None:
                    state["service_account_name"] = service_account_name
                else:
                    # Parity with the parent JWT path, which exposes the full decoded
                    # claims for factory ctx.trusted.claims (the PAT path does not).
                    state["claims"] = claims
        await self.app(scope, receive, send)


class _MarkerScrubbingProvider(AuthProvider):
    """Wraps an external (Tier-2) ``AuthProvider`` so its verified tokens cannot carry
    agno's internal trust markers into the identity bridge.

    fastmcp providers copy the entire decoded IdP payload into ``AccessToken.claims``. An
    IdP that reflects a user-influenced claim named ``agno_mcp_internal_issuer`` (the
    reserved-principal bypass), ``agno_authorization_enabled`` (the RBAC-off flag), or
    ``agno_service_account`` would otherwise reach the bridge as a first-party trust
    signal. Those markers are legitimately set only by the built-in AS and the PAT/JWT
    verifiers, so this wrapper strips them from any token the external provider verifies.

    Everything else -- routes, discovery metadata, resource URL, required-scope
    enforcement -- is delegated to the wrapped provider unchanged (fastmcp drives auth
    through the composed provider, never branching on its concrete type).
    """

    def __init__(self, wrapped: AuthProvider) -> None:
        object.__setattr__(self, "_wrapped", wrapped)
        super().__init__(
            base_url=getattr(wrapped, "base_url", None),
            required_scopes=getattr(wrapped, "required_scopes", None),
            resource_base_url=getattr(wrapped, "resource_base_url", None),
        )

    async def verify_token(self, token: str) -> Optional[AccessToken]:
        access_token = await self._wrapped.verify_token(token)
        if access_token is None:
            return None
        claims = getattr(access_token, "claims", None) or {}
        # An external provider must not assert a server-reserved principal (sa:/oauth:/
        # __scheduler__). Its token is cryptographically valid, so fastmcp would not 401 it;
        # the identity bridge then refuses to stamp the reserved identity, but the request
        # still reaches the tools as an unauthenticated session -- custom tools run with
        # user_id=None and skip the authorize() allowlist. Reject at verify, mirroring
        # JWTBearerTokenVerifier, so a reserved-principal external token never gets a session.
        # The effective principal is computed exactly as the bridge does (sub, else client_id).
        effective_sub = claims["sub"] if "sub" in claims else getattr(access_token, "client_id", None)
        if _is_reserved_principal(effective_sub):
            log_warning(f"Rejected external MCP token asserting a reserved principal: {effective_sub!r}")
            return None
        if any(marker in claims for marker in RESERVED_MARKER_CLAIMS):
            scrubbed = {k: v for k, v in claims.items() if k not in RESERVED_MARKER_CLAIMS}
            return access_token.model_copy(update={"claims": scrubbed})
        return access_token

    def get_routes(self, mcp_path: Optional[str] = None) -> Any:
        return self._wrapped.get_routes(mcp_path)

    def get_well_known_routes(self, mcp_path: Optional[str] = None) -> Any:
        return self._wrapped.get_well_known_routes(mcp_path)

    def set_mcp_path(self, mcp_path: Optional[str]) -> None:
        self._wrapped.set_mcp_path(mcp_path)

    def __getattr__(self, name: str) -> Any:
        # Reached only for attributes not defined on this wrapper (e.g. authorization_servers,
        # _get_resource_url); delegate them to the wrapped provider. _wrapped itself is set
        # via object.__setattr__ before super().__init__, so it never routes back here.
        if name == "_wrapped":
            raise AttributeError(name)
        return getattr(self._wrapped, name)


def _build_jwt_token_verifier(os: "AgentOS") -> Optional[JWTBearerTokenVerifier]:
    """A verifier for the deployment's existing JWT config, or None when none is configured."""
    from os import getenv

    from agno.os.middleware.jwt import JWTValidator, build_jwt_middleware_kwargs, resolve_expected_audience

    kwargs = build_jwt_middleware_kwargs(
        getattr(os, "authorization_config", None),
        authorization=bool(getattr(os, "authorization", False)),
    )
    jwt_configured = bool(
        kwargs["verification_keys"] or kwargs["jwks_file"] or getenv("JWT_VERIFICATION_KEY") or getenv("JWT_JWKS_FILE")
    )
    if not jwt_configured:
        return None
    validator = JWTValidator(
        verification_keys=kwargs["verification_keys"],
        jwks_file=kwargs["jwks_file"],
        algorithm=kwargs["algorithm"],
    )
    return JWTBearerTokenVerifier(
        validator,
        # Shared with the parent AuthMiddleware and the WS path, so verify_audience with no
        # explicit audience enforces the AgentOS id on /mcp exactly as it does on REST.
        expected_audience=resolve_expected_audience(
            verify_audience=bool(kwargs.get("verify_audience")),
            audience=kwargs.get("audience"),
            os_id=getattr(os, "id", None),
        ),
        authorization=bool(getattr(os, "authorization", False)),
    )


def resolve_mcp_auth(os: "AgentOS") -> Optional[AuthProvider]:
    """Resolve ``AgentOS.mcp_auth`` into the provider handed to ``FastMCP(auth=...)``.

    Composes the provider (``MultiAuth``) with the service-account verifier whenever
    the OS has a db, and with a JWT verifier whenever the deployment has a JWT config,
    so enabling OAuth never breaks the deployment's existing PAT or JWT clients.
    Returns None when ``mcp_auth`` is unset.
    """
    raw = getattr(os, "mcp_auth", None)
    if raw is None:
        return None
    if isinstance(raw, str):
        raise TypeError(
            "mcp_auth takes an AuthProvider object, not a string. For the built-in authorization server "
            "use mcp_auth=AgentOSBuiltinAuth.from_env() (from agno.os), or pass an external provider "
            "(e.g. AuthKitProvider)."
        )
    if not isinstance(raw, AuthProvider):
        raise TypeError(
            f"mcp_auth must be a fastmcp AuthProvider, got {type(raw).__name__!r}. "
            "See fastmcp.server.auth for the available providers, or AgentOSBuiltinAuth for the built-in one."
        )
    # The built-in AS may be constructed without a db (AgentOSBuiltinAuth.from_env());
    # bind the AgentOS-level db so a template can hand it straight to AgentOS. Only the
    # AgentOS db (os.db) is used -- never an agent-attached db, which is that agent's
    # data store, not the platform's OAuth state.
    from agno.os.mcp_auth_builtin import AgentOSBuiltinAuth

    is_builtin = isinstance(raw, AgentOSBuiltinAuth)
    if isinstance(raw, AgentOSBuiltinAuth) and not raw.is_db_bound():
        db = getattr(os, "db", None)
        if db is None:
            raise ValueError(
                "AgentOSBuiltinAuth needs a database: give AgentOS a Postgres db "
                "(AgentOS(db=PostgresDb(...), mcp_auth=AgentOSBuiltinAuth.from_env())), or pass db= to "
                "AgentOSBuiltinAuth directly. It stores clients, codes, and refresh-token state there."
            )
        raw.bind_db(db)
    # An external (Tier-2) provider copies the full decoded IdP payload into
    # AccessToken.claims, so wrap it to strip agno's trust markers -- the built-in AS is
    # first-party and sets them itself, so it is used unwrapped. This holds whether or not
    # the deployment adds first-party verifiers below (the MultiAuth-less return path too).
    server: AuthProvider = raw if is_builtin else _MarkerScrubbingProvider(raw)
    verifiers: List[TokenVerifier] = []
    service_account_verifier = os._get_service_account_verifier()
    if service_account_verifier is not None:
        verifiers.append(ServiceAccountTokenVerifier(service_account_verifier))
    jwt_verifier = _build_jwt_token_verifier(os)
    if jwt_verifier is not None:
        verifiers.append(jwt_verifier)
    if not verifiers:
        return server
    # required_scopes=[] so the route-level RequireAuthMiddleware does not apply the
    # server provider's required_scopes to every verified token: a PAT carries agno
    # resource scopes (config:read, agents:run) and an agno JWT carries deployment scopes,
    # never the provider's OAuth scopes, so inheriting them would 403 those bearers on
    # /mcp. Each provider/verifier still enforces its own required_scopes inside
    # verify_token, and the agno tool gates still enforce agno scopes.
    return MultiAuth(server=server, verifiers=verifiers, required_scopes=[])


def mcp_auth_route_paths(provider: AuthProvider, mcp_path: str = "/mcp") -> List[str]:
    """The public paths the provider serves inside the MCP sub-app, plus the MCP path.

    Used to exempt exactly these paths from the parent ``AuthMiddleware``: browsers and
    connector backends hit them with no agno bearer, and the provider guards them itself
    (PKCE and client auth on the OAuth endpoints, the 401 challenge on the MCP path).
    Exact paths only -- a wildcard here would silently un-authenticate unrelated routes.
    """
    paths = [mcp_path]
    try:
        for route in provider.get_routes(mcp_path=mcp_path):
            path = getattr(route, "path", None)
            if isinstance(path, str) and path not in paths:
                paths.append(path)
    except Exception as e:
        log_warning(f"Could not enumerate mcp_auth provider routes for auth exemptions: {e}")
    return paths


def describe_mcp_auth(provider: AuthProvider, mcp_path: str = "/mcp") -> Dict[str, Any]:
    """Discovery details for ``/info``: the authorization server(s) and the resource URL.

    Best-effort convenience for clients like ``agno connect``; the authoritative
    discovery surface is the provider's own ``/.well-known`` routes.
    """
    server = getattr(provider, "server", None) or provider  # unwrap MultiAuth
    authorization_servers: Optional[List[str]] = None
    raw_servers = getattr(server, "authorization_servers", None)  # RemoteAuthProvider
    if raw_servers:
        authorization_servers = [str(s) for s in raw_servers]
    elif getattr(server, "base_url", None) is not None:  # OAuthProvider is its own AS
        authorization_servers = [str(server.base_url)]
    resource: Optional[str] = None
    try:
        resource_url = server._get_resource_url(mcp_path)
        resource = str(resource_url) if resource_url is not None else None
    except Exception as e:
        log_warning(f"Could not derive the MCP resource URL from the mcp_auth provider: {e}")
    return {"authorization_servers": authorization_servers, "resource": resource}
