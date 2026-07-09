"""OpenAI Codex adapter.

Codex reads MCP servers from ~/.codex/config.toml as [mcp_servers.<name>] tables. The
`codex mcp add` CLI cannot set static HTTP headers (only --bearer-token-env-var, which
requires the user to manage an environment variable), so this adapter edits the config
file directly, using a static http_headers table for zero-setup authentication.

The edit is a section-scoped text replacement: only lines belonging to
[mcp_servers.<name>] (and its dotted subtables) are touched, so user comments and other
servers survive. The result is validated by re-parsing before it is written.
"""

import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from agnoctl.clients.base import (
    ClientAdapter,
    ExistingEntry,
    RemoveResult,
    UrlMatcher,
    WriteResult,
    atomic_write_text,
    bearer_header,
    token_from_authorization,
)
from agnoctl.errors import CLIError

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib


def _toml_string(value: str) -> str:
    # TOML basic strings share JSON's escaping rules for the characters that matter here.
    return json.dumps(value)


def _name_variants(server_name: str) -> tuple:
    """The bare and quoted spellings of a server name that TOML treats as the same key."""
    return (server_name, '"' + server_name + '"', "'" + server_name + "'")


def _owned_header(stripped: str, server_name: str) -> bool:
    """Whether a table header line belongs to our server: [mcp_servers.<name>] (bare or
    quoted) and its dotted subtables ([mcp_servers.<name>.foo])."""
    for variant in _name_variants(server_name):
        prefix = "[mcp_servers." + variant
        if stripped.startswith(prefix + "]") or stripped.startswith(prefix + "."):
            return True
    return False


def _is_inline_entry(stripped: str, server_name: str) -> bool:
    """Whether a line is an inline ``<name> = { ... }`` table for our server inside a bare
    ``[mcp_servers]`` table (the form `codex mcp add`'s table syntax does not produce, but a
    hand-written config can). TOML inline tables are single-line, so one line is enough.

    The value must actually start with ``{`` (an inline table): this is a line-by-line scan
    with no multiline-string awareness, so requiring the inline-table form keeps a stray
    ``<name> = ...`` line living inside some *other* key's triple-quoted string from being
    matched and dropped, which would silently corrupt that string."""
    if stripped.startswith("#") or "=" not in stripped:
        return False
    key, _, value = stripped.partition("=")
    if key.strip() not in _name_variants(server_name):
        return False
    return value.lstrip().startswith("{")


def _ci_get(mapping: Dict[str, Any], name: str) -> Any:
    """Case-insensitive lookup — TOML keys are case-sensitive, but HTTP header names are
    not, so a hand-written ``authorization`` must be found just like ``Authorization``."""
    for key, value in mapping.items():
        if isinstance(key, str) and key.lower() == name.lower():
            return value
    return None


