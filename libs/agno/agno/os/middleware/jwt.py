import fnmatch
from enum import Enum
from os import getenv
from typing import List, Optional

import jwt
from fastapi import Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from agno.utils.log import log_debug


class TokenSource(str, Enum):
    """Enum for JWT token source options."""

    HEADER = "header"
    COOKIE = "cookie"
    BOTH = "both"  # Try header first, then cookie


class JWTMiddleware(BaseHTTPMiddleware):
    """
    JWT Middleware for validating tokens and storing JWT claims in request state.

    This middleware:
    1. Extracts JWT token from Authorization header, cookies, or both
    2. Decodes and validates the token
    3. Stores JWT claims in request.state for easy access in endpoints

    Token Sources:
    - "header": Extract from Authorization header (default)
    - "cookie": Extract from HTTP cookie
    - "both": Try header first, then cookie as fallback

    Claims are stored as:
    - request.state.user_id: User ID from configured claim
    - request.state.session_id: Session ID from configured claim
    - request.state.dependencies: Dictionary of dependency claims
    - request.state.session_state: Dictionary of session state claims
    - request.state.authenticated: Boolean authentication status

    """

    def __init__(
        self,
        app,
        secret_key: Optional[str] = None,
        algorithm: str = "HS256",
        token_source: TokenSource = TokenSource.HEADER,
        token_header_key: str = "Authorization",
        cookie_name: str = "access_token",
        validate: bool = True,
        excluded_route_paths: Optional[List[str]] = None,
        scopes_claim: Optional[str] = None,
        user_id_claim: str = "sub",
        session_id_claim: str = "session_id",
        dependencies_claims: Optional[List[str]] = None,
        session_state_claims: Optional[List[str]] = None,
    ):
        """
        Initialize the JWT middleware.

        Args:
            app: The FastAPI app instance
            secret_key: The secret key to use for JWT validation (optional, will use JWT_SECRET_KEY environment variable if not provided)
            algorithm: The algorithm to use for JWT validation
            token_header_key: The key to use for the Authorization header (only used when token_source is header)
            token_source: Where to extract the JWT token from (header, cookie, or both)
            cookie_name: The name of the cookie containing the JWT token (only used when token_source is cookie/both)
            validate: Whether to validate the JWT token
            excluded_route_paths: A list of route paths to exclude from JWT validation
            scopes_claim: The claim to use for scopes extraction
            user_id_claim: The claim to use for user ID extraction
            session_id_claim: The claim to use for session ID extraction
            dependencies_claims: A list of claims to extract from the JWT token for dependencies
            session_state_claims: A list of claims to extract from the JWT token for session state
        """
        super().__init__(app)
        self.secret_key = secret_key or getenv("JWT_SECRET_KEY")
        if not self.secret_key:
            raise ValueError("Secret key is required")
        self.algorithm = algorithm
        self.token_header_key = token_header_key
        self.token_source = token_source
        self.cookie_name = cookie_name
        self.validate = validate
        self.excluded_route_paths = excluded_route_paths
        self.scopes_claim = scopes_claim
        self.user_id_claim = user_id_claim
        self.session_id_claim = session_id_claim
        self.dependencies_claims = dependencies_claims or []
        self.session_state_claims = session_state_claims or []

    def _extract_token_from_header(self, request: Request) -> Optional[str]:
        """Extract JWT token from Authorization header."""
        authorization = request.headers.get(self.token_header_key, "")
        if not authorization:
            return None

        try:
            # Remove the "Bearer " prefix (if present)
            _, token = authorization.split(" ", 1)
            return token
        except ValueError:
            return None

    def _extract_token_from_cookie(self, request: Request) -> Optional[str]:
        """Extract JWT token from cookie."""
        return request.cookies.get(self.cookie_name)

    def _extract_token(self, request: Request) -> Optional[str]:
        """Extract JWT token based on configured token source."""
        if self.token_source == TokenSource.HEADER:
            return self._extract_token_from_header(request)
        elif self.token_source == TokenSource.COOKIE:
            return self._extract_token_from_cookie(request)
        elif self.token_source == TokenSource.BOTH:
            # Try header first, then cookie
            token = self._extract_token_from_header(request)
            if token is None:
                token = self._extract_token_from_cookie(request)
            return token
        else:
            log_debug(f"Unknown token source: {self.token_source}")
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

    def _is_route_excluded(self, path: str) -> bool:
        """Check if a route path matches any of the excluded patterns."""
        if not self.excluded_route_paths:
            return False

        for excluded_path in self.excluded_route_paths:
            # Support both exact matches and wildcard patterns
            if fnmatch.fnmatch(path, excluded_path):
                return True

        return False

    async def dispatch(self, request: Request, call_next) -> Response:
        if self._is_route_excluded(request.url.path):
            return await call_next(request)

        # Extract JWT token from configured source (header, cookie, or both)
        token = self._extract_token(request)

        if not token:
            if self.validate:
                error_msg = self._get_missing_token_error_message()
                return JSONResponse(status_code=401, content={"detail": error_msg})
            return await call_next(request)

        # Decode JWT token
        try:
            payload = jwt.decode(token, self.secret_key, algorithms=[self.algorithm])  # type: ignore

            # Extract scopes claims
            scopes = []
            if self.scopes_claim in payload:
                extracted_scopes = payload[self.scopes_claim]
                if isinstance(extracted_scopes, str):
                    scopes = extracted_scopes.split(" ")
                else:
                    scopes = extracted_scopes
            if scopes:
                request.state.scopes = scopes

            # Extract user information
            if self.user_id_claim in payload:
                user_id = payload[self.user_id_claim]
                request.state.user_id = user_id
            if self.session_id_claim in payload:
                session_id = payload[self.session_id_claim]
                request.state.session_id = session_id
            else:
                session_id = None

            # Extract dependency claims
            dependencies = {}
            for claim in self.dependencies_claims:
                if claim in payload:
                    dependencies[claim] = payload[claim]

            if dependencies:
                request.state.dependencies = dependencies

            # Extract session state claims
            session_state = {}
            for claim in self.session_state_claims:
                if claim in payload:
                    session_state[claim] = payload[claim]

            if session_state:
                request.state.session_state = session_state

            request.state.token = token
            request.state.authenticated = True

            log_debug(f"JWT decoded successfully for user: {user_id}")
            if dependencies:
                log_debug(f"Extracted dependencies: {dependencies}")
            if session_state:
                log_debug(f"Extracted session state: {session_state}")

        except jwt.ExpiredSignatureError:
            if self.validate:
                return JSONResponse(status_code=401, content={"detail": "Token has expired"})
            request.state.authenticated = False
            request.state.token = token

        except jwt.InvalidTokenError as e:
            if self.validate:
                return JSONResponse(status_code=401, content={"detail": f"Invalid token: {str(e)}"})
            request.state.authenticated = False
            request.state.token = token
        except Exception as e:
            if self.validate:
                return JSONResponse(status_code=401, content={"detail": f"Error decoding token: {str(e)}"})
            request.state.authenticated = False
            request.state.token = token

        return await call_next(request)
