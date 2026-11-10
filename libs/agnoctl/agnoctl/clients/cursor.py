"""Cursor adapter.

Cursor has no CLI for adding MCP servers; the supported programmatic path is editing
mcp.json directly: ~/.cursor/mcp.json (global, all projects) or <project>/.cursor/mcp.json
(project-scoped, wins on name collisions). Remote servers are configured with a url and
optional headers; transport is inferred from the presence of url.
"""

from pathlib import Path
from typing import Any, Dict, Optional

from agnoctl.clients.base import (
    ClientAdapter,
    ExistingEntry,
    RemoveResult,
    UrlMatcher,
    WriteResult,
    bearer_header,
    read_json_lenient,
    remove_servers_entry,
    servers_table,
    token_from_authorization,
    write_servers_entry,
)


class CursorAdapter(ClientAdapter):
    key = "cursor"

    def __init__(self, home: Optional[Path] = None, cwd: Optional[Path] = None, project: bool = False):
        self.home = home or Path.home()
        self.cwd = cwd or Path.cwd()
        self.project = project

    @property
    def config_path(self) -> Path:
        if self.project:
            return self.cwd / ".cursor" / "mcp.json"
        return self.home / ".cursor" / "mcp.json"

    def detect(self) -> bool:
        return (self.home / ".cursor").is_dir()

    def list_entries(self) -> Dict[str, ExistingEntry]:
        entries: Dict[str, ExistingEntry] = {}
        # Project config wins on collisions, so it is read first and never overwritten.
        for path in (self.cwd / ".cursor" / "mcp.json", self.home / ".cursor" / "mcp.json"):
            config = read_json_lenient(path)
            if config is None:
                continue
            for name, entry in servers_table(config).items():
                if name in entries or not isinstance(entry, dict):
                    continue
                url = entry.get("url")
                if not isinstance(url, str) or not url:
                    continue
                headers = entry.get("headers")
                if not isinstance(headers, dict):
                    headers = {}
                entries[name] = ExistingEntry(
                    url=url,
                    token=token_from_authorization(headers.get("Authorization")),
                    location=str(path),
                )
        return entries

    def read_existing(self, server_name: str) -> Optional[ExistingEntry]:
        return self.list_entries().get(server_name)

    def remove(self, server_name: str, matches: Optional[UrlMatcher] = None) -> RemoveResult:
        # Both scopes, project first: a shadowed entry in the other file must not
        # silently take over after the client restarts.
        locations = []
        for path in (self.cwd / ".cursor" / "mcp.json", self.home / ".cursor" / "mcp.json"):
            if remove_servers_entry(path, server_name, matches):
                locations.append(str(path))
        if not locations:
            return RemoveResult(removed=False)
        return RemoveResult(removed=True, location=", ".join(locations))

    def write(self, server_name: str, url: str, token: Optional[str]) -> WriteResult:
        path = self.config_path
        entry: Dict[str, Any] = {"url": url}
        if token:
            entry["headers"] = {"Authorization": bearer_header(token)}
        write_servers_entry(path, server_name, entry, secure=bool(token), mkdir=True)
        note = None
        if self.project and token:
            note = str(path) + " is project-scoped; keep it out of version control (it now contains a token)."
        return WriteResult(method="file", location=str(path), note=note)