class CodexAdapter(ClientAdapter):
    key = "codex"

    def __init__(self, home: Optional[Path] = None):
        self.home = home or Path.home()

    @property
    def config_path(self) -> Path:
        return self.home / ".codex" / "config.toml"

    def detect(self) -> bool:
        return (self.home / ".codex").is_dir()

    def list_entries(self) -> Dict[str, ExistingEntry]:
        parsed = self._parse_config()
        servers = (parsed or {}).get("mcp_servers")
        if not isinstance(servers, dict):
            return {}
        entries: Dict[str, ExistingEntry] = {}
        for name, entry in servers.items():
            if not isinstance(entry, dict):
                continue
            url = entry.get("url")
            if not isinstance(url, str) or not url:
                continue
            headers = entry.get("http_headers")
            if not isinstance(headers, dict):
                headers = {}
            entries[name] = ExistingEntry(
                url=url,
                token=token_from_authorization(_ci_get(headers, "Authorization")),
                location=str(self.config_path),
            )
        return entries

    def read_existing(self, server_name: str) -> Optional[ExistingEntry]:
        return self.list_entries().get(server_name)

    def write(self, server_name: str, url: str, token: Optional[str]) -> WriteResult:
        block_lines = ["[mcp_servers." + server_name + "]", "url = " + _toml_string(url)]
        if token:
            block_lines.append(
                "http_headers = { " + _toml_string("Authorization") + " = " + _toml_string(bearer_header(token)) + " }"
            )
        block = "\n".join(block_lines) + "\n"

        existing_text, _ = self._read_strict()
        new_text = self._replace_section(existing_text, server_name, block)
        self._validate_result(new_text)

        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(self.config_path, new_text, secure=bool(token))
        return WriteResult(method="file", location=str(self.config_path))

    def remove(self, server_name: str, matches: Optional[UrlMatcher] = None) -> RemoveResult:
        """Drop the [mcp_servers.<name>] table via the same section-replace the write
        path uses (with an empty block). _replace_section does not report whether it
        found anything, so existence is checked on the parsed config first."""
        text, parsed = self._read_strict()
        servers = parsed.get("mcp_servers")
        if not isinstance(servers, dict) or server_name not in servers:
            return RemoveResult(removed=False)
        if matches is not None:
            entry = servers.get(server_name)
            url = entry.get("url") if isinstance(entry, dict) else None
            if not isinstance(url, str) or not matches(url):
                return RemoveResult(removed=False)

        new_text = self._replace_section(text, server_name, "")
        remaining = self._validate_result(new_text)
        # The line scanner only handles the layouts write() produces ([mcp_servers.<name>]
        # tables and inline entries). A hand-written dotted-key spelling parses to the same
        # entry but survives the scan; reporting "removed" for it would be a lie.
        if server_name in (remaining.get("mcp_servers") or {}):
            raise CLIError(
                "Could not remove '" + server_name + "' from " + str(self.config_path) + ": unsupported TOML layout.",
                hint="Remove the entry from the file manually.",
            )
        atomic_write_text(self.config_path, new_text, secure=False)
        return RemoveResult(removed=True, location=str(self.config_path))

    # -- Internals -----------------------------------------------------------------

    def _read_strict(self) -> "tuple[str, Dict[str, Any]]":
        """The config file's text and parse; a file that does not parse refuses loudly
        (shared by the write and remove paths so their refusal behavior cannot drift)."""
        if not self.config_path.exists():
            return "", {}
        text = self.config_path.read_text()
        try:
            return text, tomllib.loads(text)
        except tomllib.TOMLDecodeError as e:
            raise CLIError(
                "Refusing to modify " + str(self.config_path) + ": the existing TOML does not parse (" + str(e) + ").",
                hint="Fix or move the file, then re-run.",
            )

    def _validate_result(self, new_text: str) -> Dict[str, Any]:
        try:
            return tomllib.loads(new_text)
        except tomllib.TOMLDecodeError as e:
            raise CLIError(
                "Refusing to write " + str(self.config_path) + ": the resulting TOML would be invalid (" + str(e) + ")."
            )

    def _parse_config(self) -> Optional[Dict[str, Any]]:
        if not self.config_path.exists():
            return None
        try:
            return tomllib.loads(self.config_path.read_text())
        except (OSError, tomllib.TOMLDecodeError):
            return None

    @staticmethod
    def _replace_section(text: str, server_name: str, block: str) -> str:
        """Replace (or append) our MCP server entry, whatever spelling the existing config uses.

        Handles the three forms TOML treats as ``mcp_servers.<name>``: the standard
        ``[mcp_servers.<name>]`` header (and its dotted subtables), a quoted header
        (``[mcp_servers."<name>"]``), and an inline ``<name> = {...}`` key inside a bare
        ``[mcp_servers]`` table. Missing any of these would append a duplicate definition
        and the write's re-parse would then reject the file, making the client
        unconnectable for that layout.

        Every table header — [table] and [[array-of-tables]] alike — ends the previous
        section, so content following the managed section is never swallowed. Trailing
        comment/blank lines inside the managed section that lead into the next header
        are preserved, since they usually describe what follows.
        """
        lines = text.splitlines()
        kept: List[str] = []
        dropped: List[str] = []
        insert_at: Optional[int] = None
        in_section = False  # inside an owned [mcp_servers.<name>...] table
        in_mcp_servers_table = False  # inside the bare [mcp_servers] table

        def flush_trailing_comments() -> None:
            trailing: List[str] = []
            for dropped_line in reversed(dropped):
                if dropped_line.strip() == "" or dropped_line.lstrip().startswith("#"):
                    trailing.append(dropped_line)
                else:
                    break
            kept.extend(reversed(trailing))
            dropped.clear()

        for line in lines:
            stripped = line.strip()
            if stripped.startswith("["):
                owns = _owned_header(stripped, server_name)
                if in_section and not owns:
                    flush_trailing_comments()
                in_section = owns
                in_mcp_servers_table = stripped == "[mcp_servers]"
                if owns:
                    if insert_at is None:
                        insert_at = len(kept)
                    continue
            if in_section:
                dropped.append(line)
                continue
            # Drop an inline `<name> = {...}` entry inside a bare [mcp_servers] table; the
            # fresh block below becomes the single, canonical definition.
            if in_mcp_servers_table and _is_inline_entry(stripped, server_name):
                continue
            kept.append(line)
        if in_section:
            dropped.clear()

        block_lines = block.rstrip("\n").splitlines()
        if insert_at is not None:
            kept[insert_at:insert_at] = block_lines
        else:
            if kept and kept[-1].strip():
                kept.append("")
            kept.extend(block_lines)
        return "\n".join(kept).rstrip("\n") + "\n"
