"""Claude Code adapter.

Write path depends on whether the entry carries a token. A token on `claude mcp add`'s
argv would be visible in the local process list (and captured by execve audit logs), so a
token-bearing entry is written to the config file directly at 0600 — ~/.claude.json (user
scope) or <cwd>/.mcp.json (project scope). A tokenless entry goes through the `claude mcp
add` CLI (the sanctioned interface; it owns config placement) when the binary is present,
falling back to the same file write otherwise.

Reads follow Claude Code's same-name resolution precedence: local scope
(~/.claude.json projects.<cwd>.mcpServers) > project (.mcp.json) > user
(~/.claude.json mcpServers). Getting this order right matters: the entry this
adapter reports is the one Claude Code will actually use, which is how connect
detects stale shadowing entries after a write.

After the write, connect reads the entry back and re-verifies it, so a write that did not
take effect (or a shadowing entry) is reported, never assumed.
"""

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from agnoctl.clients.base import (
    ClientAdapter,
    ExistingEntry,
    RemoveResult,
    UrlMatcher,
    WriteResult,
    atomic_write_text,
    bearer_header,
    pop_server_entry,
    read_json_lenient,
    read_json_strict,
    remove_servers_entry,
    servers_table,
    token_from_authorization,
    write_servers_entry,
)
from agnoctl.errors import CLIError

SUBPROCESS_TIMEOUT = 60.0


def _entry_from_servers(servers: Dict[str, Any], server_name: str, location: str) -> Optional[ExistingEntry]:
    entry = servers.get(server_name)
    if not isinstance(entry, dict):
        return None
    url = entry.get("url")
    if not isinstance(url, str) or not url:
        return None
    headers = entry.get("headers")
    if not isinstance(headers, dict):
        headers = {}
    return ExistingEntry(url=url, token=token_from_authorization(headers.get("Authorization")), location=location)


