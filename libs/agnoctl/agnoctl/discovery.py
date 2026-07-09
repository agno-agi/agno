"""AgentOS discovery: find a running OS and learn its capabilities before touching it.

Prefers the structured discovery fields on GET /info (agno >= the /info discovery release):
``mcp: {enabled, path}`` and ``auth_mode``. Falls back to probing for older servers:
POST to /mcp distinguishes mounted-vs-404, and an unauthenticated GET /config
distinguishes the auth modes by status code and 401 detail wording.
"""

import ipaddress
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urlsplit

import httpx

from agnoctl.errors import CLIError
from agnoctl.http import AgentOSAPI, build_client

# Discovery probes short-circuit on dead hosts; a stale remote AGENTOS_URL should cost
# seconds, not the full API timeout, on every invocation.
DISCOVERY_TIMEOUT = 5.0

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


def _is_loopback_host(host: Optional[str]) -> bool:
    """True for hosts that never leave the machine: localhost, 127.0.0.0/8, ::1, and the
    unspecified addresses (0.0.0.0, ::) that dev servers bind to."""
    if not host:
        return False
    if host.lower() == "localhost":
        return True
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False
    return ip.is_loopback or ip.is_unspecified


# Project env files scanned for AGENTOS_URL when it is not already in the process
# environment, so `agno connect` targets a deployed OS whose URL the deploy scripts
# persisted (to .env.production) without needing --url. Preferred order: production first.
ENV_FILES = (".env.production", ".env")


@dataclass
class McpOAuth:
    """OAuth discovery details served on /info when AgentOS(mcp_auth=...) protects /mcp."""

    authorization_servers: List[str] = field(default_factory=list)
    resource: Optional[str] = None

    def public_dict(self) -> Dict[str, Any]:
        return {"authorization_servers": self.authorization_servers, "resource": self.resource}


@dataclass
class OSInfo:
    base_url: str
    version: Optional[str]
    mcp_enabled: bool
    mcp_path: Optional[str]
    auth_mode: str  # REST/WS plane only: "none" | "security_key" | "jwt" | "unknown"; MCP OAuth is signaled by `oauth`
    discovered_via: str  # "info" | "probe"
    url_source: str = "default"  # "flag" | "env" | "env-file" | "client-config" | "default"
    # Provenance detail: the env file AGENTOS_URL came from ("env-file"), or the client
    # display names whose configs point at this OS ("client-config").
    url_source_file: Optional[str] = None
    name: Optional[str] = None  # AgentOS(name=...), served on /info by agno >= 2.8; None on older servers
    os_id: Optional[str] = None
    oauth: Optional[McpOAuth] = None  # set when the MCP endpoint is OAuth-protected

    @property
    def oauth_enabled(self) -> bool:
        """Whether /mcp is OAuth-protected AND apps can actually sign in: the OS must
        advertise at least one authorization server, or there is nothing to sign in
        through. A provider with none (e.g. a bare fastmcp TokenVerifier as mcp_auth)
        still serves an mcp.oauth block, but its bearers are issued out of band, so
        connect treats it like any other token-protected endpoint. auth_mode plays no
        part here: it describes the REST/WS plane, which is independent of /mcp."""
        return self.oauth is not None and bool(self.oauth.authorization_servers)

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
            "name": self.name,
            "os_id": self.os_id,
            "version": self.version,
            "mcp": {
                "enabled": self.mcp_enabled,
                "path": self.mcp_path,
                "oauth": self.oauth.public_dict() if self.oauth is not None else None,
            },
            "auth_mode": self.auth_mode,
            "discovered_via": self.discovered_via,
            "url_source": self.url_source,
            "url_source_file": self.url_source_file,
        }

    def source_note(self) -> str:
        """Provenance suffix like ' (from AGENTOS_URL in .env.production)' for messages."""
        return _source_note(self.url_source, self.url_source_file)


