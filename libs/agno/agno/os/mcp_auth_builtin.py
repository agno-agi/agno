"""The Built-in Authorization Server for the AgentOS MCP endpoint (Tier 1 of mcp_auth).

``AgentOSBuiltinAuth`` makes a self-deployed AgentOS its own OAuth 2.1 authorization
server, so claude.ai / ChatGPT / Claude Code connect by pasting the ``/mcp`` URL with
zero external accounts -- and the endpoint is never open: every authorization requires
the deployer's connect secret on a login+consent page, over HTTPS.

What the SDK/fastmcp provide vs what lives here:

- The protocol layer is SDK-provided through ``OAuthProvider``: the HTTP endpoints
  (``/authorize``, ``/token``, ``/register``, ``/revoke``, discovery metadata), PKCE
  S256 enforcement, redirect-URI exact-match, and MCP-compliant error codes. Signed
  JWT access/refresh tokens come from fastmcp's ``JWTIssuer`` (HS256) -- verification
  is stateless, so any replica sharing the signing key can verify without a DB hit.
- This module implements the OAuthProvider callbacks against the AgentOS database
  (clients / authorization codes / refresh-token / signing-key state), the login+consent
  page (the single deployer-secret gate -- fastmcp has no login building block), and the
  server-decided scope grant. The persistence itself lives on the db behind the
  ``BaseDb.*_mcp_oauth_*`` contract (schemas in ``agno.db.schemas.mcp_oauth``, shared SQL
  in ``agno.db.mcp_oauth_store``, implemented by the sync SQLAlchemy backends), so the
  namespaced tables are created on first use by the same schema-aware path as every other
  agno table -- this module holds only OAuth protocol logic, not DDL.

Security properties, deliberate and load-bearing:

- **Public clients only.** Connector clients (claude.ai, ChatGPT, Claude Code,
  mcp-remote) register as public clients and prove possession via PKCE. DCR normalizes
  an omitted client-auth method to ``none`` and rejects an explicit confidential method,
  so no client secret is ever minted or stored.
- **Hash-at-rest.** Authorization codes and refresh tokens are stored SHA-256-hashed
  (matching the service-account PAT model); a database read yields nothing replayable.
- **Server-decided scopes.** The grant is a fixed, deployer-configured scope set,
  stamped onto the auth code at mint time -- client-requested DCR/authorize scopes are
  overwritten, not merely validated, so they can never expand it.
- **Single-use, short-lived codes; refresh rotation on every use.** Code exchange and
  refresh rotation are atomic DELETE-then-act, so a replayed code/refresh token fails
  on every replica.
- **The consent page** is served over a secure origin -- the SDK's ``validate_issuer_url``
  rejects a non-HTTPS, non-localhost ``base_url`` at construction, so a plaintext deploy
  cannot be stood up. It renders only for a valid pending authorization transaction,
  compares the secret in constant time, double-submits a CSRF cookie (marked ``Secure``
  on an HTTPS deployment), denies framing, and rate-limits failures per-IP and globally
  (verify-first, so a wrong-secret flood never blocks a correct login).
- **Revocation levers:** rotating the signing key invalidates every token it signed --
  access *and* refresh (both are JWTs under the same key) -- forcing re-consent; deleting
  a refresh-token row stops renewal for that client. Rotating the connect secret gates
  future logins only -- it revokes nothing already issued.
- **Refresh-token reuse detection:** refresh tokens rotate on every use and each carries a
  ``family_id`` shared across its rotation chain. Presenting a token that verifies but has
  no live row (i.e. one already rotated away) is treated as reuse and revokes the whole
  family (OAuth 2.1 / RFC 9700), so a stolen chain and the legitimate client both lose
  access and must re-consent. This bounds silent refresh-token theft without the blunt
  key-rotation kill switch; a stolen access token still lives out its short TTL.
- **Signing key:** env-primary (``AGENTOS_MCP_SIGNING_KEY``). Set it in production so the
  token trust root is env-managed; when unset, a key is generated and persisted in the
  same database (survives redeploy, shared across replicas) -- convenient, but then a
  database read yields the signing material. Keys support a rotation overlap: the newest
  signs, any active key verifies.
"""

import hashlib
import hmac
import html
import json
import secrets
import threading
import time
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple

from agno.utils.log import log_debug, log_info, log_warning

try:
    from fastmcp.server.auth import AccessToken
    from fastmcp.server.auth.auth import ClientRegistrationOptions, OAuthProvider, RevocationOptions
    from fastmcp.server.auth.jwt_issuer import JWTIssuer, derive_jwt_key
    from mcp.server.auth.provider import (
        AuthorizationCode,
        AuthorizationParams,
        RefreshToken,
        RegistrationError,
        TokenError,
        construct_redirect_uri,
    )
    from mcp.shared.auth import OAuthClientInformationFull, OAuthToken
except ImportError as e:  # pragma: no cover - exercised only without the extra installed
    raise ImportError(
        "`fastmcp>=3.4.3` is required for the built-in MCP authorization server. "
        "Please install it using `pip install 'fastmcp>=3.4.3'`."
    ) from e

if TYPE_CHECKING:
    from starlette.requests import Request
    from starlette.routing import Route

# Server-decided grant for the single deployer principal: run + read, mirroring the
# default service-account scopes. Anything broader (admin) requires explicit config.
DEFAULT_GRANT_SCOPES: List[str] = [
    "agents:run",
    "teams:run",
    "workflows:run",
    "sessions:read",
    "config:read",
]

DEFAULT_ACCESS_TOKEN_TTL = 60 * 60  # 1 hour
DEFAULT_REFRESH_TOKEN_TTL = 30 * 24 * 60 * 60  # 30 days, rotated on every use
DEFAULT_AUTH_CODE_TTL = 5 * 60  # single-use, 5 minutes
DEFAULT_TRANSACTION_TTL = 10 * 60  # login page validity window
DEFAULT_MAX_CLIENTS = 1000  # cap on PENDING (unconsummated) DCR registrations
DEFAULT_MAX_PENDING_TRANSACTIONS = 2000  # cap on pending /authorize transactions
# Unconsummated registrations expire fast: a real connector completes register -> consent
# within minutes, so a short TTL shrinks the window an unauthenticated /register flood
# could fill the pending cap and delay new-client onboarding.
DEFAULT_UNCONSUMED_CLIENT_TTL = 60 * 60

