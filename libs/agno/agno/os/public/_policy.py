"""Route selection shared by public admission and optional JWT authentication."""

import re
from typing import Any

from starlette.routing import Match

RUN_ROUTE = re.compile(r"^/(agents|teams|workflows)/([^/]+)/runs(?:/([^/]+)(/cancel)?)?$")


class PublicRoutePolicy:
    def __init__(self, surface: Any, agent_os: Any):
        self.authenticated_api = bool(getattr(agent_os, "authorization", False))
        self.selected = {
            kind: {component.id for component in getattr(surface, kind)} for kind in ("agents", "teams", "workflows")
        }
        self.mcp = surface.mcp
        self.oauth_paths = agent_os.mcp_auth_exempt_paths() if surface.mcp else []

    def is_mcp(self, path: str) -> bool:
        return path == "/mcp" or path.startswith("/mcp/") or path in self.oauth_paths

    def allows_authenticated_websocket(self, scope: Any) -> bool:
        # A custom base-app route can take precedence over Agno's workflow socket.
        # Only the native handler guarantees authentication before any operation.
        from agno.os.utils import flatten_routes

        for route in scope["app"].routes:
            match, _ = route.matches(scope)
            if match == Match.FULL:
                # New FastAPI versions retain an included router as a branch.
                # The native socket is registered in its own one-endpoint router.
                candidates = flatten_routes([route])
                return len(candidates) == 1 and bool(
                    getattr(getattr(candidates[0], "endpoint", None), "_agno_authenticated_workflow_socket", False)
                )
        return False

    def allows_anonymous(self, method: str, path: str) -> bool:
        if path in ("/", "/health") and method in ("GET", "HEAD"):
            return True
        if method == "GET" and path in ("/readyz", "/agents", "/teams"):
            return True
        if self.authenticated_api and method == "GET" and path == "/info":
            return True
        if self.mcp and path in ("/mcp", "/mcp/server-card"):
            return True  # MCP transport and any OAuth provider enforce their own methods/authentication.
        match = RUN_ROUTE.fullmatch(path)
        if method != "POST" or match is None:
            return False
        kind, component_id, run_id, cancellation = match.groups()
        return (
            kind in ("agents", "teams")
            and component_id in self.selected[kind]
            and (run_id is None or cancellation is not None)
        )
