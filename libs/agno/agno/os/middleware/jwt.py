"""JWT Middleware for AgentOS - JWT Authentication with optional RBAC."""

import fnmatch
import hmac
import json
import re
from enum import Enum
from os import getenv
from typing import TYPE_CHECKING, Any, Dict, Iterable, List, Optional, Union

from fastapi import Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from agno.os.auth import INTERNAL_SERVICE_SCOPES, build_insufficient_permissions_detail
from agno.os.authz.provider import AuthorizationContext
from agno.os.scopes import (
    AgentOSScope,
    get_default_scope_mappings,
    has_required_scopes,
)
from agno.utils.log import log_debug, log_warning

if TYPE_CHECKING:
    from jwt import PyJWK


class TokenSource(str, Enum):
    """Enum for JWT token source options."""

    HEADER = "header"
    COOKIE = "cookie"
    BOTH = "both"  # Try header first, then cookie


class JWTValidator:
    """
    JWT token validator that can be used standalone or within JWTMiddleware.

    This class handles:
    - Loading verification keys (static keys or JWKS files)
    - Validating JWT signatures
    - Extracting claims from tokens

    It can be stored on app.state for use by WebSocket handlers or other
    components that need JWT validation outside of the HTTP middleware chain.

    Example:
        # Create validator
        validator = JWTValidator(
            verification_keys=["your-public-key"],
            algorithm="RS256",
        )

        # Validate a token
        try:
            payload = validator.validate(token)
            user_id = payload.get("sub")
            scopes = payload.get("scopes", [])
        except jwt.InvalidTokenError as e:
            print(f"Invalid token: {e}")

        # Store on app.state for WebSocket access
        app.state.jwt_validator = validator
    """

    def __init__(
        self,
        verification_keys: Optional[List[str]] = None,
        jwks_file: Optional[str] = None,
        jwks_url: Optional[str] = None,
        algorithm: str = "RS256",
        validate: bool = True,
        scopes_claim: str = "scopes",
        user_id_claim: str = "sub",
        session_id_claim: str = "session_id",
        audience_claim: str = "aud",
        leeway: int = 10,
        issuer: Optional[Union[str, Iterable[str]]] = None,
        require_expiration: bool = True,
    ):
        """
        Initialize the JWT validator.

        Args:
            verification_keys: List of keys for verifying JWT signatures.
                              For asymmetric algorithms (RS256, ES256), these should be public keys.
                              For symmetric algorithms (HS256), these are shared secrets.
            jwks_file: Path to a static JWKS (JSON Web Key Set) file containing public keys.
            algorithm: JWT algorithm (default: RS256).
            validate: Whether to validate the JWT token (default: True).
            scopes_claim: JWT claim name for scopes (default: "scopes").
            user_id_claim: JWT claim name for user ID (default: "sub").
            session_id_claim: JWT claim name for session ID (default: "session_id").
            audience_claim: JWT claim name for audience (default: "aud").
            leeway: Seconds of leeway for clock skew tolerance (default: 10). Clamped to
                [0, 300] — a large leeway silently accepts long-expired tokens.
            issuer: Optional expected issuer ("iss"). When set, the token's "iss" claim
                must match (string or any-of an iterable). Pinning the issuer stops a
                signature-valid token minted by one trusted issuer for a different
                relying party from being accepted here. Default None (not checked).
            require_expiration: Require an "exp" claim on validated tokens (default True).
                Without this a token that simply omits "exp" never expires. Only applies
                when validate=True.
        """
        self.algorithm = algorithm
        self.validate = validate
        self.scopes_claim = scopes_claim
        self.user_id_claim = user_id_claim
        self.session_id_claim = session_id_claim
        self.audience_claim = audience_claim
        # Clamp leeway: a huge value would accept tokens long past expiry. Tolerate
        # None (treat as the default 0) so direct construction can't crash on int(None).
        self.leeway = max(0, min(int(leeway or 0), 300))
        self.issuer = issuer
        # An empty issuer ("" or []) is falsy, so pinning is skipped — make that
        # non-silent so a blank JWT_ISSUER env var doesn't quietly disable the check.
        if issuer is not None and not issuer:
            log_warning("issuer is set but empty; issuer ('iss') pinning is DISABLED. Unset it or provide a value.")
        self.require_expiration = require_expiration

        # Build list of verification keys
        self.verification_keys: List[str] = []
        if verification_keys:
            self.verification_keys.extend(verification_keys)

        # Add key from environment variable if not already provided
        env_key = getenv("JWT_VERIFICATION_KEY", "")
        if env_key and env_key not in self.verification_keys:
            self.verification_keys.append(env_key)

        # JWKS configuration - load keys from JWKS file or environment variable.
        self.jwks_keys: "Dict[str, PyJWK]" = {}

        # Try jwks_file parameter first
        if jwks_file:
            self._load_jwks_file(jwks_file)
        else:
            # Try JWT_JWKS_FILE env var (path to file)
            jwks_file_env = getenv("JWT_JWKS_FILE", "")
            if jwks_file_env:
                self._load_jwks_file(jwks_file_env)

        # Remote JWKS URL (e.g. an IdP like WorkOS/Auth0 that publishes and rotates
        # its public keys at a well-known URL). Keys are fetched and cached at
        # startup, then re-fetched lazily (rate-limited) when a token arrives with
        # a key id we haven't seen yet - which is how key rotation is handled.
        self.jwks_url: Optional[str] = jwks_url or getenv("JWT_JWKS_URL", "") or None
        self._jwks_last_fetch: float = 0.0
        self._jwks_min_refresh_seconds: float = 300.0
        if self.jwks_url:
            try:
                self._load_jwks_url(self.jwks_url)
            except Exception as e:
                # Don't hard-fail startup if the IdP is briefly unreachable; we'll
                # retry on the first token that needs a key.
                log_warning(f"Could not fetch JWKS from {self.jwks_url} at startup: {e}")

        # Validate that at least one key source is provided if validate=True
        if self.validate and not self.verification_keys and not self.jwks_keys and not self.jwks_url:
            raise ValueError(
                "At least one JWT verification key or JWKS source is required when validate=True. "
                "Set via verification_keys parameter, JWT_VERIFICATION_KEY environment variable, "
                "jwks_file/JWT_JWKS_FILE, or jwks_url/JWT_JWKS_URL."
            )

        # Guard against the classic RS256<->HS256 algorithm-confusion footgun:
        # configuring an HMAC algorithm with what is clearly an asymmetric PUBLIC
        # key. The public key is, by definition, public — so if it is used as the
        # HMAC shared secret an attacker can forge a token by HMAC-signing with it.
        # Fail closed at startup rather than silently accept forged tokens.
        if self.validate and self.algorithm.upper().startswith("HS"):
            for key in self.verification_keys:
                if isinstance(key, str) and "-----BEGIN" in key and ("PUBLIC KEY" in key or "CERTIFICATE" in key):
                    raise ValueError(
                        f"Refusing to use an asymmetric public key with the symmetric "
                        f"algorithm {self.algorithm!r}: an attacker could HMAC-sign tokens "
                        f"with the (public) key as the secret. Use an asymmetric algorithm "
                        f"(e.g. RS256/ES256) with this key, or supply an actual HMAC secret."
                    )

    def _load_jwks_file(self, file_path: str) -> None:
        """
        Load keys from a static JWKS file.

        Args:
            file_path: Path to the JWKS JSON file
        """
        try:
            with open(file_path) as f:
                jwks_data = json.load(f)
            self._parse_jwks_data(jwks_data)
            log_debug(f"Loaded {len(self.jwks_keys)} key(s) from JWKS file: {file_path}")
        except FileNotFoundError:
            raise ValueError(f"JWKS file not found: {file_path}")
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON in JWKS file {file_path}: {e}")

    def _load_jwks_url(self, url: str) -> None:
        """Fetch a JWKS document from a URL and merge its keys into the cache."""
        import time

        import httpx

        # Require https and don't follow redirects: the JWKS is the root of trust
        # for token verification, so a plaintext fetch (MITM-able) or a redirect to
        # an attacker-controlled host would let forged keys in.
        from urllib.parse import urlparse

        if urlparse(url).scheme != "https":
            raise ValueError(f"JWKS URL must use https (refusing {url!r}): keys fetched over it sign tokens.")
        response = httpx.get(url, timeout=5.0, follow_redirects=False)
        response.raise_for_status()
        self._parse_jwks_data(response.json())
        self._jwks_last_fetch = time.time()
        log_debug(f"Loaded {len(self.jwks_keys)} key(s) from JWKS url: {url}")

    def _maybe_refresh_jwks(self) -> bool:
        """Re-fetch a remote JWKS, at most once per refresh window.

        Called when a token presents a key id we don't have cached - usually
        because the IdP rotated its signing keys. Rate-limited so a flood of
        unknown-kid tokens can't turn into a fetch storm against the IdP.
        """
        import time

        if not self.jwks_url:
            return False
        if time.time() - self._jwks_last_fetch < self._jwks_min_refresh_seconds:
            return False
        try:
            self._load_jwks_url(self.jwks_url)
            return True
        except Exception as e:
            # Stamp the attempt so a persistent outage doesn't hammer the IdP.
            self._jwks_last_fetch = time.time()
            log_warning(f"JWKS refresh from {self.jwks_url} failed: {e}")
            return False

    def _parse_jwks_data(self, jwks_data: Dict[str, Any]) -> None:
        """
        Parse JWKS data and populate self.jwks_keys.

        Args:
            jwks_data: Parsed JWKS dictionary with "keys" array
        """
        from jwt import PyJWK

        keys = jwks_data.get("keys", [])
        if not keys:
            log_warning("JWKS contains no keys")
            return

        for key_data in keys:
            try:
                kid = key_data.get("kid")
                jwk = PyJWK.from_dict(key_data)
                if kid:
                    self.jwks_keys[kid] = jwk
                else:
                    # If no kid, use a default key (for single-key JWKS)
                    self.jwks_keys["_default"] = jwk
            except Exception as e:
                log_warning(f"Failed to parse JWKS key: {str(e)}")

    def validate_token(
        self, token: str, expected_audience: Optional[Union[str, Iterable[str]]] = None
    ) -> Dict[str, Any]:
        """
        Validate JWT token and extract claims.

        Args:
            token: The JWT token to validate
            expected_audience: The expected audience to verify (optional)

        Returns:
            Dictionary of claims if valid

        Raises:
            jwt.InvalidAudienceError: If audience claim doesn't match expected
            jwt.ExpiredSignatureError: If token has expired
            jwt.InvalidTokenError: If token is invalid
        """
        import jwt

        decode_options: Dict[str, Any] = {}
        decode_kwargs: Dict[str, Any] = {
            "algorithms": [self.algorithm],
            "leeway": self.leeway,
        }

        # Configure audience verification
        # We'll decode without audience verification and if we need to verify the audience,
        # we'll manually verify the audience to provide better error messages
        decode_options["verify_aud"] = False

        # If validation is disabled, decode without signature verification
        if not self.validate:
            decode_options["verify_signature"] = False
            decode_kwargs["options"] = decode_options
            return jwt.decode(token, **decode_kwargs)

        # Require an expiration so a token without "exp" can't live forever.
        if self.require_expiration:
            decode_options["require"] = ["exp"]

        if decode_options:
            decode_kwargs["options"] = decode_options

        last_exception: Optional[Exception] = None
        payload: Optional[Dict[str, Any]] = None

        # Try JWKS keys first if configured (cached keys, or a remote JWKS url)
        if self.jwks_keys or self.jwks_url:
            try:
                # Get the kid from the token header to find the right key
                unverified_header = jwt.get_unverified_header(token)
                kid = unverified_header.get("kid")

                jwk = None
                if kid and kid in self.jwks_keys:
                    jwk = self.jwks_keys[kid]

                # Present-but-unknown kid: the IdP may have rotated keys. Re-fetch
                # the remote JWKS (rate-limited) and look again. Do this BEFORE any
                # no-kid fallback so rotation is honoured rather than validating a
                # rotated token against a stale/unrelated default key.
                if jwk is None and kid and self.jwks_url and self._maybe_refresh_jwks():
                    jwk = self.jwks_keys.get(kid)

                # Last resort: a no-kid ("_default") cached key. Reached only when
                # the token carries no kid, or a refresh still didn't resolve one.
                if jwk is None and "_default" in self.jwks_keys:
                    jwk = self.jwks_keys["_default"]

                if jwk:
                    payload = jwt.decode(token, jwk.key, **decode_kwargs)
            except jwt.ExpiredSignatureError:
                raise
            except jwt.InvalidTokenError as e:
                if not self.verification_keys:
                    raise
                last_exception = e

        # Try each static verification key until one succeeds
        if payload is None:
            for key in self.verification_keys:
                try:
                    payload = jwt.decode(token, key, **decode_kwargs)
                    break
                except jwt.ExpiredSignatureError:
                    raise
                except jwt.InvalidTokenError as e:
                    last_exception = e
                    continue

        if payload is None:
            if last_exception:
                raise last_exception
            raise jwt.InvalidTokenError("No verification keys configured")

        # Manually verify audience if expected_audience was provided
        if expected_audience:
            token_audience = payload.get(self.audience_claim)
            if token_audience is None:
                raise jwt.InvalidTokenError(
                    f'Token is missing the "{self.audience_claim}" claim. '
                    f"Audience verification requires this claim to be present in the token."
                )

            # Normalize expected_audience to a list
            if isinstance(expected_audience, str):
                expected_audiences = [expected_audience]
            elif isinstance(expected_audience, Iterable):
                expected_audiences = list(expected_audience)
            else:
                expected_audiences = []

            # Normalize token_audience to a list
            if isinstance(token_audience, str):
                token_audiences = [token_audience]
            elif isinstance(token_audience, list):
                token_audiences = token_audience
            else:
                token_audiences = [token_audience] if token_audience else []

            # Check if any token audience matches any expected audience
            if not any(aud in expected_audiences for aud in token_audiences):
                raise jwt.InvalidAudienceError(
                    f"Invalid audience. Expected one of: {expected_audiences}, got: {token_audiences}"
                )

        # Pin the issuer if configured. Like the audience check above, done
        # manually for a clearer error and to support an allow-list of issuers.
        if self.issuer:
            expected_issuers = [self.issuer] if isinstance(self.issuer, str) else list(self.issuer)
            token_issuer = payload.get("iss")
            if token_issuer not in expected_issuers:
                raise jwt.InvalidIssuerError(
                    f"Invalid issuer. Expected one of: {expected_issuers}, got: {token_issuer!r}"
                )

        return payload

    def extract_claims(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Extract standard claims from a JWT payload.

        Args:
            payload: The decoded JWT payload

        Returns:
            Dictionary with user_id, session_id, scopes, and audience
        """
        scopes = payload.get(self.scopes_claim, [])
        if isinstance(scopes, str):
            scopes = [scopes]
        elif not isinstance(scopes, list):
            scopes = []

        return {
            "user_id": payload.get(self.user_id_claim),
            "session_id": payload.get(self.session_id_claim),
            "scopes": scopes,
            "audience": payload.get(self.audience_claim),
        }


class JWTIssuer:
    """Mint JWTs that an AgentOS / :class:`JWTValidator` will accept.

    The counterpart to :class:`JWTValidator`. Configure it once with your signing
    key and the audience/issuer, then call :meth:`create_token` per user. It uses
    the same claim names the validator expects, always stamps ``iat`` + ``exp``
    (AgentOS requires an expiry by default) and a unique ``jti`` (so the access
    audit can reference the token), and signs with HS256 or an asymmetric algorithm.

    This is the "your app mints the token" half of the no-IdP / app-asserts-identity
    setup — your application authenticates the user however it likes, then mints a
    token here; AgentOS verifies it. (For dev/tests it's also just the easy way to
    get a valid token.)

    Example::

        issuer = JWTIssuer(secret, audience="my-os")          # HS256 from a secret
        token = issuer.create_token("bob", scopes=["agents:*:read"])

        issuer = JWTIssuer(private_pem, algorithm="RS256",     # RS256 from a key
                           audience="my-os", issuer="https://my-app")
        token = issuer.create_token("alice", roles=["admin"], expires_in=3600)
    """

    def __init__(
        self,
        signing_key: str,
        algorithm: Optional[str] = None,
        *,
        audience: Optional[str] = None,
        issuer: Optional[str] = None,
        scopes_claim: str = "scopes",
        user_id_claim: str = "sub",
        default_expiry_seconds: int = 3600,
    ):
        """
        Args:
            signing_key: HS256 shared secret, or an RS256/ES256 PRIVATE key (PEM).
            algorithm: signing algorithm. If omitted, inferred: ``RS256`` when the
                key looks like a PEM, otherwise ``HS256``.
            audience: value for the ``aud`` claim (should match the AgentOS id /
                the validator's expected audience). Per-token override available.
            issuer: value for the ``iss`` claim (match the validator's ``issuer``
                if it pins one).
            scopes_claim: claim name for scopes (default ``scopes``, matches the
                validator).
            user_id_claim: claim name for the subject (default ``sub``).
            default_expiry_seconds: token lifetime when ``expires_in`` isn't given.
        """
        self.signing_key = signing_key
        self.algorithm = algorithm or ("RS256" if "BEGIN" in signing_key else "HS256")
        self.audience = audience
        self.issuer = issuer
        self.scopes_claim = scopes_claim
        self.user_id_claim = user_id_claim
        self.default_expiry_seconds = default_expiry_seconds

    def create_token(
        self,
        subject: str,
        *,
        scopes: Optional[List[str]] = None,
        roles: Optional[Union[str, List[str]]] = None,
        roles_claim: str = "roles",
        audience: Optional[str] = None,
        expires_in: Optional[int] = None,
        not_before: Optional[int] = None,
        jti: bool = True,
        extra_claims: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Mint a signed JWT for ``subject``.

        Args:
            subject: the user id (becomes the ``sub`` claim / principal).
            scopes: scope strings for the ``scopes`` claim (default-provider RBAC).
            roles: role name(s) for the ``roles`` claim (external-IdP style). Pass a
                string or list; goes under ``roles_claim``.
            roles_claim: claim name to carry ``roles`` under (default ``roles``).
            audience: override the configured ``aud`` for this token.
            expires_in: lifetime in seconds (default ``default_expiry_seconds``).
            not_before: optional ``nbf`` offset in seconds from now.
            jti: include a unique ``jti`` (default True) for audit/revocation.
            extra_claims: any additional claims (tenant, email, name, ...).

        Returns:
            The encoded JWT string.
        """
        import time
        import uuid

        now = int(time.time())
        claims: Dict[str, Any] = {
            self.user_id_claim: subject,
            "iat": now,
            "exp": now + (expires_in if expires_in is not None else self.default_expiry_seconds),
        }
        aud = audience if audience is not None else self.audience
        if aud is not None:
            claims["aud"] = aud
        if self.issuer is not None:
            claims["iss"] = self.issuer
        if scopes is not None:
            claims[self.scopes_claim] = scopes
        if roles is not None:
            claims[roles_claim] = roles
        if not_before is not None:
            claims["nbf"] = now + not_before
        if jti:
            claims["jti"] = uuid.uuid4().hex
        if extra_claims:
            claims.update(extra_claims)

        import jwt

        return jwt.encode(claims, self.signing_key, algorithm=self.algorithm)


class JWTMiddleware(BaseHTTPMiddleware):
    """
    JWT Authentication Middleware with optional RBAC (Role-Based Access Control).

    This middleware:
    1. Extracts JWT token from Authorization header or cookies
    2. Decodes and validates the token
    3. Validates the `aud` (audience) claim matches the AgentOS ID (if configured)
    4. Stores JWT claims (user_id, session_id, scopes) in request.state
    5. Optionally checks if the request path requires specific scopes (if scope_mappings provided)
    6. Validates that the authenticated user has the required scopes
    7. Returns 401 for invalid tokens, 403 for insufficient scopes

    RBAC is opt-in: Only enabled when authorization=True or scope_mappings are provided.
    Without authorization enabled, the middleware only extracts and validates JWT tokens —
    endpoints return 200 regardless of scopes. Pass `authorization=True` (or set it via
    AgentOS(authorization=True)) to enforce the default scope map.

    Audience Verification:
    - The `aud` claim in JWT tokens should contain the AgentOS ID
    - This is verified against the AgentOS instance ID from app.state.agent_os_id
    - Tokens with mismatched audience will be rejected with 401

    Scope Format (simplified):
    - Global resource scopes: `resource:action` (e.g., "agents:read")
    - Per-resource scopes: `resource:<resource-id>:action` (e.g., "agents:web-agent:run")
    - Wildcards: `resource:*:action` (e.g., "agents:*:run")
    - Admin scope: `admin` (grants all permissions)

    Token Sources:
    - "header": Extract from Authorization header (default)
    - "cookie": Extract from HTTP cookie
    - "both": Try header first, then cookie as fallback

    Example:
        from agno.os.middleware import JWTMiddleware
        from agno.os.scopes import AgentOSScope

        # Single verification key
        app.add_middleware(
            JWTMiddleware,
            verification_keys=["your-public-key"],
            authorization=True,
            verify_audience=True,  # Verify aud claim matches AgentOS ID
            scope_mappings={
                # Override default scope for this endpoint
                "GET /agents": ["agents:read"],
                # Add new endpoint mapping
                "POST /custom/endpoint": ["agents:run"],
                # Allow access without scopes
                "GET /public/stats": [],
            }
        )

        # Multiple verification keys (accept tokens from multiple issuers)
        app.add_middleware(
            JWTMiddleware,
            verification_keys=[
                "public-key-from-issuer-1",
                "public-key-from-issuer-2",
            ],
            authorization=True,
        )

        # Using a static JWKS file
        app.add_middleware(
            JWTMiddleware,
            jwks_file="/path/to/jwks.json",
            authorization=True,
        )

        # No validation (extract claims only, useful for development)
        app.add_middleware(
            JWTMiddleware,
            validate=False,  # No verification key needed
        )
    """

    def __init__(
        self,
        app,
        verification_keys: Optional[List[str]] = None,
        jwks_file: Optional[str] = None,
        jwks_url: Optional[str] = None,
        secret_key: Optional[str] = None,  # Deprecated: Use verification_keys instead
        algorithm: str = "RS256",
        validate: bool = True,
        authorization: Optional[bool] = None,
        token_source: TokenSource = TokenSource.HEADER,
        token_header_key: str = "Authorization",
        cookie_name: str = "access_token",
        scopes_claim: str = "scopes",
        user_id_claim: str = "sub",
        session_id_claim: str = "session_id",
        audience_claim: str = "aud",
        audience: Optional[Union[str, Iterable[str]]] = None,
        verify_audience: bool = False,
        issuer: Optional[Union[str, Iterable[str]]] = None,
        leeway: int = 10,
        require_expiration: bool = True,
        dependencies_claims: Optional[List[str]] = None,
        session_state_claims: Optional[List[str]] = None,
        scope_mappings: Optional[Dict[str, List[str]]] = None,
        excluded_route_paths: Optional[List[str]] = None,
        admin_scope: Optional[str] = None,
        user_isolation: bool = False,
    ):
        """
        Initialize the JWT middleware.

        Args:
            app: The FastAPI app instance
            verification_keys: List of keys for verifying JWT signatures.
                              For asymmetric algorithms (RS256, ES256), these should be public keys.
                              For symmetric algorithms (HS256), these are shared secrets.
                              Each key will be tried in order until one successfully validates the token.
                              Useful when accepting tokens signed by different private keys.
                              If not provided, will use JWT_VERIFICATION_KEY env var (as a single-item list).
            jwks_file: Path to a static JWKS (JSON Web Key Set) file containing public keys.
                      The file should contain a JSON object with a "keys" array.
                      Keys are looked up by the "kid" (key ID) claim in the JWT header.
                      If not provided, will check JWT_JWKS_FILE env var for a file path,
                      or JWT_JWKS env var for inline JWKS JSON content.
            secret_key: (deprecated) Use verification_keys instead. If provided, will be added to verification_keys.
            algorithm: JWT algorithm (default: RS256). Common options: RS256 (asymmetric), HS256 (symmetric).
            validate: Whether to validate the JWT signature (default: True). If False, tokens are decoded
                     without signature verification and no verification key is required. Useful when
                     JWT verification is handled upstream (API Gateway, etc.).
            authorization: Whether to add authorization checks to the request (i.e. validation of scopes)
            token_source: Where to extract JWT token from (header, cookie, or both)
            token_header_key: Header key for Authorization (default: "Authorization")
            cookie_name: Cookie name for JWT token (default: "access_token")
            scopes_claim: JWT claim name for scopes (default: "scopes")
            user_id_claim: JWT claim name for user ID (default: "sub")
            session_id_claim: JWT claim name for session ID (default: "session_id")
            audience_claim: JWT claim name for audience/OS ID (default: "aud")
            audience: Optional expected audience claim to validate against the token's audience claim (default: AgentOS ID)
            verify_audience: Whether to verify the token's audience claim matches the expected audience claim (default: False)
            dependencies_claims: A list of claims to extract from the JWT token for dependencies
            session_state_claims: A list of claims to extract from the JWT token for session state
            scope_mappings: Optional dictionary mapping route patterns to required scopes.
                           If None, RBAC is disabled and only JWT extraction/validation happens.
                           If provided, mappings are ADDITIVE to default scope mappings (overrides on conflict).
                           Use empty list [] to explicitly allow access without scopes for a route.
                           Format: {"POST /agents/*/runs": ["agents:run"], "GET /public": []}
            excluded_route_paths: List of route paths to exclude from JWT/RBAC checks
            admin_scope: The scope that grants admin access (default: "agent_os:admin")
            user_isolation: Opt in to per-user data isolation (default False).
                When True, route handlers wrap the DB in a per-request scoped
                adapter and enforce session/run ownership on non-admin callers.
                When False (the default) JWT and RBAC still apply but
                ownership/scoping gates stay dormant — preserves backwards
                compatibility with deployments that handle isolation in their
                own application layer.

        Note:
            - At least one verification key or JWKS file must be provided if validate=True
            - If validate=False, no verification key is needed (claims are extracted without verification)
            - JWKS keys are tried first (by kid), then static verification_keys as fallback
            - CORS allowed origins are read from app.state.cors_allowed_origins (set by AgentOS).
              This allows error responses to include proper CORS headers.
        """
        super().__init__(app)

        # Handle deprecated secret_key parameter
        all_verification_keys = list(verification_keys) if verification_keys else []
        if secret_key:
            log_warning("secret_key is deprecated. Use verification_keys instead.")
            if secret_key not in all_verification_keys:
                all_verification_keys.append(secret_key)

        # Create the JWT validator (handles key loading and token validation)
        self.validator = JWTValidator(
            verification_keys=all_verification_keys if all_verification_keys else None,
            jwks_file=jwks_file,
            jwks_url=jwks_url,
            algorithm=algorithm,
            validate=validate,
            scopes_claim=scopes_claim,
            user_id_claim=user_id_claim,
            session_id_claim=session_id_claim,
            audience_claim=audience_claim,
            leeway=leeway,
            issuer=issuer,
            require_expiration=require_expiration,
        )

        # Loud warning for a dangerous combination: skipping signature validation
        # while still making authorization decisions. With validate=False the
        # middleware trusts the token's claims (incl. scopes) without verifying the
        # signature — anyone can mint "agent_os:admin". Only safe when an upstream
        # gateway has already verified the signature.
        if validate is False and authorization:
            log_warning(
                "JWTMiddleware: validate=False with authorization enabled — token signatures are "
                "NOT verified, so scopes/roles in the token are attacker-controllable. Only use this "
                "when a trusted upstream (API gateway/proxy) has already verified the JWT signature."
            )

        # Store config for easy access
        self.validate = validate
        self.algorithm = algorithm
        self.token_source = token_source
        self.token_header_key = token_header_key
        self.cookie_name = cookie_name
        self.scopes_claim = scopes_claim
        self.user_id_claim = user_id_claim
        self.session_id_claim = session_id_claim
        self.audience_claim = audience_claim
        self.verify_audience = verify_audience
        self.dependencies_claims: List[str] = dependencies_claims or []
        self.session_state_claims: List[str] = session_state_claims or []

        self.audience = audience

        # RBAC configuration (opt-in via scope_mappings)
        self.authorization = authorization

        # If scope_mappings are provided, enable authorization
        if scope_mappings is not None and self.authorization is None:
            self.authorization = True

        # Build final scope mappings (additive approach)
        if self.authorization:
            # Start with default scope mappings
            self.scope_mappings = get_default_scope_mappings()

            # Merge user-provided scope mappings (overrides defaults)
            if scope_mappings is not None:
                self.scope_mappings.update(scope_mappings)
        else:
            self.scope_mappings = scope_mappings or {}

        self.excluded_route_paths = (
            excluded_route_paths if excluded_route_paths is not None else self._get_default_excluded_routes()
        )
        self.admin_scope = admin_scope or AgentOSScope.ADMIN.value
        self.user_isolation = user_isolation
        # Lazily-built default provider for manual-setup deployments that don't
        # populate app.state.authorization_provider (see _resolve_provider).
        self._fallback_provider = None

    def _get_default_excluded_routes(self) -> List[str]:
        """Get default routes that should be excluded from RBAC checks."""
        return [
            "/",
            "/health",
            "/info",
            "/docs",
            "/redoc",
            "/openapi.json",
            "/docs/oauth2-redirect",
        ]

    def _resolve_provider(self, request: Request):
        """Resolve the active AuthorizationProvider.

        Prefers the instance AgentOS set on ``app.state.authorization_provider``;
        falls back to a default ``ScopeAuthorizationProvider`` for manual
        ``app.add_middleware(JWTMiddleware)`` setups that never populated it.
        Cached on the middleware instance after first use to avoid rebuilding a
        fallback provider on every request.
        """
        provider = getattr(getattr(request, "app", None), "state", None)
        provider = getattr(provider, "authorization_provider", None) if provider is not None else None
        if provider is not None:
            return provider
        if self._fallback_provider is None:
            from agno.os.authz.scope_provider import ScopeAuthorizationProvider

            self._fallback_provider = ScopeAuthorizationProvider()
        return self._fallback_provider

    def _record_decision(
        self,
        request: Request,
        *,
        allowed: bool,
        method: str,
        path: str,
        principal: Optional[str],
        required_scopes: List[str],
        scopes: List[str],
        token: Optional[str],
        claims: Optional[dict] = None,
        reason: Optional[str] = None,
    ) -> None:
        """Record one authorization decision to the audit sink (if configured).

        Captures the principal, route, required scopes, and a NON-secret token
        reference so you can tell which token was used without storing the
        credential. The reference is the token's ``jti`` (a standard, opaque token
        id) when the token carries one — stable, correlatable to the issuer's logs,
        and revocation-friendly — falling back to a short SHA-256 of the token
        otherwise. Never the token itself, and never raises into the request path.
        """
        state = getattr(getattr(request, "app", None), "state", None)
        sink = getattr(state, "authz_audit", None) if state is not None else None
        if sink is None:
            return
        try:
            import time

            from agno.os.authz.audit import AuditEvent

            token_ref = self._token_reference(token, claims)
            metadata = {"required": required_scopes, "token": token_ref, "scopes": scopes}
            if reason:
                metadata["reason"] = reason
            sink.record(
                AuditEvent(
                    action="access.allowed" if allowed else "access.denied",
                    actor=principal,
                    target=f"{method} {path}",
                    timestamp=int(time.time()),
                    metadata=metadata,
                )
            )
        except Exception as e:  # pragma: no cover - audit must never break requests
            log_debug(f"decision audit failed: {e}")

    @staticmethod
    def _token_reference(token: Optional[str], claims: Optional[dict]) -> Optional[str]:
        """A non-secret reference to the presented token, for the decision trail.

        Prefer the token's ``jti`` (RFC 7519 JWT ID): it's an opaque identifier the
        issuer already minted for exactly this purpose, so it correlates to the
        issuer's own logs and any revocation list. When the token has no ``jti``,
        fall back to a short SHA-256 of the raw token so we can still tell two
        distinct tokens apart — without storing the credential itself.
        """
        if claims:
            jti = claims.get("jti")
            if jti:
                return str(jti)
        if token:
            import hashlib

            return hashlib.sha256(token.encode()).hexdigest()[:12]
        return None

    # Resource families that get per-resource scopes + list filtering. Order is
    # irrelevant — a path has at most one leading family segment.
    _RESOURCE_TYPES = ("agents", "teams", "workflows")

    def _detect_resource_type(self, path: str) -> Optional[str]:
        """Classify a path's resource family by its FIRST segment, not a substring.

        Must be a leading-segment match (``/agents`` or ``/agents/...``). A naive
        ``"/agents" in path`` substring test misclassifies unrelated routes whose
        id segment merely contains the family name — e.g. ``/sessions/agents-1``
        (a session whose id starts with "agents") would be tagged as an *agents*
        route with no resource id, and the list-endpoint fallback would then wave
        it through without the scope the route actually requires. Anchoring to the
        first segment closes that bypass.
        """
        for rt in self._RESOURCE_TYPES:
            if path == f"/{rt}" or path.startswith(f"/{rt}/"):
                return rt
        return None

    def _extract_resource_id_from_path(self, path: str, resource_type: str) -> Optional[str]:
        """
        Extract resource ID from a path.

        Args:
            path: The request path
            resource_type: Type of resource ("agents", "teams", "workflows")

        Returns:
            The resource ID if found, None otherwise

        Examples:
            >>> _extract_resource_id_from_path("/agents/my-agent/runs", "agents")
            "my-agent"
        """
        # Pattern: /{resource_type}/{resource_id}/...
        pattern = f"^/{resource_type}/([^/]+)"
        match = re.search(pattern, path)
        if match:
            return match.group(1)
        return None

    def _is_route_excluded(self, path: str) -> bool:
        """Check if a route path matches any of the excluded patterns."""
        if not self.excluded_route_paths:
            return False

        for excluded_path in self.excluded_route_paths:
            # Support both exact matches and wildcard patterns
            if fnmatch.fnmatch(path, excluded_path):
                return True
            # Also check without trailing slash
            if fnmatch.fnmatch(path.rstrip("/"), excluded_path):
                return True

        return False

    def _get_required_scopes(self, method: str, path: str) -> List[str]:
        """
        Get required scopes for a given method and path.

        Args:
            method: HTTP method (GET, POST, etc.)
            path: Request path

        Returns:
            List of required scopes. Empty list [] means no scopes required (allow access).
            Routes not in scope_mappings also return [], allowing access.
        """
        route_key = f"{method} {path}"

        # First, try exact match
        if route_key in self.scope_mappings:
            return self.scope_mappings[route_key]

        # Then try pattern matching
        for pattern, scopes in self.scope_mappings.items():
            pattern_method, pattern_path = pattern.split(" ", 1)

            # Check if method matches
            if pattern_method != method:
                continue

            # Convert pattern to fnmatch pattern (replace {param} with *)
            # This handles both /agents/* and /agents/{agent_id} style patterns
            normalized_pattern = pattern_path
            if "{" in normalized_pattern:
                # Replace {param} with * for pattern matching
                normalized_pattern = re.sub(r"\{[^}]+\}", "*", normalized_pattern)

            if fnmatch.fnmatch(path, normalized_pattern):
                return scopes

        return []

    def _extract_token_from_header(self, request: Request) -> Optional[str]:
        """Extract JWT token from Authorization header."""
        authorization = request.headers.get(self.token_header_key, "")
        if not authorization:
            return None

        # Support both "Bearer <token>" and just "<token>"
        if authorization.lower().startswith("bearer "):
            return authorization[7:].strip()
        return authorization.strip()

    def _extract_token_from_cookie(self, request: Request) -> Optional[str]:
        """Extract JWT token from cookie."""
        cookie_value = request.cookies.get(self.cookie_name)
        if cookie_value:
            return cookie_value.strip()
        return None

    def _get_missing_token_error_message(self) -> str:
        """Get appropriate error message for missing token based on token source."""
        if self.token_source == TokenSource.HEADER:
            return "Authorization header missing"
        elif self.token_source == TokenSource.COOKIE:
            return f"JWT cookie '{self.cookie_name}' missing"
        elif self.token_source == TokenSource.BOTH:
            return f"JWT token missing from both Authorization header and '{self.cookie_name}' cookie"
        else:
            return "JWT token missing"

    def _create_error_response(
        self,
        status_code: int,
        detail: str,
        origin: Optional[str] = None,
        cors_allowed_origins: Optional[List[str]] = None,
        required_scopes: Optional[List[str]] = None,
    ) -> JSONResponse:
        """Create an error response with CORS headers."""
        if required_scopes:
            detail = build_insufficient_permissions_detail(required_scopes)
        response = JSONResponse(status_code=status_code, content={"detail": detail})

        # Add CORS headers to the error response
        if origin and self._is_origin_allowed(origin, cors_allowed_origins):
            response.headers["Access-Control-Allow-Origin"] = origin
            response.headers["Access-Control-Allow-Credentials"] = "true"
            response.headers["Access-Control-Allow-Methods"] = "*"
            response.headers["Access-Control-Allow-Headers"] = "*"
            response.headers["Access-Control-Expose-Headers"] = "*"

        return response

    def _is_origin_allowed(self, origin: str, cors_allowed_origins: Optional[List[str]] = None) -> bool:
        """Check if the origin is in the allowed origins list."""
        if not cors_allowed_origins:
            # If no allowed origins configured, allow all (fallback to default behavior)
            return True

        # Check if origin is in the allowed list
        return origin in cors_allowed_origins

    async def dispatch(self, request: Request, call_next) -> Response:
        """Process the request: extract JWT, validate, and check RBAC scopes."""
        import jwt

        # Ensure the JWT auth config is accessible on app.state for WebSocket
        # endpoints (which don't flow through this middleware) and any other
        # components that need it outside the middleware chain. This handles
        # both built-in (AgentOS authorization=True) and manual
        # (app.add_middleware(JWTMiddleware, ...)) setup paths.
        #
        # All these values must be cached together: resolve_ws_jwt_config
        # returns early once it sees ``jwt_validator``, so without the
        # companion fields a manual-setup WebSocket connection arriving after
        # the first HTTP request would silently drop verify_audience, the
        # custom admin scope, and the user_isolation flag.
        if not getattr(request.app.state, "jwt_validator", None):
            request.app.state.jwt_validator = self.validator
            request.app.state.jwt_verify_audience = self.verify_audience
            request.app.state.jwt_audience = self.audience
            request.app.state.admin_scope = self.admin_scope
            request.app.state.user_isolation_enabled = self.user_isolation

        path = request.url.path
        method = request.method

        # Skip OPTIONS requests (CORS preflight)
        if method == "OPTIONS":
            return await call_next(request)

        # Skip excluded routes
        if self._is_route_excluded(path):
            return await call_next(request)

        # Get origin and CORS allowed origins for error responses
        origin = request.headers.get("origin")
        cors_allowed_origins = getattr(request.app.state, "cors_allowed_origins", None)

        # Get agent_os_id from app state for audience verification
        agent_os_id = getattr(request.app.state, "agent_os_id", None)

        # Extract JWT token
        token = self._extract_token(request)
        if not token:
            error_msg = self._get_missing_token_error_message()
            return self._create_error_response(401, error_msg, origin, cors_allowed_origins)

        # Check for internal service token (used by scheduler executor)
        internal_token = getattr(request.app.state, "internal_service_token", None)
        if internal_token and hmac.compare_digest(token, internal_token):
            request.state.authenticated = True
            request.state.user_id = "__scheduler__"
            request.state.session_id = None
            internal_scopes = list(INTERNAL_SERVICE_SCOPES)
            request.state.scopes = internal_scopes
            request.state.authorization_enabled = self.authorization or False
            request.state.admin_scope = self.admin_scope
            request.state.user_isolation_enabled = self.user_isolation

            # Enforce RBAC for internal token (do not skip scope checks)
            if self.authorization:
                required_scopes = self._get_required_scopes(method, path)
                if required_scopes:
                    if not has_required_scopes(
                        internal_scopes,
                        required_scopes,
                        admin_scope=self.admin_scope,
                    ):
                        log_warning(
                            f"Internal service token denied for {method} {path}. "
                            f"Required: {required_scopes}, Token has: {internal_scopes}"
                        )
                        return self._create_error_response(
                            403,
                            "Insufficient permissions",
                            origin,
                            cors_allowed_origins,
                            required_scopes=required_scopes,
                        )

            return await call_next(request)

        try:
            # Validate token and extract claims (with audience verification if configured)
            expected_audience = None
            if self.verify_audience:
                expected_audience = self.audience or agent_os_id
                # Fail closed: audience verification was explicitly requested but
                # there is nothing to verify against (no configured audience and no
                # AgentOS id on app.state). Silently skipping the check would accept
                # tokens minted for any audience, defeating the point of enabling it.
                if not expected_audience:
                    log_warning(
                        "verify_audience=True but no audience is configured and no AgentOS id is "
                        "available; rejecting the request instead of skipping the audience check."
                    )
                    return self._create_error_response(
                        401,
                        "Audience verification is enabled but no expected audience is configured",
                        origin,
                        cors_allowed_origins,
                    )
            payload: Dict[str, Any] = self.validator.validate_token(token, expected_audience)  # type: ignore

            # Extract standard claims and store in request.state
            user_id = payload.get(self.user_id_claim)
            session_id = payload.get(self.session_id_claim)
            scopes = payload.get(self.scopes_claim, [])
            audience = payload.get(self.audience_claim)

            # Ensure scopes is a list
            if isinstance(scopes, str):
                scopes = [scopes]
            elif not isinstance(scopes, list):
                scopes = []

            # Store claims in request.state
            request.state.authenticated = True
            request.state.user_id = user_id
            request.state.session_id = session_id
            request.state.scopes = scopes
            request.state.claims = payload  # Full decoded JWT for factory ctx.trusted.claims
            request.state.audience = audience
            request.state.authorization_enabled = self.authorization or False
            # Expose admin scope so downstream helpers (e.g. get_scoped_user_id)
            # honour custom admin scopes configured via JWTMiddleware(admin_scope=...).
            request.state.admin_scope = self.admin_scope
            # Per-user isolation is opt-in. get_scoped_user_id short-circuits
            # to None when this is False, so the DB wrapper and route-level
            # ownership gates stay dormant.
            request.state.user_isolation_enabled = self.user_isolation

            # User directory (no-IdP): optionally auto-provision the subject from
            # token claims, then enforce the disabled flag. This is the revocation
            # kill-switch — a disabled user is denied even with a valid token, on
            # EVERY route (independent of per-route scopes). Identity is still the
            # app's to assert; we only gate it.
            user_store = getattr(getattr(request.app, "state", None), "user_store", None)
            if user_store is not None and user_id:
                try:
                    if getattr(request.app.state, "user_auto_provision", False):
                        user_store.provision_from_claims(
                            user_id,
                            payload,
                            email_claim=getattr(request.app.state, "user_email_claim", "email"),
                            name_claim=getattr(request.app.state, "user_name_claim", "name"),
                        )
                    disabled = user_store.is_disabled(user_id)
                except Exception as e:  # never let directory issues fail open OR crash the request
                    log_warning(f"user directory check failed for {user_id!r}: {e}")
                    disabled = False
                if disabled:
                    log_warning(f"Disabled user denied: {user_id} for {method} {path}")
                    self._record_decision(
                        request,
                        allowed=False,
                        method=method,
                        path=path,
                        principal=user_id,
                        required_scopes=[],
                        scopes=scopes,
                        token=token,
                        claims=payload,
                        reason="user_disabled",
                    )
                    return self._create_error_response(403, "User is disabled", origin, cors_allowed_origins)

            # Extract dependencies claims
            dependencies = {}
            if self.dependencies_claims:
                for claim in self.dependencies_claims:
                    if claim in payload:
                        dependencies[claim] = payload[claim]

            if dependencies:
                log_debug(f"Extracted dependencies: {dependencies}")
                request.state.dependencies = dependencies

            # Extract session state claims
            session_state = {}
            if self.session_state_claims:
                for claim in self.session_state_claims:
                    if claim in payload:
                        session_state[claim] = payload[claim]

            if session_state:
                log_debug(f"Extracted session state: {session_state}")
                request.state.session_state = session_state

            # RBAC scope checking (only if enabled)
            if self.authorization:
                # Extract resource type and ID from path
                resource_type = self._detect_resource_type(path)
                resource_id = None
                if resource_type:
                    resource_id = self._extract_resource_id_from_path(path, resource_type)

                required_scopes = self._get_required_scopes(method, path)
                request.state.required_scopes = required_scopes

                # Empty list [] means no scopes required (allow access)
                if required_scopes:
                    # Resolve the active authorization provider. Defaults to the
                    # scope-based provider (identical behaviour); a custom provider
                    # configured via AuthorizationConfig owns the decision instead.
                    # Build one context and reuse it for the route gate and the
                    # listing-endpoint filtering below.
                    provider = self._resolve_provider(request)
                    # Derive a single context action only when all required scopes
                    # agree on one (true for every built-in mapping). For a route
                    # with mixed actions, leave it None rather than silently picking
                    # the first — the full required_scopes list is passed to
                    # authorize_route, which evaluates each one.
                    _actions = {s.rsplit(":", 1)[1] for s in required_scopes if ":" in s}
                    action_for_ctx: Optional[str] = next(iter(_actions)) if len(_actions) == 1 else None
                    authz_ctx = AuthorizationContext(
                        principal_id=user_id,
                        scopes=scopes,
                        claims=payload,
                        resource_type=resource_type,
                        resource_id=resource_id,
                        action=action_for_ctx,
                        admin_scope=self.admin_scope,
                    )

                    has_access = provider.authorize_route(authz_ctx, required_scopes)

                    # Special handling for listing endpoints (no resource_id)
                    if not has_access and not resource_id and resource_type:
                        # For listing endpoints, always allow access but store accessible IDs for filtering
                        # This allows endpoints to return filtered results (including empty list) instead of 403.
                        # The provider decides which IDs are accessible (the scope provider keys off the
                        # action so a user with only `agents:run` doesn't leak through `GET /agents`).
                        accessible_ids = provider.accessible_resource_ids(authz_ctx)
                        has_access = True  # Always allow listing endpoints
                        request.state.accessible_resource_ids = accessible_ids

                        if accessible_ids:
                            log_debug(f"User has specific {resource_type} scopes. Accessible IDs: {accessible_ids}")
                        else:
                            log_debug(f"User has no {resource_type} scopes. Will return empty list.")

                    # Decision audit: record the allow/deny with a non-secret
                    # token reference, if an audit sink is configured.
                    self._record_decision(
                        request,
                        allowed=has_access,
                        method=method,
                        path=path,
                        principal=user_id,
                        required_scopes=required_scopes,
                        scopes=scopes,
                        token=token,
                        claims=payload,
                    )

                    if not has_access:
                        log_warning(
                            f"Insufficient scopes for {method} {path}. Required: {required_scopes}, User has: {scopes}"
                        )
                        return self._create_error_response(
                            403,
                            "Insufficient permissions",
                            origin,
                            cors_allowed_origins,
                            required_scopes=required_scopes,
                        )

                    log_debug(f"Scope check passed for {method} {path}. User scopes: {scopes}")
                else:
                    log_debug(f"No scopes required for {method} {path}")
                    # Decision-audit completeness: record allow-by-default routes
                    # (empty/unmapped scope map) too, so the trail covers EVERY
                    # authenticated request, not only the scope-gated ones. No-ops
                    # when no decision sink is configured.
                    self._record_decision(
                        request,
                        allowed=True,
                        method=method,
                        path=path,
                        principal=user_id,
                        required_scopes=[],
                        scopes=scopes,
                        token=token,
                        claims=payload,
                        reason="no_scopes_required",
                    )

            log_debug(f"JWT decoded successfully for user: {user_id}")

            request.state.token = token
            request.state.authenticated = True

        except jwt.InvalidAudienceError as e:
            log_warning(f"Invalid token audience - expected: {expected_audience}: {str(e)}")
            return self._create_error_response(
                401, "Invalid token audience - token not valid for this AgentOS instance", origin, cors_allowed_origins
            )
        except jwt.ExpiredSignatureError as e:
            if self.validate:
                log_warning(f"Token has expired: {str(e)}")
                return self._create_error_response(401, "Token has expired", origin, cors_allowed_origins)
            request.state.authenticated = False
            request.state.token = token

        except jwt.InvalidTokenError as e:
            if self.validate:
                log_warning(f"Invalid token: {str(e)}")
                return self._create_error_response(401, f"Invalid token: {str(e)}", origin, cors_allowed_origins)
            request.state.authenticated = False
            request.state.token = token
        except Exception as e:
            if self.validate:
                log_warning(f"Error decoding token: {str(e)}")
                return self._create_error_response(401, f"Error decoding token: {str(e)}", origin, cors_allowed_origins)
            request.state.authenticated = False
            request.state.token = token

        return await call_next(request)

    def _extract_token(self, request: Request) -> Optional[str]:
        """Extract JWT token based on configured source."""
        if self.token_source == TokenSource.HEADER:
            return self._extract_token_from_header(request)
        elif self.token_source == TokenSource.COOKIE:
            return self._extract_token_from_cookie(request)
        elif self.token_source == TokenSource.BOTH:
            # Try header first, then cookie
            token = self._extract_token_from_header(request)
            if token:
                return token
            return self._extract_token_from_cookie(request)
        return None