def _read_env_value(path: Path, key: str) -> Optional[str]:
    """Read a single ``KEY=value`` from a .env-style file. No dotenv dependency: agnoctl
    parses only what it needs and never loads the file into the process environment.
    Tolerates an ``export `` prefix, surrounding quotes, blank lines, and ``#`` comments;
    the last uncommented assignment wins. Returns None if absent or unreadable."""
    try:
        # utf-8-sig transparently drops a UTF-8 BOM (some Windows editors add one); catching
        # UnicodeDecodeError keeps a binary/other-encoding file from crashing discovery.
        text = path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeDecodeError):
        return None
    found: Optional[str] = None
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export ") or line.startswith("export\t"):
            line = line[len("export") :].lstrip()
        name, sep, value = line.partition("=")
        if not sep or name.strip() != key:
            continue
        value = value.strip()
        if value[:1] in ("'", '"'):
            # Quoted value: take what's inside the matching quote and ignore any trailing
            # inline comment. An unterminated quote is left as-is (a malformed line).
            end = value.find(value[0], 1)
            if end != -1:
                value = value[1:end]
        else:
            # Unquoted value: an inline comment starts at the first '#' preceded by
            # whitespace ("host  # note"); a '#' with no leading space is a literal (a URL
            # fragment) and is kept.
            for i in range(1, len(value)):
                if value[i] == "#" and value[i - 1] in " \t":
                    value = value[:i].rstrip()
                    break
        # The last assignment wins, including an empty one that clears an earlier value.
        found = value or None
    return found


def _agentos_url_from_env_files() -> "tuple[Optional[str], Optional[str]]":
    """AGENTOS_URL from a project env file (.env.production preferred, then .env), read
    from the current working directory. Returns (url, filename) or (None, None)."""
    try:
        cwd = Path.cwd()
    except OSError:
        # The working directory was deleted out from under us; treat as "no env file".
        return None, None
    for name in ENV_FILES:
        value = _read_env_value(cwd / name, URL_ENV_VAR)
        if value:
            url = value.rstrip("/")
            if url:  # a slash-only value ("/") normalizes to "" -- skip it and try the next file
                return url, name
    return None, None


def _dedup_key(url: str) -> "tuple[str, str, Optional[str]]":
    """Key under which two candidate URLs mean the same server. Loopback aliases
    (localhost vs 127.0.0.1) collapse, so an env-file URL for a local server does not
    make the same OS show up twice."""
    try:
        parts = urlsplit(url)
        host = "loopback" if _is_loopback_host(parts.hostname) else (parts.hostname or url)
        port = str(parts.port) if parts.port is not None else ""
    except ValueError:
        return "", url, None
    return parts.scheme.lower(), host, port


def _candidate_sources(url: Optional[str]) -> "List[tuple[str, str, Optional[str]]]":
    """Every (url, source, source_file) discovery should consider, in priority order.

    An explicit --url or an exported AGENTOS_URL is a deliberate, single target. An
    AGENTOS_URL read from an ambient env file is different: a deploy script persisting
    the production URL to .env.production must not make a locally running AgentOS
    undiscoverable, so the env-file URL and the localhost defaults coexist.
    """
    if url:
        return [(url.rstrip("/"), "flag", None)]
    env_url = os.environ.get(URL_ENV_VAR)
    if env_url:
        return [(env_url.rstrip("/"), "env", None)]
    sources: "List[tuple[str, str, Optional[str]]]" = []
    seen = set()
    file_url, file_name = _agentos_url_from_env_files()
    if file_url:
        sources.append((file_url, "env-file", file_name))
        seen.add(_dedup_key(file_url))
    for default_url in DEFAULT_URLS:
        if _dedup_key(default_url) not in seen:
            sources.append((default_url, "default", None))
    return sources


def _primary_sources(url: Optional[str]) -> "List[tuple[str, str, Optional[str]]]":
    """The highest-priority source's candidates only: the single-target view used by
    discover(). An ambient env-file URL is authoritative here -- localhost is not
    probed behind it -- which keeps tokens/status pinned to one deterministic target."""
    sources = _candidate_sources(url)
    primary = sources[0][1]
    return [s for s in sources if s[1] == primary]


def _candidate_urls(url: Optional[str]) -> "tuple[List[str], str, Optional[str]]":
    sources = _primary_sources(url)
    return [s[0] for s in sources], sources[0][1], sources[0][2]


def _source_note(url_source: str, url_source_file: Optional[str]) -> str:
    """A short '(from AGENTOS_URL ...)' provenance suffix for user-facing messages."""
    if url_source == "env-file" and url_source_file:
        return " (from AGENTOS_URL in " + url_source_file + ")"
    if url_source == "env":
        return " (from AGENTOS_URL)"
    if url_source == "client-config" and url_source_file:
        return " (configured in " + url_source_file + ")"
    return ""


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


def _str_or_none(value: Any) -> Optional[str]:
    return value if isinstance(value, str) and value else None


