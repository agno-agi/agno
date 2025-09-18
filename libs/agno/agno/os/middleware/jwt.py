from typing import Any, Dict, List, Optional

from fastapi.responses import JSONResponse
import jwt
from fastapi import Request, Response
from fastapi.exceptions import HTTPException
from starlette.middleware.base import BaseHTTPMiddleware

from agno.utils.log import log_debug


class JWTMiddleware(BaseHTTPMiddleware):
    """
    JWT Middleware for validating tokens and extracting user information from JWT tokens.

    This middleware:
    1. Extracts JWT token from Authorization header
    2. Decodes and validates the token
    3. Extracts user_id and other claims
    4. Adds them to request state for use in routes
    """

    def __init__(
        self,
        app,
        secret_key: str,
        algorithm: str = "HS256",
        token_prefix: str = "Bearer",
        user_id_claim: str = "user_id",
        validate_token: bool = True,
        excluded_route_paths: Optional[List[str]] = None,
    ):
        super().__init__(app)
        self.secret_key = secret_key
        self.algorithm = algorithm
        self.token_prefix = token_prefix
        self.user_id_claim = user_id_claim
        self.validate_token = validate_token
        self.excluded_route_paths = excluded_route_paths
        
    async def dispatch(self, request: Request, call_next) -> Response:
        if self.excluded_route_paths and request.url.path in self.excluded_route_paths:
            return await call_next(request)
        
        # Extract token from Authorization header
        authorization: str = request.headers.get("Authorization", "")

        if not authorization:
            if self.validate_token:
                return JSONResponse(status_code=401, content={"detail": "Authorization header missing"})
            return await call_next(request)

        try:
            # Parse token
            scheme, token = authorization.split(" ", 1)
            if scheme.lower() != self.token_prefix.lower():
                if self.validate_token:
                    return JSONResponse(status_code=401, content={"detail": "Invalid authentication scheme"})
                return await call_next(request)

        except ValueError:
            if self.validate_token:
                return JSONResponse(status_code=401, content={"detail": "Invalid authorization header format"})
            return await call_next(request)

        # Decode JWT token
        try:
            payload = jwt.decode(token, self.secret_key, algorithms=[self.algorithm])

            # Extract user information
            user_id = payload.get(self.user_id_claim)

            # Add to request state
            request.state.jwt_payload = payload
            request.state.user_id = user_id
            request.state.authenticated = True

            log_debug(f"JWT decoded successfully for user: {user_id}")

        except jwt.ExpiredSignatureError:
            if self.validate_token:
                return JSONResponse(status_code=401, content={"detail": "Token has expired"})
            request.state.authenticated = False

        except jwt.InvalidTokenError as e:
            if self.validate_token:
                return JSONResponse(status_code=401, content={"detail": f"Invalid token: {str(e)}"})
            request.state.authenticated = False

        return await call_next(request)


# Helper functions
def get_current_user_id(request: Request) -> Optional[str]:
    """Helper function to get current user ID from request."""
    return getattr(request.state, "user_id", None)


def get_jwt_payload(request: Request) -> Optional[Dict[str, Any]]:
    """Helper function to get full JWT payload from request."""
    return getattr(request.state, "jwt_payload", None)


def is_authenticated(request: Request) -> bool:
    """Helper function to check if request is authenticated."""
    return getattr(request.state, "authenticated", False)
