from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response


class TrailingSlashMiddleware(BaseHTTPMiddleware):
    """
    Middleware that strips trailing slashes from request paths.

    This ensures that both /agents and /agents/ are handled identically
    without requiring a redirect.
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        # Get the path from the request scope
        path = request.scope.get("path", "")

        # Strip trailing slash if path is not root "/"
        if path != "/" and path.endswith("/"):
            # Modify the scope to remove trailing slash
            request.scope["path"] = path.rstrip("/")

        return await call_next(request)
