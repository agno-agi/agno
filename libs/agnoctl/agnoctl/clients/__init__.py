"""Client adapters: how each coding agent stores MCP server configuration."""

from pathlib import Path
from typing import Dict, Optional

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