class ClaudeCodeAdapter(ClientAdapter):
    key = "claude-code"

    def __init__(
        self,
        home: Optional[Path] = None,
        cwd: Optional[Path] = None,
        scope: str = "user",
        which: Callable[[str], Optional[str]] = shutil.which,
        runner: Callable[..., "subprocess.CompletedProcess[str]"] = subprocess.run,
    ):
        self.home = home or Path.home()
        self.cwd = cwd or Path.cwd()
        self.scope = scope
        self._which = which
        self._runner = runner

    @property
    def _user_config_path(self) -> Path:
        return self.home / ".claude.json"

    @property
    def _project_config_path(self) -> Path:
        return self.cwd / ".mcp.json"

    def detect(self) -> bool:
        return self._which("claude") is not None or self._user_config_path.exists()

    def _scoped_servers(self) -> "List[tuple[Dict[str, Any], str]]":
        """(servers table, location label) per scope, in Claude Code's resolution
        precedence: local (~/.claude.json projects.<cwd>) > project (.mcp.json) > user
        (~/.claude.json mcpServers)."""
        scopes: "List[tuple[Dict[str, Any], str]]" = []
        user_config = read_json_lenient(self._user_config_path)
        if user_config:
            projects = user_config.get("projects")
            if isinstance(projects, dict):
                project = projects.get(str(self.cwd))
                if isinstance(project, dict):
                    scopes.append((servers_table(project), str(self._user_config_path) + " (local scope)"))
        project_config = read_json_lenient(self._project_config_path)
        if project_config:
            scopes.append((servers_table(project_config), str(self._project_config_path)))
        if user_config:
            scopes.append((servers_table(user_config), str(self._user_config_path) + " (user scope)"))
        return scopes

    def read_existing(self, server_name: str) -> Optional[ExistingEntry]:
        """Return the entry Claude Code would resolve: local > project > user scope."""
        for servers, location in self._scoped_servers():
            entry = _entry_from_servers(servers, server_name, location)
            if entry:
                return entry
        return None

    def list_entries(self) -> Dict[str, ExistingEntry]:
        entries: Dict[str, ExistingEntry] = {}
        for servers, location in self._scoped_servers():
            for name in servers:
                if name not in entries:
                    entry = _entry_from_servers(servers, name, location)
                    if entry:
                        entries[name] = entry
        return entries

    def remove(self, server_name: str, matches: Optional[UrlMatcher] = None) -> RemoveResult:
        """Delete the entry from every scope it lives in: local (~/.claude.json
        projects.<cwd>), project (.mcp.json), and user (~/.claude.json mcpServers).
        Both ~/.claude.json scopes are handled in one strict read + one atomic write."""
        removed_local = removed_user = False
        if self._user_config_path.exists():
            config = read_json_strict(self._user_config_path)
            projects = config.get("projects")
            if isinstance(projects, dict):
                project = projects.get(str(self.cwd))
                if isinstance(project, dict):
                    removed_local = pop_server_entry(project, server_name, matches)
            removed_user = pop_server_entry(config, server_name, matches)
            if removed_local or removed_user:
                atomic_write_text(self._user_config_path, json.dumps(config, indent=2) + "\n", secure=False)

        removed_project = remove_servers_entry(self._project_config_path, server_name, matches)

        # Report in Claude Code's resolution precedence: local > project > user.
        locations: List[str] = []
        if removed_local:
            locations.append(str(self._user_config_path) + " (local scope)")
        if removed_project:
            locations.append(str(self._project_config_path))
        if removed_user:
            locations.append(str(self._user_config_path) + " (user scope)")
        if not locations:
            return RemoveResult(removed=False)
        return RemoveResult(removed=True, location=", ".join(locations))

    def write(self, server_name: str, url: str, token: Optional[str]) -> WriteResult:
        # A token on `claude mcp add`'s argv would be exposed to `ps`/proc and execve audit
        # logs, so a token-bearing entry is written to the config file directly (0600). The
        # sanctioned CLI is used only for tokenless entries, where there is no secret to leak.
        if token is None and self._which("claude") is not None:
            self._write_via_cli(server_name, url)
            return WriteResult(method="cli", location="claude mcp add (scope: " + self.scope + ")")
        if self.scope == "project":
            return self._write_config_file(self._project_config_path, server_name, url, token)
        return self._write_config_file(self._user_config_path, server_name, url, token)

    # -- CLI path ---------------------------------------------------------------

    def _run_claude(self, args: List[str]) -> "subprocess.CompletedProcess[str]":
        try:
            return self._runner(
                args,
                capture_output=True,
                text=True,
                timeout=SUBPROCESS_TIMEOUT,
                stdin=subprocess.DEVNULL,
            )
        except subprocess.TimeoutExpired:
            raise CLIError("The claude CLI did not respond within " + str(int(SUBPROCESS_TIMEOUT)) + "s: " + args[2])

    def _write_via_cli(self, server_name: str, url: str) -> None:
        # Reached only for tokenless entries (see write): no --header, so nothing sensitive
        # rides on argv and the CLI error text carries no secret to redact.
        add_args: List[str] = ["claude", "mcp", "add", "--transport", "http", "--scope", self.scope, server_name, url]
        result = self._run_claude(add_args)
        if result.returncode != 0 and "already exists" in (result.stderr or "").lower():
            remove = self._run_claude(["claude", "mcp", "remove", "--scope", self.scope, server_name])
            if remove.returncode == 0:
                result = self._run_claude(add_args)
        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "").strip()
            raise CLIError("claude mcp add failed: " + (detail or "unknown error"))

    # -- File fallback ------------------------------------------------------------

    def _write_config_file(self, path: Path, server_name: str, url: str, token: Optional[str]) -> WriteResult:
        entry: Dict[str, Any] = {"type": "http", "url": url}
        if token:
            entry["headers"] = {"Authorization": bearer_header(token)}
        write_servers_entry(path, server_name, entry, secure=bool(token))
        note = None
        if path == self._project_config_path and token:
            note = str(path) + " is project-scoped and often committed to version control; it now contains a token."
        return WriteResult(method="file", location=str(path), note=note)
