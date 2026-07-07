"""AgentOS discovery: find a running OS and learn its capabilities before touching it.

Prefers the structured discovery fields on GET /info (agno >= the /info discovery release):
``mcp: {enabled, path}`` and ``auth_mode``. Falls back to probing for older servers:
POST to /mcp distinguishes mounted-vs-404, and an unauthenticated GET /config
distinguishes the auth modes by status code and 401 detail wording.
"""

import os
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import httpx

from agnoctl.errors import CLIError
from agnoctl.http import AgentOSAPI, build_client

# AgentOS.serve() defaults to port 7777; when that is taken, users commonly bump to
# 7778/7779, and 8000 covers a bare-uvicorn setup. All are probed on localhost when no
# --url / AGENTOS_URL is given. A server on any other port needs --url or AGENTOS_URL
# (the "no running AgentOS found" error names both).
DEFAULT_URLS = [
    "http://localhost:7777",
    "http://localhost:7778",
    "http://localhost:7779",
    "http://localhost:8000",
]

URL_ENV_VAR = "AGENTOS_URL"


@dataclass
class OSInfo:
    base_url: str
    version: Optional[str]
    mcp_enabled: bool
    mcp_path: Optional[str]
    auth_mode: str  # "none" | "security_key" | "jwt" | "unknown"
    discovered_via: str  # "info" | "probe"
    url_source: str = "default"  # "flag" | "env" | "default"

    @property
    def mcp_url(self) -> str:
        path = self.mcp_path or "/mcp"
        # A server may advertise its MCP path without a leading slash ("mcp",
        # "custom/mcp"); normalize so we never build "http://hostmcp".
        if not path.startswith("/"):
            path = "/" + path
        return self.base_url.rstrip("/") + path

    def public_dict(self) -> Dict[str, Any]:
        return {
            "url": self.base_url,
            "version": self.version,
            "mcp": {"enabled": self.mcp_enabled, "path": self.mcp_path},
            "auth_mode": self.auth_mode,
            "discovered_via": self.discovered_via,
            "url_source": self.url_source,
        }


def _candidate_urls(url: Optional[str]) -> "tuple[List[str], str]":
    if url:
        return [url.rstrip("/")], "flag"
    env_url = os.environ.get(URL_ENV_VAR)
    if env_url:
        return [env_url.rstrip("/")], "env"
    return list(DEFAULT_URLS), "default"


def _probe_mcp(base_url: str) -> bool:
    """True when something MCP-shaped is mounted at /mcp.

    A FastAPI app without the MCP mount returns 404 for any method on /mcp; the
    streamable-HTTP endpoint answers POSTs with anything but 404 (200, 400, 401, 406...).
    """
    try:
        with build_client(base_url=base_url, timeout=5.0) as client:
            response = client.post(
                "/mcp",
                json={"jsonrpc": "2.0", "id": 0, "method": "ping"},
                headers={"Accept": "application/json, text/event-stream"},
            )
    except httpx.HTTPError:
        return False
    return response.status_code != 404


def discover(url: Optional[str] = None) -> OSInfo:
    """Find a running AgentOS and return what the CLI needs to know about it."""
    candidates, url_source = _candidate_urls(url)
    for candidate in candidates:
        with AgentOSAPI(candidate) as api:
            if api.health() is None:
                continue
            info = api.info() or {}

            mcp_field = info.get("mcp")
            auth_mode = info.get("auth_mode")
            if isinstance(mcp_field, dict) and isinstance(auth_mode, str):
                return OSInfo(
                    base_url=candidate,
                    version=info.get("agno_version"),
                    mcp_enabled=bool(mcp_field.get("enabled")),
                    mcp_path=mcp_field.get("path") or ("/mcp" if mcp_field.get("enabled") else None),
                    auth_mode=auth_mode,
                    discovered_via="info",
                    url_source=url_source,
                )

            mcp_enabled = _probe_mcp(candidate)
            return OSInfo(
                base_url=candidate,
                version=info.get("agno_version"),
                mcp_enabled=mcp_enabled,
                mcp_path="/mcp" if mcp_enabled else None,
                auth_mode=api.probe_auth_mode(),
                discovered_via="probe",
                url_source=url_source,
            )

    tried = ", ".join(candidates)
    raise CLIError(
        "No running AgentOS found (tried: " + tried + ").",
        hint="Start your AgentOS (agent_os.serve()) or pass --url / set " + URL_ENV_VAR + ".",
    )


MCP_ENABLE_INSTRUCTIONS = """MCP is not enabled on this AgentOS. Enable it and restart:

    agent_os = AgentOS(
        agents=[...],
        enable_mcp_server=True,  # add this line
    )
"""