# Minimum lengths enforced at construction. The connect secret is the sole gate on the
# consent page and the signing key is the HS256 root for every issued token, so both must
# have real length -- a passphrase-strength value for either is a footgun.
MIN_CONNECT_SECRET_LENGTH = 16
MIN_SIGNING_KEY_LENGTH = 32

# The login/consent surface, served by this provider inside the MCP sub-app (and so
# automatically exempted from the parent AuthMiddleware with the other provider routes).
CONSENT_PATH = "/mcp-auth/consent"

_CSRF_COOKIE = "agno_mcp_consent"

# user_id namespace for OAuth-connected clients; distinct from sa:<name> and JWT subs.
# Single source of truth in middleware.jwt so this minting and the reserved-principal
# guard can never drift (a drift would let a human JWT impersonate a connected client).
from agno.os.mcp_auth import INTERNAL_ISSUER_CLAIM  # noqa: E402
from agno.os.middleware.jwt import MCP_OAUTH_PRINCIPAL_PREFIX as _PRINCIPAL_PREFIX  # noqa: E402


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _constant_time_equals(a: str, b: str) -> bool:
    # Compare digests, not the raw strings, so length is not observable.
    return hmac.compare_digest(_hash(a), _hash(b))


def _is_loopback_host(host: Optional[str]) -> bool:
    return host is not None and host.lower() in {"localhost", "127.0.0.1", "::1"}


def _redirect_uri_matches_registered(requested: Any, registered: Any) -> bool:
    """Whether ``requested`` matches a registered redirect URI: exact, or -- for a
    registered loopback URI (RFC 8252) -- identical in everything but the port.

    Reimplemented locally (rather than importing fastmcp's private
    ``_matches_registered_redirect_uri``) so redirect validation -- a security control --
    owns its logic and cannot break on an upstream rename/removal or drift silently.
    """
    from urllib.parse import urlparse

    if str(requested) == str(registered):
        return True
    req = urlparse(str(requested))
    reg = urlparse(str(registered))
    # Never let credentials in the URI participate in matching.
    if req.username or req.password or reg.username or reg.password:
        return False
    req_host = req.hostname.lower() if req.hostname else None
    reg_host = reg.hostname.lower() if reg.hostname else None
    if not _is_loopback_host(reg_host) or req_host != reg_host:
        return False
    # Loopback: only the port may vary; scheme/path/params/query/fragment must be identical.
    return (
        req.scheme.lower() == reg.scheme.lower()
        and (req.path or "/") == (reg.path or "/")
        and req.params == reg.params
        and req.query == reg.query
        and req.fragment == reg.fragment
    )


class _LoopbackTolerantClient(OAuthClientInformationFull):
    """A DCR client that permits a registered loopback redirect URI to vary its port.

    RFC 8252: native CLI clients (Claude Code, mcp-remote) register a client_id, then on
    a later authorization bind a fresh ephemeral callback port. Exact-match validation
    would reject the second run with "redirect_uri not registered". Non-loopback URIs
    (claude.ai, ChatGPT) keep exact matching, and a non-registered redirect is refused by
    the base class's strict validation below.
    """

    def validate_redirect_uri(self, redirect_uri: Any) -> Any:
        if redirect_uri is not None and self.redirect_uris:
            if any(_redirect_uri_matches_registered(redirect_uri, r) for r in self.redirect_uris):
                return redirect_uri
        return super().validate_redirect_uri(redirect_uri)


