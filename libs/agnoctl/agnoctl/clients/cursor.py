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
    WriteResult,
    bearer_header,
    read_json_lenient,
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

    def read_existing(self, server_name: str) -> Optional[ExistingEntry]:
        # Project config wins on collisions, so check it first even in global mode.
        for path in (self.cwd / ".cursor" / "mcp.json", self.home / ".cursor" / "mcp.json"):
            config = read_json_lenient(path)
            if config is None:
                continue
            entry = servers_table(config).get(server_name)
            if not isinstance(entry, dict):
                continue
            url = entry.get("url")
            if not isinstance(url, str) or not url:
                continue
            headers = entry.get("headers")
            if not isinstance(headers, dict):
                headers = {}
            return ExistingEntry(
                url=url,
                token=token_from_authorization(headers.get("Authorization")),
                location=str(path),
            )
        return None

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
