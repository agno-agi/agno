from typing import List, Optional

import jwt
from fastapi import Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from agno.utils.log import log_debug


class JWTMiddleware(BaseHTTPMiddleware):
    """
    JWT Middleware for validating tokens and storing JWT claims in request state.

    This middleware:
    1. Extracts JWT token from Authorization header
    2. Decodes and validates the token
    3. Stores JWT claims in request.state for easy access in endpoints

    Claims are stored as:
    - request.state.jwt_user_id: User ID from configured claim
    - request.state.jwt_session_id: Session ID from configured claim  
    - request.state.jwt_dependencies: Dictionary of dependency claims
    - request.state.authenticated: Boolean authentication status

    """

    def __init__(
        self,
        app,
        secret_key: str,
        algorithm: str = "HS256",
        token_prefix: str = "Bearer",
        validate: bool = True,
        excluded_route_paths: Optional[List[str]] = None,
        user_id_claim: str = "sub",
        session_id_claim: Optional[str] = None,
        dependencies_claims: Optional[List[str]] = None,
    ):
        """
        Initialize the JWT middleware.

        Args:
            app: The FastAPI app instance
            secret_key: The secret key to use for JWT validation
            algorithm: The algorithm to use for JWT validation
            token_prefix: The prefix to use for JWT validation
            validate: Whether to validate the JWT token
            excluded_route_paths: A list of route paths to exclude from JWT validation
            user_id_claim: The claim to use for user ID extraction
            session_id_claim: The claim to use for session ID extraction
            dependencies_claims: A list of claims to extract from the JWT token
        """
        super().__init__(app)
        self.secret_key = secret_key
        self.algorithm = algorithm
        self.token_prefix = token_prefix
        self.validate = validate
        self.excluded_route_paths = excluded_route_paths
        self.user_id_claim = user_id_claim
        self.session_id_claim = session_id_claim
        self.dependencies_claims = dependencies_claims or []

    async def dispatch(self, request: Request, call_next) -> Response:
        if self.excluded_route_paths and request.url.path in self.excluded_route_paths:
            return await call_next(request)

        # Extract token from Authorization header
        authorization: str = request.headers.get("Authorization", "")

        if not authorization:
            if self.validate:
                return JSONResponse(status_code=401, content={"detail": "Authorization header missing"})
            return await call_next(request)

        try:
            # Parse token
            scheme, token = authorization.split(" ", 1)
            if scheme.lower() != self.token_prefix.lower():
                if self.validate:
                    return JSONResponse(status_code=401, content={"detail": "Invalid authentication scheme"})
                return await call_next(request)

        except ValueError:
            if self.validate:
                return JSONResponse(status_code=401, content={"detail": "Invalid authorization header format"})
            return await call_next(request)

        # Decode JWT token
        try:
            payload = jwt.decode(token, self.secret_key, algorithms=[self.algorithm])

            # Extract user information
            user_id = payload.get(self.user_id_claim)
            session_id = payload.get(self.session_id_claim)

            # Extract dependency claims
            dependencies = {}
            for claim in self.dependencies_claims:
                if claim in payload:
                    dependencies[claim] = payload[claim]

            # Store everything in request state
            request.state.user_id = user_id
            request.state.session_id = session_id
            request.state.dependencies = dependencies
            request.state.authenticated = True

            log_debug(f"JWT decoded successfully for user: {user_id}")
            if dependencies:
                log_debug(f"Extracted dependencies: {dependencies}")

        except jwt.ExpiredSignatureError:
            if self.validate:
                return JSONResponse(status_code=401, content={"detail": "Token has expired"})
            request.state.authenticated = False

        except jwt.InvalidTokenError as e:
            if self.validate:
                return JSONResponse(status_code=401, content={"detail": f"Invalid token: {str(e)}"})
            request.state.authenticated = False

        return await call_next(request)