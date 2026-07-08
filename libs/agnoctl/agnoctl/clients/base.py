"""Shared shapes for coding-agent client adapters.

An adapter knows how one coding agent (Claude Code, Codex, Cursor) stores MCP server
configuration: how to detect the client on this machine, read an existing entry back
(for idempotent re-runs), and write an entry pointing at an AgentOS MCP endpoint.
"""

import contextlib
import json
import os
import stat
import tempfile
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

from agnoctl.errors import CLIError


@dataclass
class ExistingEntry:
    """An MCP server entry found in a client's configuration."""

    url: str
    token: Optional[str]
    location: str  # human-readable: file path or config scope it was found in


@dataclass
class WriteResult:
    """How and where a config write landed."""

    method: str  # "cli" (client's own CLI did the write) | "file" (we edited the config file)
    location: str
    note: Optional[str] = None  # caveat worth surfacing to the user (e.g. VCS-shared file)


def servers_table(config: object) -> dict:
    """The mcpServers mapping from a parsed config, tolerating malformed shapes."""
    if isinstance(config, dict):
        servers = config.get("mcpServers")
        if isinstance(servers, dict):
            return servers
    return {}


def bearer_header(token: str) -> str:
    return "Bearer " + token


def token_from_authorization(value: Optional[str]) -> Optional[str]:
    """Extract the raw token from an Authorization header value."""
    if not value:
        return None
    if value.lower().startswith("bearer "):
        return value[len("bearer ") :].strip() or None
    return value.strip() or None


def read_json_lenient(path: Path) -> Optional[Dict[str, Any]]:
    """For reads: a missing or malformed file simply means no entry found."""
    if not path.exists():
        return None
    try:
        parsed = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return None
    return parsed if isinstance(parsed, dict) else None


def read_json_strict(path: Path) -> Dict[str, Any]:
    """For writes: refuse to clobber a file we cannot parse."""
    if not path.exists():
        return {}
    try:
        parsed = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as e:
        raise CLIError(
            "Refusing to modify " + str(path) + ": the existing file is not valid JSON (" + str(e) + ").",
            hint="Fix or move the file, then re-run.",
        )
    if not isinstance(parsed, dict):
        raise CLIError("Refusing to modify " + str(path) + ": expected a JSON object at the top level.")
    return parsed


def _plain_file_mode(path: Path) -> int:
    """The mode a non-secret config write should land with: the target's current mode
    when we are merging into an existing file, otherwise the process default
    (``0o666 & ~umask``). This keeps us from silently tightening or loosening an
    unrelated file that happens to carry no token."""
    try:
        return stat.S_IMODE(path.stat().st_mode)
    except OSError:
        current = os.umask(0)
        os.umask(current)
        return 0o666 & ~current


def atomic_write_text(path: Path, text: str, *, secure: bool) -> None:
    """Write ``text`` to ``path`` atomically, never exposing a secret at wide permissions.

    A crash mid-write must never corrupt the target (these files include Claude Code's
    whole ``~/.claude.json`` user state), and a token must never touch disk at a
    world-readable mode -- even transiently, and even if the process dies between the
    write and a follow-up ``chmod``.

    So: write to a temp file in the *same directory* (so ``os.replace`` is an atomic
    rename on one filesystem), ``fsync`` it, then replace the target. ``mkstemp`` creates
    the temp file 0600, so a secret is at 0600 from the instant it hits disk; the replace
    carries that mode onto the target. Non-secret writes keep the target's existing (or a
    umask-default) mode.
    """
    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix="." + path.name + ".", suffix=".tmp")
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "w") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        # mkstemp already created tmp as 0600; set the final mode explicitly so intent is
        # visible and a non-secret write does not inherit an over-tight 0600 by accident.
        os.chmod(tmp, 0o600 if secure else _plain_file_mode(path))
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise


def write_servers_entry(
    path: Path, server_name: str, entry: Dict[str, Any], *, secure: bool, mkdir: bool = False
) -> None:
    """Create or replace one ``mcpServers`` entry in a JSON config file.

    Shared by the file-editing adapters so the safety behavior -- strict parse before
    write, refusal on a malformed ``mcpServers``, atomic replace, 0600 permissions when
    the entry carries a token -- cannot drift between clients.
    """
    config = read_json_strict(path)
    servers = config.get("mcpServers")
    if servers is None:
        servers = {}
        config["mcpServers"] = servers
    elif not isinstance(servers, dict):
        raise CLIError("Refusing to modify " + str(path) + ": 'mcpServers' is not an object.")
    servers[server_name] = entry
    if mkdir:
        path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(path, json.dumps(config, indent=2) + "\n", secure=secure)


class ClientAdapter(ABC):
    key: str

    @abstractmethod
    def detect(self) -> bool:
        """Whether this client appears to be installed or configured on this machine."""

    @abstractmethod
    def read_existing(self, server_name: str) -> Optional[ExistingEntry]:
        """Return the existing MCP entry for server_name, if any."""

    @abstractmethod
    def write(self, server_name: str, url: str, token: Optional[str]) -> WriteResult:
        """Create or replace the MCP entry for server_name. Must be idempotent."""
