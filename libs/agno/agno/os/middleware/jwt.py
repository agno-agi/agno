"""JWT Middleware for AgentOS - JWT Authentication with optional RBAC."""

import fnmatch
import re
from enum import Enum
from os import getenv
from typing import Any, Dict, List, Optional

import jwt
from fastapi import Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from agno.os.scopes import (
    AgentOSScope,
    get_accessible_resource_ids,
    get_default_scope_mappings,
    has_required_scopes,
)
from agno.utils.log import log_debug, log_warning


class TokenSource(str, Enum):
    """Enum for JWT token source options."""

    HEADER = "header"
    COOKIE = "cookie"
    BOTH = "both"  # Try header first, then cookie


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
    Without authorization enabled, the middleware only extracts and validates JWT tokens.

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

        app.add_middleware(
            JWTMiddleware,
            verification_key="your-secret",
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
    """

    def __init__(
        self,
        app,
        verification_key: Optional[str] = None,
        secret_key: Optional[str] = None,
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
        verify_audience: bool = False,
        dependencies_claims: Optional[List[str]] = None,
        session_state_claims: Optional[List[str]] = None,
        scope_mappings: Optional[Dict[str, List[str]]] = None,
        excluded_route_paths: Optional[List[str]] = None,
        admin_scope: Optional[str] = None,
    ):
        """
        Initialize the JWT middleware.

        Args:
            app: The FastAPI app instance
            verification_key: Key used to verify JWT signatures (will use JWT_VERIFICATION_KEY env var if not provided).
                             For asymmetric algorithms (RS256, ES256), this should be the public key.
                             For symmetric algorithms (HS256), this is the shared secret.
            secret_key: (deprecated) Use verification_key instead.
            algorithm: JWT algorithm (default: RS256). Common options: RS256 (asymmetric), HS256 (symmetric).
            validate: Whether to validate the JWT token (default: True)
            authorization: Whether to add authorization checks to the request (i.e. validation of scopes)
            token_source: Where to extract JWT token from (header, cookie, or both)
            token_header_key: Header key for Authorization (default: "Authorization")
            cookie_name: Cookie name for JWT token (default: "access_token")
            scopes_claim: JWT claim name for scopes (default: "scopes")
            user_id_claim: JWT claim name for user ID (default: "sub")
            session_id_claim: JWT claim name for session ID (default: "session_id")
            audience_claim: JWT claim name for audience/OS ID (default: "aud")
            verify_audience: Whether to verify the audience claim matches AgentOS ID (default: False)
            dependencies_claims: A list of claims to extract from the JWT token for dependencies
            session_state_claims: A list of claims to extract from the JWT token for session state
            scope_mappings: Optional dictionary mapping route patterns to required scopes.
                           If None, RBAC is disabled and only JWT extraction/validation happens.
                           If provided, mappings are ADDITIVE to default scope mappings (overrides on conflict).
                           Use empty list [] to explicitly allow access without scopes for a route.
                           Format: {"POST /agents/*/runs": ["agents:run"], "GET /public": []}
            excluded_route_paths: List of route paths to exclude from JWT/RBAC checks
            admin_scope: The scope that grants admin access (default: "agent_os:admin")

        Note:
            CORS allowed origins are read from app.state.cors_allowed_origins (set by AgentOS).
            This allows error responses to include proper CORS headers.
        """
        super().__init__(app)

        # JWT configuration
        self.verification_key = verification_key or getenv("JWT_VERIFICATION_KEY", "")
        if not self.verification_key and secret_key:
            self.verification_key = secret_key
        if not self.verification_key:
            raise ValueError(
                "JWT verification key is required. Set via verification_key parameter or JWT_VERIFICATION_KEY environment variable."
            )
        self.algorithm = algorithm
        self.token_source = token_source
        self.token_header_key = token_header_key
        self.cookie_name = cookie_name
        self.validate = validate
        self.scopes_claim = scopes_claim
        self.user_id_claim = user_id_claim
        self.session_id_claim = session_id_claim
        self.audience_claim = audience_claim
        self.verify_audience = verify_audience
        self.dependencies_claims: List[str] = dependencies_claims or []
        self.session_state_claims: List[str] = session_state_claims or []

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

        self.excluded_route_paths = excluded_route_paths or self._get_default_excluded_routes()
        self.admin_scope = admin_scope or AgentOSScope.ADMIN.value

    def _get_default_excluded_routes(self) -> List[str]:
        """Get default routes that should be excluded from RBAC checks."""
        return [
            "/",
            "/health",
            "/docs",
            "/redoc",
            "/openapi.json",
            "/docs/oauth2-redirect",
        ]

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

    def _validate(self, token: str, expected_audience: Optional[str] = None) -> Dict[str, Any]:
        """
        Validate JWT token and extract claims.

        Args:
            token: The JWT token to validate
            expected_audience: The expected audience (AgentOS ID) to verify

        Returns:
            Dictionary of claims if valid

        Raises:
            jwt.InvalidAudienceError: If audience claim doesn't match expected
            jwt.ExpiredSignatureError: If token has expired
            jwt.InvalidTokenError: If token is invalid
        """
        decode_options = {}
        decode_kwargs: Dict[str, Any] = {
            "algorithms": [self.algorithm],
        }

        # Configure audience verification
        if self.verify_audience and expected_audience:
            decode_kwargs["audience"] = expected_audience
        else:
            decode_options["verify_aud"] = False

        if decode_options:
            decode_kwargs["options"] = decode_options

        payload = jwt.decode(token, self.verification_key, **decode_kwargs)  # type: ignore
        return payload

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
    ) -> JSONResponse:
        """Create an error response with CORS headers."""
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
            if self.validate:
                error_msg = self._get_missing_token_error_message()
                return self._create_error_response(401, error_msg, origin, cors_allowed_origins)

        try:
            # Validate token and extract claims (with audience verification if configured)
            expected_audience = agent_os_id if self.verify_audience else None
            payload: Dict[str, Any] = self._validate(token, expected_audience)  # type: ignore

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
            request.state.audience = audience
            request.state.authorization_enabled = self.authorization or False

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
                resource_type = None
                resource_id = None

                if "/agents" in path:
                    resource_type = "agents"
                elif "/teams" in path:
                    resource_type = "teams"
                elif "/workflows" in path:
                    resource_type = "workflows"

                if resource_type:
                    resource_id = self._extract_resource_id_from_path(path, resource_type)

                required_scopes = self._get_required_scopes(method, path)

                # Empty list [] means no scopes required (allow access)
                if required_scopes:
                    # Use the scope validation system
                    has_access = has_required_scopes(
                        scopes,
                        required_scopes,
                        resource_type=resource_type,
                        resource_id=resource_id,
                        admin_scope=self.admin_scope,
                    )

                    # Special handling for listing endpoints (no resource_id)
                    if not has_access and not resource_id and resource_type:
                        # For listing endpoints, always allow access but store accessible IDs for filtering
                        # This allows endpoints to return filtered results (including empty list) instead of 403
                        accessible_ids = get_accessible_resource_ids(
                            scopes, resource_type, admin_scope=self.admin_scope
                        )
                        has_access = True  # Always allow listing endpoints
                        request.state.accessible_resource_ids = accessible_ids

                        if accessible_ids:
                            log_debug(f"User has specific {resource_type} scopes. Accessible IDs: {accessible_ids}")
                        else:
                            log_debug(f"User has no {resource_type} scopes. Will return empty list.")

                    if not has_access:
                        log_warning(
                            f"Insufficient scopes for {method} {path}. Required: {required_scopes}, User has: {scopes}"
                        )
                        return self._create_error_response(
                            403, "Insufficient permissions", origin, cors_allowed_origins
                        )

                    log_debug(f"Scope check passed for {method} {path}. User scopes: {scopes}")
                else:
                    log_debug(f"No scopes required for {method} {path}")

            log_debug(f"JWT decoded successfully for user: {user_id}")

            request.state.token = token
            request.state.authenticated = True

        except jwt.InvalidAudienceError:
            log_warning(f"Invalid audience - expected: {agent_os_id}")
            return self._create_error_response(
                401, "Invalid audience - token not valid for this AgentOS instance", origin, cors_allowed_origins
            )

        except jwt.ExpiredSignatureError:
            if self.validate:
                log_warning("Token has expired")
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
