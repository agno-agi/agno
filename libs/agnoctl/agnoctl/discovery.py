"""AgentOS discovery: find a running OS and learn its capabilities before touching it.

Prefers the structured discovery fields on GET /info (agno >= the /info discovery release):
``mcp: {enabled, path}`` and ``auth_mode``. Falls back to probing for older servers:
POST to /mcp distinguishes mounted-vs-404, and an unauthenticated GET /config
distinguishes the auth modes by status code and 401 detail wording.
"""

import os
from dataclasses import dataclass
from pathlib import Path
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

# Project env files scanned for AGENTOS_URL when it is not already in the process
# environment, so `agno connect` targets a deployed OS whose URL the deploy scripts
# persisted (to .env.production) without needing --url. Preferred order: production first.
ENV_FILES = (".env.production", ".env")


@dataclass
class OSInfo:
    base_url: str
    version: Optional[str]
    mcp_enabled: bool
    mcp_path: Optional[str]
    auth_mode: str  # "none" | "security_key" | "jwt" | "unknown"
    discovered_via: str  # "info" | "probe"
    url_source: str = "default"  # "flag" | "env" | "env-file" | "default"
    url_source_file: Optional[str] = None  # env file AGENTOS_URL came from, when url_source == "env-file"

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
            "url_source_file": self.url_source_file,
        }


def _read_env_value(path: Path, key: str) -> Optional[str]:
    """Read a single ``KEY=value`` from a .env-style file. No dotenv dependency: agnoctl
    parses only what it needs and never loads the file into the process environment.
    Tolerates an ``export `` prefix, surrounding quotes, blank lines, and ``#`` comments;
    the last uncommented assignment wins. Returns None if absent or unreadable."""
    try:
        text = path.read_text()
    except OSError:
        return None
    found: Optional[str] = None
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].lstrip()
        name, sep, value = line.partition("=")
        if not sep or name.strip() != key:
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        if value:
            found = value  # keep scanning: a later assignment overrides an earlier one
    return found


def _agentos_url_from_env_files() -> "tuple[Optional[str], Optional[str]]":
    """AGENTOS_URL from a project env file (.env.production preferred, then .env), read
    from the current working directory. Returns (url, filename) or (None, None)."""
    for name in ENV_FILES:
        value = _read_env_value(Path.cwd() / name, URL_ENV_VAR)
        if value:
            return value.rstrip("/"), name
    return None, None


def _candidate_urls(url: Optional[str]) -> "tuple[List[str], str, Optional[str]]":
    if url:
        return [url.rstrip("/")], "flag", None
    env_url = os.environ.get(URL_ENV_VAR)
    if env_url:
        return [env_url.rstrip("/")], "env", None
    file_url, file_name = _agentos_url_from_env_files()
    if file_url:
        return [file_url], "env-file", file_name
    return list(DEFAULT_URLS), "default", None


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
    candidates, url_source, url_source_file = _candidate_urls(url)
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
                    url_source_file=url_source_file,
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
                url_source_file=url_source_file,
            )

    tried = ", ".join(candidates)
    raise CLIError(
        "No running AgentOS found (tried: " + tried + ").",
        hint="Start your AgentOS (agent_os.serve()), pass --url, or set "
        + URL_ENV_VAR
        + " (in your shell or a .env.production / .env file).",
    )


MCP_ENABLE_INSTRUCTIONS = """MCP is not enabled on this AgentOS. Enable it and restart:

    agent_os = AgentOS(
        agents=[...],
        enable_mcp_server=True,  # add this line
    )
"""
