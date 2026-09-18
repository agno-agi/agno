"""Normalize configured MCP endpoints before authentication and public admission."""

import re
from typing import Any

from starlette._utils import get_route_path
from starlette.datastructures import Headers
from starlette.responses import JSONResponse
from starlette.routing import Match, Mount

from agno.os.config import MCP_SERVER_CARD_PATH, MCPConfig


def validate_mcp_routes(app: Any, config: MCPConfig, mcp_app: Any) -> None:
    """Reject transport paths that would hide an existing REST route."""
    # Revalidate routing settings if a caller mutated/copied the configuration.
    MCPConfig(path=config.path, path_aliases=config.path_aliases, root_host=config.root_host)
    for route in app.routes:
        if isinstance(route, Mount) and route.app is mcp_app:
            continue
        for path in [config.path, *config.path_aliases]:
            for candidate in (path, path + "/server-card"):
                match, _ = route.matches({"type": "http", "method": "GET", "path": candidate, "root_path": ""})
                if match != Match.NONE:
                    raise ValueError(f"MCP routing conflicts with existing route at {candidate}")


class MCPRoutingMiddleware:
    def __init__(self, app: Any, *, config: MCPConfig):
        self.app = app
        self.path = config.path
        self.paths = (config.path, *config.path_aliases)
        self.root_host = config.root_host

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        from agno.os.mcp import _mcp_request_hostname

        headers = Headers(scope=scope)
        hosts = headers.getlist("host")
        if len(hosts) != 1 or not re.fullmatch(r"(?:\[[0-9A-Fa-f:.]+\]|[A-Za-z0-9.-]+)(?::[0-9]{1,5})?", hosts[0]):
            await JSONResponse({"error": "invalid_host"}, status_code=400)(scope, receive, send)
            return
        # Forwarding headers never select the dedicated-host route.
        root = self.root_host is not None and _mcp_request_hostname(hosts[0]) == self.root_host
        path = get_route_path(scope).rstrip("/") or "/"
        prefixes = self.paths
        mapped = None
        if root and path in ("/", "/server-card"):
            mapped = "/mcp" if path == "/" else MCP_SERVER_CARD_PATH
        else:
            for prefix in prefixes:
                if path == prefix:
                    mapped = "/mcp"
                    break
                if path == prefix + "/server-card":
                    mapped = MCP_SERVER_CARD_PATH
                    break
        if mapped is None:
            if path in ("/mcp", MCP_SERVER_CARD_PATH):
                await JSONResponse({"error": "not_found"}, status_code=404)(scope, receive, send)
                return
            await self.app(scope, receive, send)
            return
        mount = scope.get("root_path", "").rstrip("/")
        endpoint = mount + ("/" if root else self.path)
        card = mount + ("/server-card" if root else self.path + "/server-card")
        scope = {
            **scope,
            "path": mount + mapped,
            "raw_path": (mount + mapped).encode("utf-8"),
            "_agno_mcp_public_endpoint": endpoint,
        }

        async def public_send(message):
            if message["type"] == "http.response.start":
                message = {
                    **message,
                    "headers": [
                        (
                            key,
                            card.encode("utf-8")
                            if key.lower() == b"location" and value == MCP_SERVER_CARD_PATH.encode()
                            else value,
                        )
                        for key, value in message.get("headers", [])
                    ],
                }
            await send(message)

        await self.app(scope, receive, public_send)
