"""JWT Middleware for AgentOS - JWT Authentication with optional RBAC."""

import fnmatch
import re
from enum import Enum
from os import getenv
from typing import Any, Dict, List, Optional, Set, Tuple

import jwt
from fastapi import Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from agno.os.scopes import (
    AgentOSScope,
    get_default_scope_mappings,
    has_required_scopes,
    parse_scope,
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
    3. Stores JWT claims (user_id, session_id, scopes) in request.state
    4. Optionally checks if the request path requires specific scopes (if scope_mappings provided)
    5. Validates that the authenticated user has the required scopes
    6. Returns 401 for invalid tokens, 403 for insufficient scopes

    RBAC is opt-in: Only enabled when authorization=True or scope_mappings are provided.
    Without authorization enabled, the middleware only extracts and validates JWT tokens.

    Scope Resolution (when RBAC enabled):
    - Supports wildcard scopes (e.g., "agents:*" matches "agents:read", "agents:run")
    - Supports hierarchical scopes (e.g., "admin" grants all permissions)
    - Custom scope mappings are ADDITIVE to defaults (override on conflict)
    - Empty list [] means "no scopes required" for that route
    - Use AgentOSScope enum for type-safe scope definitions

    Token Sources:
    - "header": Extract from Authorization header (default)
    - "cookie": Extract from HTTP cookie
    - "both": Try header first, then cookie as fallback

    Example:
        from agno.os.middleware import JWTMiddleware
        from agno.os.scopes import AgentOSScope

        # Additive scope mappings (adds to defaults)
        app.add_middleware(
            JWTMiddleware,
            secret_key="your-secret",
            authorization=True,
            scope_mappings={
                # Override default scope for this endpoint
                "GET /agents": [AgentOSScope.AGENTS_READ.value],
                # Add new endpoint mapping
                "POST /custom/endpoint": [AgentOSScope.AGENTS_RUN.value],
                # Allow access without scopes
                "GET /public/stats": [],
            }
        )
    """

    def __init__(
        self,
        app,
        secret_key: Optional[str] = None,
        algorithm: str = "HS256",
        token_source: TokenSource = TokenSource.HEADER,
        token_header_key: str = "Authorization",
        cookie_name: str = "access_token",
        scopes_claim: str = "scopes",
        user_id_claim: str = "sub",
        session_id_claim: str = "session_id",
        dependencies_claims: Optional[List[str]] = None,
        session_state_claims: Optional[List[str]] = None,
        authorization: Optional[bool] = None,
        scope_mappings: Optional[Dict[str, List[str]]] = None,
        excluded_route_paths: Optional[List[str]] = None,
        admin_scope: Optional[str] = None,
    ):
        """
        Initialize the JWT middleware.

        Args:
            app: The FastAPI app instance
            secret_key: JWT secret key (will use JWT_SECRET_KEY env var if not provided)
            algorithm: JWT algorithm (default: HS256)
            token_source: Where to extract JWT token from (header, cookie, or both)
            token_header_key: Header key for Authorization (default: "Authorization")
            cookie_name: Cookie name for JWT token (default: "access_token")
            authorization: Whether to add validation/authorization checks to the request
            scopes_claim: JWT claim name for scopes (default: "scopes")
            user_id_claim: JWT claim name for user ID (default: "sub")
            session_id_claim: JWT claim name for session ID (default: "session_id")
            dependencies_claims: A list of claims to extract from the JWT token for dependencies
            session_state_claims: A list of claims to extract from the JWT token for session state
            scope_mappings: Optional dictionary mapping route patterns to required scopes.
                           If None, RBAC is disabled and only JWT extraction/validation happens.
                           If provided, mappings are ADDITIVE to default scope mappings (overrides on conflict).
                           Use empty list [] to explicitly allow access without scopes for a route.
                           Format: {"POST /agents/*/runs": ["agents:run"], "GET /public": []}
            excluded_route_paths: List of route paths to exclude from JWT/RBAC checks
            admin_scope: The scope that grants admin access (default: "admin")
        """
        super().__init__(app)

        # JWT configuration
        self.secret_key = secret_key or getenv("JWT_SECRET_KEY", "")
        if not self.secret_key:
            raise ValueError(
                "JWT secret key is required. Set via secret_key parameter or JWT_SECRET_KEY environment variable."
            )
        self.algorithm = algorithm
        self.token_source = token_source
        self.token_header_key = token_header_key
        self.cookie_name = cookie_name
        self.scopes_claim = scopes_claim
        self.user_id_claim = user_id_claim
        self.session_id_claim = session_id_claim
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
                import re

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
        return request.cookies.get(self.cookie_name)

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

    def _validate(self, token: str) -> Dict[str, Any]:
        """
        Validate JWT token and extract claims.

        Returns:
            Dictionary of claims if valid, None otherwise
        """
        payload = jwt.decode(token, self.secret_key, algorithms=[self.algorithm])  # type: ignore
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

    async def dispatch(self, request: Request, call_next) -> Response:
        """Process the request: extract JWT, validate, and check RBAC scopes."""
        path = request.url.path
        method = request.method

        # Skip excluded routes
        if self._is_route_excluded(path):
            return await call_next(request)

        # Extract JWT token
        token = self._extract_token(request)
        if not token:
            if self.authorization:
                error_msg = self._get_missing_token_error_message()
                return JSONResponse(status_code=401, content={"detail": error_msg})

        try:
            # Validate token and extract claims
            payload: Dict[str, Any] = self._validate(token)  # type: ignore

            # Extract standard claims and store in request.state
            user_id = payload.get(self.user_id_claim)
            session_id = payload.get(self.session_id_claim)
            scopes = payload.get(self.scopes_claim, [])

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

            # Extract dependencies claims
            dependencies = {}
            for claim in self.dependencies_claims:
                if claim in payload:
                    dependencies[claim] = payload[claim]

            if dependencies:
                log_debug(f"Extracted dependencies: {dependencies}")
                request.state.dependencies = dependencies

            # Extract session state claims
            session_state = {}
            for claim in self.session_state_claims:
                if claim in payload:
                    session_state[claim] = payload[claim]

            if session_state:
                log_debug(f"Extracted session state: {session_state}")
                request.state.session_state = session_state

            # RBAC scope checking (only if enabled)
            if self.authorization:
                # Get agent_os_id from app state
                agent_os_id = getattr(request.app.state, "agent_os_id", None)
                
                # Extract resource type and ID from path
                resource_type = None
                resource_id = None
                
                if "/agents/" in path:
                    resource_type = "agent"
                    resource_id = self._extract_resource_id_from_path(path, "agents")
                elif "/teams/" in path:
                    resource_type = "team"
                    resource_id = self._extract_resource_id_from_path(path, "teams")
                elif "/workflows/" in path:
                    resource_type = "workflow"
                    resource_id = self._extract_resource_id_from_path(path, "workflows")

                required_scopes = self._get_required_scopes(method, path)

                # Empty list [] means no scopes required (allow access)
                if required_scopes:
                    # Use the new scope validation system
                    if not has_required_scopes(
                        scopes,
                        required_scopes,
                        agent_os_id=agent_os_id,
                        resource_type=resource_type,
                        resource_id=resource_id,
                    ):
                        log_warning(
                            f"Insufficient scopes for {method} {path}. Required: {required_scopes}, User has: {scopes}"
                        )
                        return JSONResponse(
                            status_code=403,
                            content={"detail": "Insufficient permissions"},
                        )
                    log_debug(f"Scope check passed for {method} {path}. User scopes: {scopes}")
                else:
                    log_debug(f"No scopes required for {method} {path}")

            log_debug(f"JWT decoded successfully for user: {user_id}")

            request.state.token = token
            request.state.authenticated = True

        except jwt.ExpiredSignatureError:
            if self.authorization:
                return JSONResponse(status_code=401, content={"detail": "Token has expired"})
            request.state.authenticated = False
            request.state.token = token

        except jwt.InvalidTokenError as e:
            if self.authorization:
                return JSONResponse(status_code=401, content={"detail": f"Invalid token: {str(e)}"})
            request.state.authenticated = False
            request.state.token = token
        except Exception as e:
            if self.authorization:
                return JSONResponse(status_code=401, content={"detail": f"Error decoding token: {str(e)}"})
            request.state.authenticated = False
            request.state.token = token

        return await call_next(request)