class AgentOSBuiltinAuth(OAuthProvider):
    """A self-hosted OAuth 2.1 authorization server backed by the AgentOS database.

    Args:
        url: The deployment's public origin (e.g. ``https://my-os.up.railway.app``), the
            value of ``AGENTOS_URL``. Every advertised OAuth metadata URL derives from it
            -- it must be exact.
        secret: The deployer secret typed on the consent page (``MCP_CONNECT_SECRET``).
            Use a dedicated secret, not a root credential.
        db: The AgentOS database (``PostgresDb`` in production; ``SqliteDb`` is accepted
            for development with a warning). Optional -- when omitted, AgentOS binds its
            own db. Stores clients, pending authorizations, single-use code hashes, and
            refresh-token state.
        scopes: The server-decided grant for every connected client (default: the
            run+read connector set). Client-requested scopes can never expand this.
        access_token_ttl / refresh_token_ttl / auth_code_ttl: Token lifetimes in
            seconds. Refresh tokens rotate on every use.
        signing_key_material: High-entropy material for the HS256 signing key
            (``AGENTOS_MCP_SIGNING_KEY``). When omitted, a key is generated once and
            persisted in the database so it survives redeploys and is shared across
            replicas. Rotating the key invalidates all outstanding access tokens.
        server_name: Display name on the consent page (defaults to the AgentOS name).
    """

    def __init__(
        self,
        *,
        url: str,
        secret: str,
        db: Any = None,
        scopes: Optional[List[str]] = None,
        access_token_ttl: int = DEFAULT_ACCESS_TOKEN_TTL,
        refresh_token_ttl: int = DEFAULT_REFRESH_TOKEN_TTL,
        auth_code_ttl: int = DEFAULT_AUTH_CODE_TTL,
        signing_key_material: Optional[str] = None,
        server_name: Optional[str] = None,
        max_clients: int = DEFAULT_MAX_CLIENTS,
        max_login_failures_per_ip: int = 10,
        max_login_failures_global: int = 100,
        enable_cimd: bool = True,
    ):
        super().__init__(
            base_url=url,
            client_registration_options=ClientRegistrationOptions(enabled=True),
            revocation_options=RevocationOptions(enabled=True),
        )
        if not secret:
            raise ValueError(
                "AgentOSBuiltinAuth requires a secret: set MCP_CONNECT_SECRET (or pass secret=). "
                "It is the login credential on the consent page -- use a dedicated secret, not a "
                "root credential."
            )
        if len(secret) < MIN_CONNECT_SECRET_LENGTH:
            raise ValueError(
                f"AgentOSBuiltinAuth secret is too short ({len(secret)} chars): it is the only gate on "
                f"the consent page, so it must be at least {MIN_CONNECT_SECRET_LENGTH} characters. "
                "Generate a strong one, e.g. `openssl rand -base64 32`."
            )
        # AGENTOS_MCP_SIGNING_KEY is fed to fastmcp's derive_jwt_key as high-entropy
        # material (a single HKDF pass, no stretching), so a low-entropy value is
        # offline-brute-forceable from any token a client holds. Require real length --
        # a passphrase like "connect-me" must be rejected, not silently accepted as an
        # HS256 root. (When unset, a strong key is generated and persisted instead.)
        if signing_key_material is not None and len(signing_key_material) < MIN_SIGNING_KEY_LENGTH:
            raise ValueError(
                f"AGENTOS_MCP_SIGNING_KEY is too short ({len(signing_key_material)} chars): it is the "
                f"HS256 signing root for every issued token and must be at least {MIN_SIGNING_KEY_LENGTH} "
                "high-entropy characters. Generate one with `openssl rand -base64 32`, or leave it unset "
                "to have a strong key generated and persisted for you."
            )
        # db may be bound now (explicit) or later by AgentOS (``bind_db``), so passing
        # AgentOSBuiltinAuth.from_env() to AgentOS(db=...) just works -- the store binds to
        # the AgentOS Postgres db without threading it through here. The token store lives
        # on the db (BaseDb.*_mcp_oauth_* methods, implemented by the sync SQLAlchemy
        # backends); every store call goes through _ensure_ready(), which raises when the
        # db is unbound, so the delegations downstream never see None.
        if db is not None:
            self._validate_db(db)
        self._db = db
        self._secret = secret
        self._grant_scopes = list(scopes) if scopes is not None else list(DEFAULT_GRANT_SCOPES)
        self._access_token_ttl = access_token_ttl
        self._refresh_token_ttl = refresh_token_ttl
        self._auth_code_ttl = auth_code_ttl
        self._signing_key_material = signing_key_material
        self._server_name = server_name
        self._max_clients = max_clients
        self._max_pending_transactions = DEFAULT_MAX_PENDING_TRANSACTIONS
        # Verifiers, newest first: the current key issues, and any of the persisted
        # keys can verify -- so rotation is add-new-key, let old tokens drain, then
        # remove the old key (a graceful dual-key overlap rather than a hard cut).
        self._issuers: List[Tuple[str, JWTIssuer]] = []
        self._issuers_ready = False
        # Guards the one-time signing-key load against concurrent first requests.
        self._ready_lock = threading.Lock()

        from agno.os.service_accounts import _FailedLookupLimiter

        self._ip_limiter = _FailedLookupLimiter(max_failures=max_login_failures_per_ip, window_seconds=60)
        self._global_limiter = _FailedLookupLimiter(max_failures=max_login_failures_global, window_seconds=60)

        # CIMD (Client ID Metadata Documents): URL client ids resolved by fetching the
        # client's published metadata -- ChatGPT's preferred registration mechanism and
        # the recommended one since the 2025-11-25 MCP revision. DCR stays on for
        # clients that register instead (claude.ai, Claude Code, mcp-remote).
        self._cimd_manager: Optional[Any] = None
        if enable_cimd:
            from fastmcp.server.auth.cimd import CIMDClientManager

            self._cimd_manager = CIMDClientManager(enable_cimd=True, default_scope=" ".join(self._grant_scopes))

    @classmethod
    def from_env(cls, db: Any = None, server_name: Optional[str] = None) -> "AgentOSBuiltinAuth":
        """Build from the deployment environment: ``AGENTOS_URL`` (the public
        origin), ``MCP_CONNECT_SECRET`` (the login secret), and optionally
        ``AGENTOS_MCP_SIGNING_KEY`` (env-primary signing key material).

        The Postgres db is optional here: pass ``AgentOSBuiltinAuth.from_env()`` straight
        to ``AgentOS(db=..., mcp_auth=...)`` and it binds to the AgentOS db.
        """
        from os import getenv

        url = getenv("AGENTOS_URL")
        if not url:
            raise ValueError(
                "AgentOSBuiltinAuth.from_env() requires AGENTOS_URL: the deployment's public "
                "origin (e.g. https://my-os.up.railway.app). Every advertised OAuth metadata URL derives "
                "from it. (Pass url=... to construct it directly instead.)"
            )
        secret = getenv("MCP_CONNECT_SECRET")
        if not secret:
            raise ValueError(
                "AgentOSBuiltinAuth.from_env() requires MCP_CONNECT_SECRET: the deployer secret typed on "
                "the consent page when a client connects. Generate a strong one, e.g. `openssl rand -base64 32`."
            )
        return cls(
            url=url,
            db=db,
            secret=secret,
            signing_key_material=getenv("AGENTOS_MCP_SIGNING_KEY"),
            server_name=server_name,
        )

    def is_db_bound(self) -> bool:
        """Whether a database is attached (either passed to the constructor or bound
        later by AgentOS)."""
        return self._db is not None

    def bind_db(self, db: Any) -> None:
        """Attach the AgentOS database if one was not passed to the constructor.

        A db passed explicitly wins -- this only binds when unbound, so
        ``AgentOSBuiltinAuth.from_env()`` handed to ``AgentOS(db=...)`` picks up the
        AgentOS db, while an explicit ``AgentOSBuiltinAuth(db=other)`` is left alone.
        """
        if self._db is not None:
            return
        self._validate_db(db)
        self._db = db

    # ==================== Storage ====================

    @staticmethod
    def _validate_db(db: Any) -> None:
        """Fail fast (at construction/bind) unless the db can back the OAuth store.

        The store is served through the ``BaseDb.*_mcp_oauth_*`` methods, which only the
        sync SQLAlchemy backends implement. Gate on a synchronous ``db_engine`` so a
        non-SQLAlchemy db (Mongo/Dynamo -> NotImplementedError) or an async adapter
        (AsyncPostgresDb / AsyncSqliteDb, whose AsyncEngine the sync store cannot drive)
        is rejected here rather than with an opaque error mid-OAuth-flow.
        """
        engine = getattr(db, "db_engine", None)
        if engine is None:
            raise ValueError(
                f"AgentOSBuiltinAuth requires a SQLAlchemy-backed database (PostgresDb in production); "
                f"got {type(db).__name__}."
            )
        from sqlalchemy.ext.asyncio import AsyncEngine

        if isinstance(engine, AsyncEngine):
            raise ValueError(
                f"AgentOSBuiltinAuth does not support async databases yet ({type(db).__name__}); "
                "pass a synchronous PostgresDb (production) or SqliteDb (development)."
            )
        if engine.dialect.name == "sqlite":
            log_warning(
                "AgentOSBuiltinAuth is running on SQLite -- fine for development, but production "
                "deployments should use PostgresDb (restart-safe and shared across replicas)."
            )
        # A sync db_engine is necessary but not sufficient: other SQLAlchemy backends
        # (MySQLDb, SingleStoreDb, ...) expose one but do NOT override the BaseDb OAuth
        # store methods, so they would pass the checks above and then 500 with
        # NotImplementedError on the first /register. Confirm the store is actually
        # implemented (only PostgresDb / SqliteDb do today) and fail fast here instead.
        from agno.db.base import BaseDb

        if getattr(type(db), "create_mcp_oauth_client", None) is BaseDb.create_mcp_oauth_client:
            raise ValueError(
                f"{type(db).__name__} does not implement the built-in MCP OAuth store (the "
                "BaseDb.*_mcp_oauth_* methods). It is currently provided only by PostgresDb and SqliteDb; "
                "use one of those for AgentOSBuiltinAuth."
            )

    def _require_db(self) -> Any:
        """The bound db, or a clear error. The store methods route through this."""
        if self._db is None:
            raise ValueError(
                "AgentOSBuiltinAuth has no database bound: pass db= when constructing it, or attach it "
                "to an AgentOS with a Postgres db (AgentOS(db=PostgresDb(...), mcp_auth=...)). It stores "
                "clients, authorization codes, and refresh-token state there."
            )
        return self._db

    def _ensure_ready(self) -> None:
        """Load the signing key(s) once. The token-store tables are created on first use
        by the db layer's normal schema-aware path (BaseDb._get_table), so nothing here
        touches DDL -- this only loads/generates the signing keys.

        Locked so concurrent first requests do not double-load (or double-generate) keys.
        Idempotent after the first call.
        """
        if self._issuers_ready:
            return
        self._require_db()
        with self._ready_lock:
            if self._issuers_ready:
                return
            self._issuers = self._load_issuers()
            self._issuers_ready = True

    def _build_issuer(self, material: str, kid: str) -> Tuple[str, "JWTIssuer"]:
        salt = str(self.base_url).rstrip("/")
        issuer = JWTIssuer(
            issuer=salt,
            audience=str(self._get_resource_url(self._mcp_path or "/mcp")),
            signing_key=derive_jwt_key(high_entropy_material=material, salt=salt),
        )
        return kid, issuer

    def _load_issuers(self) -> List[Tuple[str, "JWTIssuer"]]:
        """The signing key(s): newest first. The newest issues; any verifies.

        Env-primary: AGENTOS_MCP_SIGNING_KEY is always the current issuer. Persisted
        keys in ``agno_mcp_oauth_keys`` provide the rotation overlap -- add a new row (or
        set the env key), let tokens signed by the old key drain within their TTL, then
        delete the old row. Rotating away from a key invalidates the access tokens it
        signed (the revocation lever); deleting all keys is a full reset.

        When neither env nor a persisted key exists, one is generated and persisted so
        tokens survive a redeploy and verify across replicas.
        """
        db = self._require_db()

        issuers: List[Tuple[str, JWTIssuer]] = []
        if self._signing_key_material:
            issuers.append(self._build_issuer(self._signing_key_material, "env"))

        rows = db.get_mcp_oauth_keys()
        if not rows and not issuers:
            material = secrets.token_urlsafe(48)
            if db.insert_mcp_oauth_key(kid="default", secret=material, created_at=int(time.time())):
                log_info(
                    "Generated and persisted the built-in MCP OAuth signing key. For production, set "
                    "AGENTOS_MCP_SIGNING_KEY so the token trust root is env-managed, not stored in the database."
                )
                rows = [("default", material)]
            else:
                # Another replica won the cold-start race and inserted first; use its key.
                rows = db.get_mcp_oauth_keys()
        for kid, material in rows:
            issuers.append(self._build_issuer(material, kid))
        return issuers

    @property
    def _issuer(self) -> "JWTIssuer":
        """The current issuer -- the one that signs newly minted tokens."""
        return self._issuers[0][1]

    def _verify_any(self, token: str, expected_token_use: str) -> Optional[Dict[str, Any]]:
        """Verify against any active signing key (the dual-key rotation overlap)."""
        for _, issuer in self._issuers:
            try:
                return issuer.verify_token(token, expected_token_use=expected_token_use)
            except Exception:
                continue
        return None

    async def _run(self, fn: Any, *args: Any) -> Any:
        """Run a sync DB operation without blocking the event loop."""
        from starlette.concurrency import run_in_threadpool

        return await run_in_threadpool(fn, *args)

    # ==================== Client store (DCR) ====================

    async def get_client(self, client_id: str) -> Optional[OAuthClientInformationFull]:
        # CIMD clients identify by URL and publish their own metadata -- nothing is
        # stored; the manager fetches and validates the document.
        if self._cimd_manager is not None and self._cimd_manager.is_cimd_client_id(client_id):
            return await self._cimd_manager.get_client(client_id)
        return await self._run(self._get_client_sync, client_id)

    def _get_client_sync(self, client_id: str) -> Optional[OAuthClientInformationFull]:
        metadata = self._require_db().get_mcp_oauth_client(client_id)
        if metadata is None:
            return None
        # Return a client whose redirect-URI validation allows a registered loopback
        # host to vary its port (RFC 8252) -- Claude Code / mcp-remote persist their
        # client_id and bind a fresh ephemeral callback port on a later auth run.
        return _LoopbackTolerantClient.model_validate(json.loads(metadata))

    async def register_client(self, client_info: OAuthClientInformationFull) -> None:
        # Public clients only: connector clients (claude.ai, ChatGPT, Claude Code,
        # mcp-remote) prove possession via PKCE. Refusing confidential registrations
        # means no client secret is ever stored.
        if client_info.token_endpoint_auth_method != "none":
            raise RegistrationError(
                error="invalid_client_metadata",
                error_description=(
                    "This authorization server supports public clients only: register with "
                    'token_endpoint_auth_method "none" and use PKCE.'
                ),
            )
        if client_info.client_id is None:
            raise RegistrationError(error="invalid_client_metadata", error_description="client_id is required")
        await self._run(self._register_client_sync, client_info)

    def _register_client_sync(self, client_info: OAuthClientInformationFull) -> None:
        # The store expires unconsummated registrations (the /register flood vector) and
        # caps only unconsumed rows, so a run of deployer-approved (consumed) connections
        # can never wedge /register. A False return means that cap was reached.
        inserted = self._require_db().create_mcp_oauth_client(
            client_id=client_info.client_id,
            client_metadata=client_info.model_dump_json(),
            now=int(time.time()),
            unconsumed_ttl=DEFAULT_UNCONSUMED_CLIENT_TTL,
            max_clients=self._max_clients,
        )
        if not inserted:
            raise RegistrationError(
                error="invalid_client_metadata",
                error_description="Too many pending client registrations on this server; try again later.",
            )
        log_debug(f"Registered MCP OAuth client {client_info.client_id}")

    # ==================== Authorization (the consent gate) ====================

    async def authorize(self, client: OAuthClientInformationFull, params: AuthorizationParams) -> str:
        """Store a pending authorization and send the browser to the consent page.

        Nothing is granted here: the code is minted only after the deployer secret is
        verified on the consent POST. The transaction pins everything the grant will
        use (client, redirect URI, PKCE challenge) so the consent POST cannot alter it.
        """
        txn_id = secrets.token_urlsafe(32)
        payload = {
            "client_id": client.client_id,
            "redirect_uri": str(params.redirect_uri),
            "redirect_uri_provided_explicitly": params.redirect_uri_provided_explicitly,
            "code_challenge": params.code_challenge,
            "state": params.state,
            "resource": params.resource,
        }
        await self._run(self._store_transaction_sync, txn_id, client.client_id, payload)
        return f"{str(self.base_url).rstrip('/')}{CONSENT_PATH}?txn={txn_id}"

    def _store_transaction_sync(self, txn_id: str, client_id: str, payload: Dict[str, Any]) -> None:
        now = int(time.time())
        self._require_db().store_mcp_oauth_transaction(
            txn_id=txn_id,
            client_id=client_id,
            params=json.dumps(payload),
            expires_at=now + DEFAULT_TRANSACTION_TTL,
            now=now,
            max_pending=self._max_pending_transactions,
        )

    def _load_transaction_sync(self, txn_id: str) -> Optional[Dict[str, Any]]:
        row = self._require_db().get_mcp_oauth_transaction(txn_id)
        if row is None or row[1] < int(time.time()):
            return None
        return json.loads(row[0])

    def _consume_transaction_sync(self, txn_id: str) -> Optional[Dict[str, Any]]:
        """Atomically claim the transaction: the DELETE succeeds on exactly one replica."""
        row = self._require_db().consume_mcp_oauth_transaction(txn_id, int(time.time()))
        if row is None:
            return None
        return json.loads(row[0])

    def _mark_client_consumed_sync(self, client_id: str) -> None:
        self._require_db().mark_mcp_oauth_client_consumed(client_id, int(time.time()))

    # ==================== The consent page ====================

    def get_routes(self, mcp_path: Optional[str] = None) -> "List[Route]":
        from starlette.routing import Route

        routes = super().get_routes(mcp_path)
        from mcp.server.auth.routes import cors_middleware
        from starlette.routing import Route as StarletteRoute

        rebuilt: List[Route] = []
        for route in routes:
            is_post = isinstance(route, StarletteRoute) and route.methods and "POST" in route.methods
            if is_post and route.path == "/register":
                # Normalize DCR registrations to public clients: the SDK handler defaults
                # an OMITTED token_endpoint_auth_method to client_secret_post and mints a
                # secret before the provider sees it, which would reject any DCR connector
                # (Claude Code, mcp-remote) that does not send "none" verbatim. Force
                # "none" for an omitted method; reject only an explicit confidential one.
                rebuilt.append(
                    Route(
                        "/register",
                        endpoint=cors_middleware(self._register_public, ["POST", "OPTIONS"]),
                        methods=["POST", "OPTIONS"],
                    )
                )
            elif is_post and route.path == "/token" and self._cimd_manager is not None:
                # Swap the token endpoint's authenticator for one that also accepts
                # private_key_jwt assertions from CIMD clients (RFC 7523); standard
                # methods (none/PKCE) delegate to the SDK unchanged.
                from fastmcp.server.auth.auth import PrivateKeyJWTClientAuthenticator, TokenHandler

                authenticator = PrivateKeyJWTClientAuthenticator(
                    provider=self,
                    cimd_manager=self._cimd_manager,
                    token_endpoint_url=f"{str(self.base_url).rstrip('/')}/token",
                )
                handler = TokenHandler(provider=self, client_authenticator=authenticator)
                rebuilt.append(
                    Route(
                        "/token",
                        endpoint=cors_middleware(handler.handle, ["POST", "OPTIONS"]),
                        methods=["POST", "OPTIONS"],
                    )
                )
            elif isinstance(route, StarletteRoute) and route.path.startswith("/.well-known/oauth-authorization-server"):
                rebuilt.append(self._public_metadata_route(route, cors_middleware))
            else:
                rebuilt.append(route)
        routes = rebuilt
        routes.append(Route(CONSENT_PATH, endpoint=self._consent_get, methods=["GET"]))
        routes.append(Route(CONSENT_PATH, endpoint=self._consent_post, methods=["POST"]))
        return routes

    def _public_metadata_route(self, route: Any, cors_middleware: Any) -> Any:
        """Rebuild the authorization-server metadata route to advertise the client-auth
        methods this server actually accepts.

        The SDK's ``build_metadata`` hardcodes ``token_endpoint_auth_methods_supported`` to
        the confidential methods (``client_secret_post`` / ``client_secret_basic``), but
        this AS is public-clients-only and REJECTS those at ``/register``. A spec-strict
        connector (claude.ai) reads the metadata, registers with a confidential method,
        and gets a 400 -- surfacing as "Couldn't register with the sign-in service".
        Advertise ``none`` (public + PKCE) instead -- plus ``private_key_jwt`` when CIMD is
        enabled -- so DCR picks the path the server accepts. Revocation is public too.
        """
        from mcp.server.auth.handlers.metadata import MetadataHandler
        from mcp.server.auth.routes import build_metadata
        from starlette.routing import Route

        if self.base_url is None:
            # Unreachable: the SDK requires a valid issuer URL at construction, so the
            # metadata route only exists when base_url is set. Guard for the type checker.
            return route
        metadata = build_metadata(
            self.base_url,
            self.service_documentation_url,
            self.client_registration_options or ClientRegistrationOptions(enabled=True),
            self.revocation_options or RevocationOptions(enabled=True),
        )
        methods = ["none"] + (["private_key_jwt"] if self._cimd_manager is not None else [])
        metadata.token_endpoint_auth_methods_supported = methods
        if metadata.revocation_endpoint is not None:
            metadata.revocation_endpoint_auth_methods_supported = ["none"]
        if self._cimd_manager is not None:
            metadata.client_id_metadata_document_supported = True
        handler = MetadataHandler(metadata)
        return Route(
            route.path,
            endpoint=cors_middleware(handler.handle, ["GET", "OPTIONS"]),
            methods=route.methods or ["GET", "OPTIONS"],
            name=route.name,
            include_in_schema=route.include_in_schema,
        )

    async def _register_public(self, request: "Request") -> Any:
        """DCR that treats an omitted client-auth method as a public (PKCE) client.

        Rejects only a client that EXPLICITLY asks for a confidential method (so no
        client secret is ever minted or stored), then delegates the remaining RFC 7591
        validation and storage to the SDK's ``RegistrationHandler`` with the method
        pinned to ``none``.
        """
        from mcp.server.auth.handlers.register import RegistrationErrorResponse, RegistrationHandler
        from mcp.server.auth.json_response import PydanticJSONResponse
        from starlette.requests import Request as StarletteRequest

        try:
            body = await request.json()
        except Exception:
            body = {}
        if isinstance(body, dict):
            method = body.get("token_endpoint_auth_method")
            if method is not None and method != "none":
                return PydanticJSONResponse(
                    content=RegistrationErrorResponse(
                        error="invalid_client_metadata",
                        error_description=(
                            "This authorization server supports public clients only: register with "
                            'token_endpoint_auth_method "none" and use PKCE.'
                        ),
                    ),
                    status_code=400,
                )
            body["token_endpoint_auth_method"] = "none"

        raw = json.dumps(body).encode()

        async def receive() -> Dict[str, Any]:
            return {"type": "http.request", "body": raw, "more_body": False}

        normalized = StarletteRequest(request.scope, receive)
        options = self.client_registration_options or ClientRegistrationOptions(enabled=True)
        handler = RegistrationHandler(provider=self, options=options)
        return await handler.handle(normalized)

    def _consent_headers(self) -> Dict[str, str]:
        return {
            # The page carries a secret input: never framed, never cached. NOTE: no
            # `form-action` directive -- Chromium enforces form-action on the redirect that
            # FOLLOWS the form POST, so `form-action 'self'` would silently block the
            # post-approval 302 to the client's cross-origin callback (claude.ai / ChatGPT),
            # stranding the flow before the token exchange. The page runs no JS
            # (`default-src 'none'`, no script-src), so the form cannot be hijacked and
            # form-action adds no protection here.
            "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; frame-ancestors 'none'",
            "X-Frame-Options": "DENY",
            "Cache-Control": "no-store",
            "Referrer-Policy": "no-referrer",
        }

    def _client_display_name_sync(self, client_id: str) -> str:
        client = self._get_client_sync(client_id)
        return (getattr(client, "client_name", None) or client_id) if client else client_id

    async def _display_name(self, client_id: str) -> str:
        if self._cimd_manager is not None and self._cimd_manager.is_cimd_client_id(client_id):
            try:
                client = await self._cimd_manager.get_client(client_id)
                if client is not None:
                    return getattr(client, "client_name", None) or client_id
            except Exception:
                return client_id
        return await self._run(self._client_display_name_sync, client_id)

    def _deployment_is_https(self) -> bool:
        """Whether the deployment's public origin is HTTPS.

        The MCP SDK already guarantees the consent page is served over a secure origin:
        ``create_auth_routes`` rejects any ``base_url`` that is not HTTPS or localhost at
        construction (``validate_issuer_url``), so a plaintext non-localhost built-in AS
        cannot be stood up. This derives the CSRF cookie's ``Secure`` flag from that same
        deployer-declared origin -- correct behind a TLS-terminating proxy (Railway/PaaS),
        where the app sees plain http from the edge though the user's connection is https,
        and off for a localhost http dev flow (where a Secure cookie would not be sent).
        """
        return str(self.base_url).lower().startswith("https")

    def _render_consent_page(
        self,
        txn_id: str,
        payload: Dict[str, Any],
        client_name: str,
        error: Optional[str] = None,
        secure_cookie: bool = True,
    ) -> Any:
        from starlette.responses import HTMLResponse

        csrf_token = secrets.token_urlsafe(24)
        scopes_html = "".join(f"<li><code>{html.escape(s)}</code></li>" for s in self._grant_scopes)
        error_html = f'<p class="error">{html.escape(error)}</p>' if error else ""
        server_name = html.escape(self._server_name or "AgentOS")
        body = f"""<!doctype html>
<html><head><meta charset="utf-8"><title>Connect to {server_name}</title>
<style>
body {{ font-family: -apple-system, system-ui, sans-serif; background: #f5f5f5; display: flex; justify-content: center; padding-top: 8vh; }}
.card {{ background: #fff; border-radius: 12px; box-shadow: 0 2px 12px rgba(0,0,0,.08); padding: 2rem; max-width: 26rem; }}
h1 {{ font-size: 1.15rem; }} code {{ background: #f0f0f0; padding: 1px 5px; border-radius: 4px; }}
.uri {{ background: #fff8e1; border-radius: 6px; padding: .5rem; word-break: break-all; font-size: .85rem; }}
input[type=password] {{ width: 100%; padding: .5rem; margin: .75rem 0; box-sizing: border-box; }}
button {{ padding: .5rem 1.25rem; border-radius: 6px; border: 0; cursor: pointer; }}
.approve {{ background: #111; color: #fff; }} .deny {{ background: #eee; }}
.error {{ color: #b00020; }}
</style></head><body><div class="card">
<h1>Connect <strong>{html.escape(str(client_name))}</strong> to {server_name}</h1>
<p>The application is requesting access with:</p>
<ul>{scopes_html}</ul>
<p>Credentials will be sent to:</p>
<div class="uri">{html.escape(payload["redirect_uri"])}</div>
{error_html}
<form method="post" action="{CONSENT_PATH}">
<input type="hidden" name="txn" value="{html.escape(txn_id)}">
<input type="hidden" name="csrf" value="{html.escape(csrf_token)}">
<label>Connect secret<input type="password" name="secret" autocomplete="off" autofocus></label>
<button class="approve" type="submit" name="action" value="approve">Approve</button>
<button class="deny" type="submit" name="action" value="deny">Deny</button>
</form></div></body></html>"""
        response = HTMLResponse(body, headers=self._consent_headers())
        response.set_cookie(
            _CSRF_COOKIE,
            csrf_token,
            max_age=DEFAULT_TRANSACTION_TTL,
            httponly=True,
            samesite="lax",
            secure=secure_cookie,
            path=CONSENT_PATH,
        )
        return response

    async def _consent_get(self, request: "Request") -> Any:
        from starlette.responses import HTMLResponse

        txn_id = request.query_params.get("txn", "")
        payload = await self._run(self._load_transaction_sync, txn_id)
        if payload is None:
            # Only a valid pending authorization renders the secret form.
            return HTMLResponse(
                "<h1>Authorization request not found or expired.</h1>Restart the connection from your client.",
                status_code=404,
                headers=self._consent_headers(),
            )
        client_name = await self._display_name(payload["client_id"])
        return self._render_consent_page(txn_id, payload, client_name, secure_cookie=self._deployment_is_https())

    async def _consent_post(self, request: "Request") -> Any:
        from starlette.responses import HTMLResponse, RedirectResponse

        secure_cookie = self._deployment_is_https()
        form = await request.form()
        txn_id = str(form.get("txn", ""))
        payload = await self._run(self._load_transaction_sync, txn_id)
        if payload is None:
            return HTMLResponse(
                "<h1>Authorization request not found or expired.</h1>",
                status_code=404,
                headers=self._consent_headers(),
            )

        # CSRF double-submit: the form field must match the cookie set with the page.
        csrf_form = str(form.get("csrf", ""))
        csrf_cookie = request.cookies.get(_CSRF_COOKIE, "")
        if not csrf_form or not csrf_cookie or not _constant_time_equals(csrf_form, csrf_cookie):
            log_warning("MCP consent POST rejected: CSRF token mismatch")
            return HTMLResponse("<h1>Invalid request.</h1>", status_code=400, headers=self._consent_headers())

        redirect_uri = payload["redirect_uri"]
        state = payload.get("state")
        if str(form.get("action", "")) != "approve":
            return RedirectResponse(
                construct_redirect_uri(redirect_uri, error="access_denied", state=state),
                status_code=302,
                headers=self._consent_headers(),
            )

        # Verify first, throttle only the FAILURE. A correct secret is never blocked --
        # so a flood of wrong-secret attempts (the DCR + /authorize endpoints are
        # unauthenticated, so anyone can drive the consent POST) cannot lock the deployer
        # out of approving a connection. Mirrors ServiceAccountVerifier's limiter.
        client_key = request.client.host if request.client else "unknown"
        if _constant_time_equals(str(form.get("secret", "")), self._secret):
            secret_ok = True
        else:
            secret_ok = False
            self._ip_limiter.record_failure(client_key)
            self._global_limiter.record_failure("global")
            log_warning(f"MCP consent login failed from {client_key} (wrong connect secret)")

        if not secret_ok:
            client_name = await self._display_name(payload["client_id"])
            if self._ip_limiter.is_limited(client_key) or self._global_limiter.is_limited("global"):
                log_warning(f"MCP consent login throttled for {client_key}: too many failed attempts")
                return HTMLResponse(
                    "<h1>Too many failed attempts. Try again later.</h1>",
                    status_code=429,
                    headers=self._consent_headers(),
                )
            return self._render_consent_page(
                txn_id, payload, client_name, error="Wrong connect secret.", secure_cookie=secure_cookie
            )

        consumed = await self._run(self._consume_transaction_sync, txn_id)
        if consumed is None:
            return HTMLResponse(
                "<h1>Authorization request not found or expired.</h1>",
                status_code=404,
                headers=self._consent_headers(),
            )

        code = secrets.token_urlsafe(32)
        await self._run(self._store_code_sync, code, consumed)
        await self._run(self._mark_client_consumed_sync, consumed["client_id"])
        log_info(f"MCP consent approved for client {consumed['client_id']}")
        return RedirectResponse(
            construct_redirect_uri(redirect_uri, code=code, state=state),
            status_code=302,
            headers=self._consent_headers(),
        )

    # ==================== Authorization codes ====================

    def _store_code_sync(self, code: str, txn_payload: Dict[str, Any]) -> None:
        now = int(time.time())
        payload = {
            "client_id": txn_payload["client_id"],
            "redirect_uri": txn_payload["redirect_uri"],
            "redirect_uri_provided_explicitly": txn_payload["redirect_uri_provided_explicitly"],
            "code_challenge": txn_payload["code_challenge"],
            "resource": txn_payload.get("resource"),
            # The grant is server-decided: the requested scopes never reach the code.
            "scopes": self._grant_scopes,
        }
        self._require_db().store_mcp_oauth_code(
            code_hash=_hash(code), payload=json.dumps(payload), expires_at=now + self._auth_code_ttl, now=now
        )

    async def load_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: str
    ) -> Optional[AuthorizationCode]:
        row = await self._run(self._load_code_sync, authorization_code)
        if row is None:
            return None
        payload, expires_at = row
        if payload["client_id"] != client.client_id:
            return None
        return AuthorizationCode(
            code=authorization_code,
            scopes=payload["scopes"],
            expires_at=expires_at,
            client_id=payload["client_id"],
            code_challenge=payload["code_challenge"],
            redirect_uri=payload["redirect_uri"],
            redirect_uri_provided_explicitly=payload["redirect_uri_provided_explicitly"],
            resource=payload.get("resource"),
        )

    def _load_code_sync(self, code: str) -> Optional[Any]:
        row = self._require_db().get_mcp_oauth_code(_hash(code))
        if row is None or row[1] < time.time():
            return None
        return json.loads(row[0]), row[1]

    async def exchange_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: AuthorizationCode
    ) -> OAuthToken:
        # Single use, atomically: the DELETE succeeds for exactly one caller, so a
        # replayed code fails on every replica. PKCE was already verified by the SDK
        # token handler against the stored code_challenge.
        deleted = await self._run(self._delete_code_sync, authorization_code.code)
        if not deleted:
            raise TokenError("invalid_grant", "Authorization code not found or already used.")
        if client.client_id is None:
            raise TokenError("invalid_client", "Client ID is required")
        return await self._issue_tokens(client.client_id, authorization_code.scopes)

    def _delete_code_sync(self, code: str) -> bool:
        return self._require_db().delete_mcp_oauth_code(_hash(code))

    # ==================== Tokens ====================

    async def _issue_tokens(self, client_id: str, scopes: List[str], family_id: Optional[str] = None) -> OAuthToken:
        await self._run(self._ensure_ready)
        # A rotation family: minted fresh at the auth-code grant, carried across every
        # refresh so reuse of any token in the chain can revoke the whole family.
        family_id = family_id or secrets.token_hex(16)
        access_token = self._issuer.issue_access_token(
            client_id=client_id, scopes=scopes, jti=secrets.token_hex(16), expires_in=self._access_token_ttl
        )
        refresh_token = self._issuer.issue_refresh_token(
            client_id=client_id,
            scopes=scopes,
            jti=secrets.token_hex(16),
            expires_in=self._refresh_token_ttl,
            upstream_claims={"family_id": family_id},
        )
        await self._run(self._store_refresh_sync, refresh_token, client_id, scopes, family_id)
        return OAuthToken(
            access_token=access_token,
            token_type="Bearer",
            expires_in=self._access_token_ttl,
            refresh_token=refresh_token,
            scope=" ".join(scopes),
        )

    def _store_refresh_sync(self, refresh_token: str, client_id: str, scopes: List[str], family_id: str) -> None:
        now = int(time.time())
        self._require_db().store_mcp_oauth_refresh(
            token_hash=_hash(refresh_token),
            client_id=client_id,
            scopes=json.dumps(scopes),
            expires_at=now + self._refresh_token_ttl,
            now=now,
            family_id=family_id,
        )

    @staticmethod
    def _family_id_of(payload: Optional[Dict[str, Any]]) -> Optional[str]:
        """The rotation family_id embedded in a verified refresh token, if any."""
        return (payload.get("upstream_claims") or {}).get("family_id") if payload else None

    def _delete_refresh_family_sync(self, family_id: str) -> int:
        return self._require_db().delete_mcp_oauth_refresh_family(family_id)

    async def load_refresh_token(
        self, client: OAuthClientInformationFull, refresh_token: str
    ) -> Optional[RefreshToken]:
        await self._run(self._ensure_ready)
        payload = self._verify_any(refresh_token, "refresh")
        if payload is None:
            return None
        row = await self._run(self._load_refresh_sync, refresh_token)
        if row is None:
            # Cryptographically valid and unexpired, but no live row *at all*: this token was
            # already rotated away, so its presentation is reuse (theft or a stale retry).
            # OAuth 2.1 / RFC 9700 reuse detection: revoke the whole rotation family so a
            # stolen chain and the legitimate client both lose access and must re-consent.
            # (An expired-but-present row is handled below -- benign, not reuse.)
            await self._run(self._revoke_family_on_reuse, payload)
            return None
        client_id, scopes_json, expires_at = row
        # An expired row is a benign lazy-sweep artifact, not reuse: reject quietly.
        if expires_at < time.time():
            return None
        if client_id != client.client_id:
            return None
        return RefreshToken(
            token=refresh_token, client_id=client_id, scopes=json.loads(scopes_json), expires_at=expires_at
        )

    def _load_refresh_sync(self, refresh_token: str) -> Optional[Any]:
        # The raw store row (client_id, scopes_json, expires_at) or None when truly absent.
        # Expiry is checked by the caller so a benign expired row is not misread as reuse.
        return self._require_db().get_mcp_oauth_refresh(_hash(refresh_token))

    def _revoke_family_on_reuse(self, payload: Optional[Dict[str, Any]]) -> None:
        """Revoke the whole rotation family of a reused refresh token (RFC 9700)."""
        family_id = self._family_id_of(payload)
        if not family_id:
            return
        removed = self._delete_refresh_family_sync(family_id)
        if removed:
            log_warning(
                f"Reused MCP OAuth refresh token detected; revoked the refresh-token family ({removed} token(s))."
            )

    async def exchange_refresh_token(
        self, client: OAuthClientInformationFull, refresh_token: RefreshToken, scopes: List[str]
    ) -> OAuthToken:
        if scopes and not set(scopes).issubset(set(refresh_token.scopes)):
            raise TokenError("invalid_scope", "Requested scopes exceed those authorized by the refresh token.")
        # Carry the rotation family forward so the new token stays in the same chain.
        payload = self._verify_any(refresh_token.token, "refresh")
        family_id = self._family_id_of(payload)
        # Rotation on every use: deleting the old row is atomic, so a replayed refresh
        # token fails on every replica after its first use.
        deleted = await self._run(self._delete_refresh_sync, refresh_token.token)
        if not deleted:
            # A successful load (the SDK calls load_refresh_token first) followed by a
            # failed delete means another request rotated this token away in between -- a
            # concurrent second presentation of the same refresh token, i.e. reuse. Revoke
            # the family too (RFC 9700), so a thief that wins the rotation race cannot
            # outlive detection; the load-path detector alone would miss this interleaving.
            await self._run(self._revoke_family_on_reuse, payload)
            raise TokenError("invalid_grant", "Refresh token not found or already used.")
        if client.client_id is None:
            raise TokenError("invalid_client", "Client ID is required")
        return await self._issue_tokens(client.client_id, scopes or refresh_token.scopes, family_id=family_id)

    def _delete_refresh_sync(self, refresh_token: str) -> bool:
        return self._require_db().delete_mcp_oauth_refresh(_hash(refresh_token))

    async def load_access_token(self, token: str) -> Optional[AccessToken]:
        """Stateless verification: signature + expiry + issuer + audience, no DB hit.

        Tries every active signing key, so tokens signed by a still-valid previous key
        keep verifying during a rotation overlap.
        """
        await self._run(self._ensure_ready)
        payload = self._verify_any(token, "access")
        if payload is None:
            return None
        client_id = payload.get("client_id", "")
        scopes = str(payload.get("scope", "")).split()
        return AccessToken(
            token=token,
            client_id=client_id,
            scopes=scopes,
            expires_at=payload.get("exp"),
            # INTERNAL_ISSUER_CLAIM marks this as a first-party token so the identity
            # bridge trusts its server-assigned ``__oauth__:`` principal (an external Tier-2
            # token claiming that namespace is rejected).
            claims={
                **payload,
                "sub": f"{_PRINCIPAL_PREFIX}{client_id}",
                INTERNAL_ISSUER_CLAIM: True,
            },
        )

    async def revoke_token(self, token: Any) -> None:
        """RFC 7009: refresh tokens are deleted (renewal stops); access tokens are
        stateless JWTs and expire on their own TTL (rotate the signing key to kill
        them all)."""
        value = getattr(token, "token", None)
        if value is None:
            return
        deleted = await self._run(self._delete_refresh_sync, value)
        if deleted:
            log_info("Revoked a built-in MCP OAuth refresh token")
        else:
            log_debug("Revocation no-op: access tokens are stateless (rotate the signing key to invalidate)")
