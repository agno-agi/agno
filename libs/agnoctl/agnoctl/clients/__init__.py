"""Client adapters: how each coding agent stores MCP server configuration."""

from pathlib import Path
from typing import Dict, List, Optional, Tuple
from urllib.parse import urlsplit, urlunsplit

from agnoctl.clients.base import ClientAdapter, ExistingEntry, WriteResult
from agnoctl.clients.claude_code import ClaudeCodeAdapter
from agnoctl.clients.claude_desktop import ClaudeDesktopAdapter
from agnoctl.clients.codex import CodexAdapter
from agnoctl.clients.cursor import CursorAdapter

# Accepted spellings for --clients, mapped to canonical adapter keys. "claude" stays
# bound to Claude Code (the coding agent); the desktop app is claude-desktop.
CLIENT_ALIASES = {
    "claude": "claude-code",
    "claude-code": "claude-code",
    "claude-desktop": "claude-desktop",
    "claude-app": "claude-desktop",
    "codex": "codex",
    "cursor": "cursor",
}

# Human-facing names for report lines and restart hints; JSON output keeps the raw keys.
CLIENT_DISPLAY_NAMES = {
    "claude-code": "Claude Code",
    "claude-desktop": "Claude Desktop",
    "codex": "Codex",
    "cursor": "Cursor",
}


def display_name(client_key: str) -> str:
    return CLIENT_DISPLAY_NAMES.get(client_key, client_key)


def build_adapters(
    home: Optional[Path] = None,
    cwd: Optional[Path] = None,
    project: bool = False,
) -> Dict[str, ClientAdapter]:
    """All known adapters keyed by canonical client key."""
    claude_scope = "project" if project else "user"
    return {
        "claude-code": ClaudeCodeAdapter(home=home, cwd=cwd, scope=claude_scope),
        "claude-desktop": ClaudeDesktopAdapter(home=home),
        "codex": CodexAdapter(home=home),
        "cursor": CursorAdapter(home=home, cwd=cwd, project=project),
    }


def _base_url_of_entry(entry_url: str) -> Optional[str]:
    """The AgentOS base URL behind an MCP entry, or None when it cannot be derived.

    connect always writes ``<base>/mcp`` (including path-routed deployments like
    ``https://host/team1/mcp``), so stripping the final ``/mcp`` segment recovers the
    base. Entries with any other path shape are not ours to reinterpret.
    """
    parts = urlsplit(entry_url)
    if parts.scheme.lower() not in ("http", "https") or not parts.netloc:
        return None
    path = parts.path.rstrip("/")
    if not path.endswith("/mcp"):
        return None
    return urlunsplit((parts.scheme, parts.netloc, path[: -len("/mcp")], "", "")).rstrip("/")


def configured_sources(adapters: Dict[str, ClientAdapter]) -> List[Tuple[str, str, Optional[str]]]:
    """Discovery candidates for every AgentOS the local client configs already point at.

    The client configs are the one durable record of previously connected OSes (there
    is no other memory), so the interactive picker offers them alongside the ambient
    env-file URL and the localhost defaults. Returns (base_url, "client-config",
    "<display names>") tuples; a corrupt config never breaks discovery.
    """
    found: Dict[str, List[str]] = {}
    for adapter in adapters.values():
        try:
            entries = adapter.list_entries()
        except Exception:
            continue
        for entry in entries.values():
            base = _base_url_of_entry(entry.url)
            if base is None:
                continue
            names = found.setdefault(base, [])
            if display_name(adapter.key) not in names:
                names.append(display_name(adapter.key))
    return [(base, "client-config", ", ".join(names)) for base, names in found.items()]
