from typing import List, Optional
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

import jwt
from fastapi import Request, Response
from fastapi.responses import JSONResponse
from starlette.datastructures import FormData, MutableHeaders
from starlette.middleware.base import BaseHTTPMiddleware

from agno.utils.log import log_debug


class JWTMiddleware(BaseHTTPMiddleware):
    """
    JWT Middleware for validating tokens and automatically injecting JWT claims into endpoint parameters.

    This middleware:
    1. Extracts JWT token from Authorization header
    2. Decodes and validates the token
    3. Inspects the target endpoint function signature
    4. Automatically injects JWT claims (user_id, session_id, etc.) as request parameters
       when the endpoint accepts them and they're not already provided
    5. Stores JWT payload and authentication status in request state for backward compatibility

    Example:
        For an endpoint like `/agents/{agent_id}/runs` with `user_id: Optional[str] = Form(None)`,
        if the JWT contains `{"sub": "user_123"}` and `user_id_claim="sub"` is configured,
        the middleware will automatically inject `user_id=user_123` into the form data.
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

    def _get_endpoint_function(self, request: Request):
        """Extract the endpoint function by matching the route manually."""
        try:
            # Get the FastAPI app from the ASGI app
            app = request.scope.get("app")
            if not app or not hasattr(app, "router"):
                return None
            
            # Get the request path and method
            path = request.url.path
            method = request.method.upper()
            
            # Try to find matching route in the FastAPI router
            router = app.router
            for route in router.routes:
                if hasattr(route, "methods") and method in route.methods:
                    # Check if the path matches the route pattern
                    if hasattr(route, "path_regex") and route.path_regex:
                        match = route.path_regex.match(path)
                        if match and hasattr(route, "endpoint"):
                            return route.endpoint
                    elif hasattr(route, "path") and route.path == path:
                        if hasattr(route, "endpoint"):
                            return route.endpoint
            
            return None
        except Exception as e:
            log_debug(f"Could not extract endpoint function: {e}")
            return None

    def _get_endpoint_parameters(self, endpoint_func):
        """Get the parameter names and types from an endpoint function signature."""
        if not endpoint_func:
            return set()
        
        try:
            import inspect
            signature = inspect.signature(endpoint_func)
            return set(signature.parameters.keys())
        except Exception as e:
            log_debug(f"Could not inspect endpoint signature: {e}")
            return set()

    async def _inject_into_form_data(self, request: Request, jwt_params: dict, endpoint_params: set, has_kwargs: bool = False):
        """Inject JWT parameters directly into form data by modifying the request body."""
        # Filter parameters based on endpoint signature
        if has_kwargs:
            # If endpoint has **kwargs, it can accept any parameter
            params_to_inject = {
                param_name: str(param_value)
                for param_name, param_value in jwt_params.items()
                if param_value is not None
            }
        else:
            # Only inject parameters that the endpoint explicitly accepts
            params_to_inject = {
                param_name: str(param_value)
                for param_name, param_value in jwt_params.items()
                if param_name in endpoint_params and param_value is not None
            }
        
        if not params_to_inject:
            return
            
        try:
            content_type = request.headers.get("content-type", "")
            
            # Only inject into form data requests
            if not (content_type.startswith("multipart/form-data") or content_type.startswith("application/x-www-form-urlencoded")):
                # Try query parameters instead
                self._inject_into_query_params(request, params_to_inject)
                return
                
            # Read the current body
            body = await request.body()
            
            if content_type.startswith("application/x-www-form-urlencoded"):
                # Parse existing form data
                if body:
                    existing_data = parse_qs(body.decode('utf-8'))
                else:
                    existing_data = {}
                
                # Add JWT parameters that don't already exist
                for param_name, param_value in params_to_inject.items():
                    if param_name not in existing_data:
                        existing_data[param_name] = [param_value]
                        log_debug(f"Injecting {param_name}={param_value} into URL-encoded form data")
                
                # Reconstruct the body
                new_body = urlencode(existing_data, doseq=True).encode('utf-8')
                
                # Replace the request's receive method to return the new body
                async def new_receive():
                    return {
                        "type": "http.request",
                        "body": new_body,
                        "more_body": False,
                    }
                
                # Replace the receive method in the request scope
                request.scope["_original_receive"] = request.receive
                request._receive = new_receive
                
                print(f"New body: {new_body}")
                
            elif content_type.startswith("multipart/form-data"):
                # For multipart, we need to construct proper multipart data
                import io
                from email.mime.multipart import MIMEMultipart
                from email.mime.text import MIMEText
                
                # Parse boundary from content-type
                boundary = None
                if "boundary=" in content_type:
                    boundary = content_type.split("boundary=")[1].split(";")[0].strip()
                
                if boundary and body:
                    # Parse existing multipart data (simplified)
                    body_str = body.decode('utf-8')
                    parts = body_str.split(f"--{boundary}")
                    
                    # Reconstruct with JWT parameters
                    new_parts = []
                    existing_fields = set()
                    
                    for part in parts:
                        if "Content-Disposition:" in part and "name=" in part:
                            # Extract field name
                            name_start = part.find('name="') + 6
                            name_end = part.find('"', name_start)
                            field_name = part[name_start:name_end]
                            existing_fields.add(field_name)
                        new_parts.append(part)
                    
                    # Add JWT parameters
                    for param_name, param_value in params_to_inject.items():
                        if param_name not in existing_fields:
                            part = f'\r\nContent-Disposition: form-data; name="{param_name}"\r\n\r\n{param_value}\r\n'
                            new_parts.insert(-1, part)  # Insert before the final boundary
                            log_debug(f"Injecting {param_name}={param_value} into multipart form data")
                    
                    new_body = f"--{boundary}".join(new_parts).encode('utf-8')
                    
                    # Replace receive method
                    async def new_receive():
                        return {
                            "type": "http.request", 
                            "body": new_body,
                            "more_body": False,
                        }
                    
                    request.scope["_original_receive"] = request.receive
                    request._receive = new_receive
                else:
                    # Fallback to query parameters if multipart parsing fails
                    self._inject_into_query_params(request, params_to_inject)
                    
        except Exception as e:
            log_debug(f"Could not inject into form data: {e}")
            # Fallback to query parameters
            self._inject_into_query_params(request, params_to_inject)

    def _inject_into_query_params(self, request: Request, params_to_inject: dict):
        """Inject JWT parameters into query string."""
        if not params_to_inject:
            return
            
        try:
            # Parse current query string
            query_string = request.scope.get("query_string", b"").decode('utf-8')
            existing_params = parse_qs(query_string) if query_string else {}
            
            # Add JWT parameters that don't already exist
            modified = False
            for param_name, param_value in params_to_inject.items():
                if param_name not in existing_params:
                    existing_params[param_name] = [str(param_value)]
                    modified = True
                    log_debug(f"Injecting {param_name}={param_value} into query parameters")
            
            if modified:
                # Reconstruct query string
                new_query_string = urlencode(existing_params, doseq=True)
                request.scope["query_string"] = new_query_string.encode('utf-8')
                
        except Exception as e:
            log_debug(f"Could not inject into query parameters: {e}")

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

            # Store authentication status (minimal state storage)
            request.state.authenticated = True

            # Get the target endpoint function and its parameters
            endpoint_func = self._get_endpoint_function(request)
            print(f"Endpoint function: {endpoint_func}")
            endpoint_params = self._get_endpoint_parameters(endpoint_func)
            print(f"Endpoint parameters: {endpoint_params}")
            
            # Inject JWT values into request parameters if the endpoint accepts them
            jwt_param_mapping = {}
            if user_id is not None:
                jwt_param_mapping['user_id'] = str(user_id)
            if session_id is not None:
                jwt_param_mapping['session_id'] = str(session_id)
            if dependencies:
                import json
                jwt_param_mapping['dependencies'] = json.dumps(dependencies)

            # Inject JWT parameters directly into the request (form data or query params)
            await self._inject_into_form_data(request, jwt_param_mapping, endpoint_params)


        except jwt.ExpiredSignatureError:
            if self.validate:
                return JSONResponse(status_code=401, content={"detail": "Token has expired"})
            request.state.authenticated = False
            request.state.dependencies = {}

        except jwt.InvalidTokenError as e:
            if self.validate:
                return JSONResponse(status_code=401, content={"detail": f"Invalid token: {str(e)}"})
            request.state.authenticated = False
            request.state.dependencies = {}

        return await call_next(request)