def _parse_mcp_oauth(mcp_field: Dict[str, Any]) -> Optional[McpOAuth]:
    """The /info mcp.oauth object, when the server advertises OAuth on /mcp."""
    raw = mcp_field.get("oauth")
    if not isinstance(raw, dict):
        return None
    servers = raw.get("authorization_servers")
    return McpOAuth(
        authorization_servers=[s for s in servers if isinstance(s, str)] if isinstance(servers, list) else [],
        resource=_str_or_none(raw.get("resource")),
    )


def _probe_candidate(candidate: str, url_source: str, url_source_file: Optional[str]) -> Optional[OSInfo]:
    """Probe one candidate URL; an OSInfo when a live AgentOS answers, else None."""
    try:
        api = AgentOSAPI(candidate, timeout=DISCOVERY_TIMEOUT)
    except httpx.InvalidURL as e:
        # A user-supplied URL (flag/env/env-file) that httpx cannot parse -- e.g. an
        # un-expanded "${PORT}" or a typo'd port. Fail clearly, not with a traceback.
        raise CLIError(
            "Invalid AgentOS URL: " + candidate + _source_note(url_source, url_source_file) + ".",
            hint="Fix the URL" + (" in " + url_source_file if url_source_file else "") + " or pass --url.",
        ) from e
    with api:
        if api.health() is None:
            return None
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
                name=_str_or_none(info.get("name")),
                os_id=_str_or_none(info.get("os_id")),
                oauth=_parse_mcp_oauth(mcp_field),
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


def _no_os_error(sources: "List[tuple[str, str, Optional[str]]]") -> CLIError:
    """The "nothing answered" error, with each tried URL annotated with its own provenance."""
    tried = ", ".join(url + _source_note(source, source_file) for url, source, source_file in sources)
    env_file_sources = [s for s in sources if s[1] == "env-file"]
    if env_file_sources:
        hint = (
            "The URL came from AGENTOS_URL in "
            + (env_file_sources[0][2] or "an env file")
            + " in this directory -- fix or remove it, pass --url, or start your AgentOS (agent_os.serve())."
        )
    else:
        hint = (
            "Start your AgentOS (agent_os.serve()), pass --url, or set "
            + URL_ENV_VAR
            + " (in your shell or a .env.production / .env file)."
        )
    return CLIError("No running AgentOS found (tried: " + tried + ").", hint=hint)


def discover(url: Optional[str] = None) -> OSInfo:
    """Find a running AgentOS and return what the CLI needs to know about it.

    Single-target: only the highest-priority source is probed, and the first live
    candidate wins. Non-interactive connect/disconnect runs use this too, so automation
    always resolves the same deterministic target and a dead env-file OS stays a hard
    failure instead of silently falling through to a different server.
    """
    sources = _primary_sources(url)
    for candidate, url_source, url_source_file in sources:
        os_info = _probe_candidate(candidate, url_source, url_source_file)
        if os_info is not None:
            return os_info
    raise _no_os_error(sources)


def discover_all(
    url: Optional[str] = None,
    extra_sources: Optional["List[tuple[str, str, Optional[str]]]"] = None,
) -> List[OSInfo]:
    """Every running AgentOS among the candidate sources, in priority order.

    Unlike discover(), an ambient env-file URL does not short-circuit the localhost
    defaults: all candidates are probed and every live one is returned, so an
    interactive caller can offer a choice. ``extra_sources`` are additional
    (url, source, note) candidates -- e.g. OSes the client configs already point at --
    probed after the standard ones and deduped against them; they are ignored when an
    explicit --url or exported AGENTOS_URL names a deliberate single target. Raises
    the same "no running AgentOS" CLIError when none answer.
    """
    sources = list(_candidate_sources(url))
    if extra_sources and sources[0][1] not in ("flag", "env"):
        seen = {_dedup_key(candidate) for candidate, _, _ in sources}
        for candidate, url_source, url_source_file in extra_sources:
            if _dedup_key(candidate) not in seen:
                seen.add(_dedup_key(candidate))
                sources.append((candidate.rstrip("/"), url_source, url_source_file))
    found: List[OSInfo] = []
    for candidate, url_source, url_source_file in sources:
        os_info = _probe_candidate(candidate, url_source, url_source_file)
        if os_info is not None:
            found.append(os_info)
    if not found:
        raise _no_os_error(sources)
    return found


MCP_ENABLE_INSTRUCTIONS = """MCP is not enabled on this AgentOS. Enable it and restart:

    agent_os = AgentOS(
        agents=[...],
        mcp_server=True,  # add this line
    )
"""
