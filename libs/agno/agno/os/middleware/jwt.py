import jwt
from typing import Optional, Dict, Any, List
from fastapi import HTTPException, Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
import logging

logger = logging.getLogger(__name__)


class JWTMiddleware(BaseHTTPMiddleware):
    """
    JWT Middleware for extracting user information from JWT tokens.
    
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
        optional_routes: Optional[List[str]] = None,
        user_id_claim: str = "user_id",
        auto_error: bool = False,
    ):
        super().__init__(app)
        self.secret_key = secret_key
        self.algorithm = algorithm
        self.token_prefix = token_prefix
        self.optional_routes = optional_routes or []
        self.user_id_claim = user_id_claim
        self.auto_error = auto_error

    async def dispatch(self, request: Request, call_next) -> Response:
        # Check if this route should skip JWT validation
        path = request.url.path
        if self._should_skip_route(path):
            return await call_next(request)

        # Extract token from Authorization header
        authorization: str = request.headers.get("Authorization", "")
        
        if not authorization:
            if self.auto_error:
                raise HTTPException(status_code=401, detail="Authorization header missing")
            return await call_next(request)

        try:
            # Parse token
            scheme, token = authorization.split(" ", 1)
            if scheme.lower() != self.token_prefix.lower():
                if self.auto_error:
                    raise HTTPException(status_code=401, detail="Invalid authentication scheme")
                return await call_next(request)

        except ValueError:
            if self.auto_error:
                raise HTTPException(status_code=401, detail="Invalid authorization header format")
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
            
            logger.debug(f"JWT decoded successfully for user: {user_id}")
            
        except jwt.ExpiredSignatureError:
            if self.auto_error:
                raise HTTPException(status_code=401, detail="Token has expired")
            request.state.authenticated = False
            
        except jwt.InvalidTokenError as e:
            if self.auto_error:
                raise HTTPException(status_code=401, detail=f"Invalid token: {str(e)}")
            request.state.authenticated = False
            
        return await call_next(request)


def get_current_user_id(request: Request) -> Optional[str]:
    """
    Helper function to get current user ID from request.
    Use this in your route handlers.
    """
    return getattr(request.state, "user_id", None)


def get_jwt_payload(request: Request) -> Optional[Dict[str, Any]]:
    """
    Helper function to get full JWT payload from request.
    Use this in your route handlers.
    """
    return getattr(request.state, "jwt_payload", None)


def is_authenticated(request: Request) -> bool:
    """
    Helper function to check if request is authenticated.
    Use this in your route handlers.
    """
    return getattr(request.state, "authenticated", False)