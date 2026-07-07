"""Claude Desktop adapter.

Claude Desktop reads MCP servers from claude_desktop_config.json, but that file is
stdio-only: it launches each server as a subprocess and speaks JSON-RPC over stdio, so
it cannot point at a remote HTTP AgentOS directly. The supported bridge is `mcp-remote`
(run via npx), a small stdio<->HTTP proxy that every remote-MCP vendor documents for
this client. We write an entry that launches it with the AgentOS URL and, when auth is
on, an Authorization header sourced from an env var so the token stays out of argv:

    "agno": {
      "command": "npx",
      "args": ["-y", "mcp-remote", "<url>", "--header", "Authorization:${AGNO_AUTH_HEADER}"],
      "env": {"AGNO_AUTH_HEADER": "Bearer <token>"}
    }

Config path is per-OS (macOS Application Support, Windows APPDATA, Linux ~/.config).
Because the bridge runs at Claude Desktop launch time, it needs Node/npx on PATH; connect
verifies the AgentOS endpoint itself, not that Claude can spawn npx, so a missing npx is
surfaced as a note rather than a failure.
"""

import os
import re
import shutil
import sys
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from agnoctl.clients.base import (
    ClientAdapter,
    ExistingEntry,
    WriteResult,
    bearer_header,
    read_json_lenient,
    servers_table,
    token_from_authorization,
    write_servers_entry,
)

# The env var the written entry reads the Authorization header from.
AUTH_ENV_VAR = "AGNO_AUTH_HEADER"

_ENV_REF = re.compile(r"\$\{(\w+)\}")


def _default_config_path(home: Path, platform: str) -> Path:
    if platform == "darwin":
        return home / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json"
    if platform.startswith("win"):
        appdata = os.environ.get("APPDATA")
        base = Path(appdata) if appdata else home / "AppData" / "Roaming"
        return base / "Claude" / "claude_desktop_config.json"
    return home / ".config" / "Claude" / "claude_desktop_config.json"


def _resolve_env_refs(value: str, env: Dict[str, Any]) -> str:
    """Expand ${VAR} references against the entry's own env table."""

    def repl(match: "re.Match[str]") -> str:
        replacement = env.get(match.group(1))
        return replacement if isinstance(replacement, str) else match.group(0)

    return _ENV_REF.sub(repl, value)


def _token_from_bridge(args: List[Any], env: Dict[str, Any]) -> Optional[str]:
    """Pull the bearer token out of a `--header Authorization:...` mcp-remote arg."""
    for i, arg in enumerate(args):
        if arg == "--header" and i + 1 < len(args) and isinstance(args[i + 1], str):
            name, sep, raw = args[i + 1].partition(":")
            if sep and name.strip().lower() == "authorization":
                return token_from_authorization(_resolve_env_refs(raw.strip(), env))
    return None


def _entry_from_config(entry: Any, location: str) -> Optional[ExistingEntry]:
    if not isinstance(entry, dict):
        return None
    # Forward-compatible: if a future Claude Desktop writes a native remote entry.
    url = entry.get("url")
    if isinstance(url, str) and url:
        headers = entry.get("headers")
        header_map = headers if isinstance(headers, dict) else {}
        return ExistingEntry(
            url=url, token=token_from_authorization(header_map.get("Authorization")), location=location
        )
    # The mcp-remote bridge: first http(s) arg is the AgentOS URL.
    args = entry.get("args")
    if not isinstance(args, list):
        return None
    bridge_url = next(
        (a for a in args if isinstance(a, str) and (a.startswith("http://") or a.startswith("https://"))), None
    )
    if not bridge_url:
        return None
    env = entry.get("env")
    env_map = env if isinstance(env, dict) else {}
    return ExistingEntry(url=bridge_url, token=_token_from_bridge(args, env_map), location=location)


class ClaudeDesktopAdapter(ClientAdapter):
    key = "claude-desktop"

    def __init__(
        self,
        home: Optional[Path] = None,
        config_path: Optional[Path] = None,
        platform: str = sys.platform,
        which: Callable[[str], Optional[str]] = shutil.which,
    ):
        self.home = home or Path.home()
        self._config_path = config_path or _default_config_path(self.home, platform)
        self._which = which

    @property
    def config_path(self) -> Path:
        return self._config_path

    def detect(self) -> bool:
        return self.config_path.exists() or self.config_path.parent.is_dir()

    def read_existing(self, server_name: str) -> Optional[ExistingEntry]:
        config = read_json_lenient(self.config_path)
        if config is None:
            return None
        return _entry_from_config(servers_table(config).get(server_name), str(self.config_path))

    def write(self, server_name: str, url: str, token: Optional[str]) -> WriteResult:
        args: List[str] = ["-y", "mcp-remote", url]
        entry: Dict[str, Any] = {"command": "npx", "args": args}
        if token:
            args += ["--header", "Authorization:${" + AUTH_ENV_VAR + "}"]
            entry["env"] = {AUTH_ENV_VAR: bearer_header(token)}
        write_servers_entry(self.config_path, server_name, entry, secure=bool(token), mkdir=True)

        note = None
        if self._which("npx") is None:
            note = (
                "Claude Desktop launches this server with 'npx mcp-remote'; install Node.js/npx or it will not start."
            )
        return WriteResult(method="file", location=str(self.config_path), note=note)
