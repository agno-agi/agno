from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response


class TrailingSlashMiddleware(BaseHTTPMiddleware):
    """
    Middleware that strips trailing slashes from request paths.

    This ensures that both /agents and /agents/ are handled identically
    without requiring a redirect. Updates both 'path' and 'raw_path'
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        # Get the path from the request scope
        path = request.scope.get("path", "")

        # Strip trailing slash if path is not root "/"
        if path != "/" and path.endswith("/"):
            normalized_path = path.rstrip("/")
            if normalized_path:  # Ensure we don't end up with empty path
                # Modify the scope to remove trailing slash
                request.scope["path"] = normalized_path
                # Update raw_path for ASGI spec compliance
                request.scope["raw_path"] = normalized_path.encode("utf-8")

        return await call_next(request)
