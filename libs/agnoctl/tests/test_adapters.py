"""Client adapters: config reads/writes for Claude Code, Codex, and Cursor."""

import json
import os
import stat
import subprocess
import sys
from pathlib import Path
from typing import List, Optional

import pytest

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib

import agnoctl.clients.base as base_module
from agnoctl.clients.base import atomic_write_text
from agnoctl.clients.claude_code import ClaudeCodeAdapter
from agnoctl.clients.claude_desktop import ClaudeDesktopAdapter
from agnoctl.clients.codex import CodexAdapter
from agnoctl.clients.cursor import CursorAdapter
from agnoctl.errors import CLIError

URL = "http://localhost:7777/mcp"
TOKEN = "agno_pat_test123"


def _mode(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


class FakeRunner:
    """Records subprocess invocations and plays back scripted results."""

    def __init__(self, results: Optional[List[subprocess.CompletedProcess]] = None):
        self.calls: List[List[str]] = []
        self.results = results or []

    def __call__(self, args, **kwargs):
        self.calls.append(list(args))
        if self.results:
            return self.results.pop(0)
        return subprocess.CompletedProcess(args, 0, stdout="", stderr="")


# -- Claude Code -----------------------------------------------------------------------


def test_claude_token_write_never_reaches_cli_argv(tmp_path: Path):
    """Even with `claude` installed, a token-bearing write must not shell out: the token
    would be visible on `claude mcp add`'s argv (ps/proc, execve audit logs). It is written
    to the config file directly at 0600 instead."""
    runner = FakeRunner()
    adapter = ClaudeCodeAdapter(home=tmp_path, cwd=tmp_path, which=lambda name: "/usr/bin/claude", runner=runner)
    result = adapter.write("agno", URL, TOKEN)

    assert runner.calls == []  # the CLI (and thus argv) was never invoked
    assert result.method == "file"
    entry = json.loads((tmp_path / ".claude.json").read_text())["mcpServers"]["agno"]
    assert entry["headers"]["Authorization"] == "Bearer " + TOKEN
    assert _mode(tmp_path / ".claude.json") == 0o600


def test_claude_tokenless_write_via_cli_flag_order(tmp_path: Path):
    """A tokenless entry goes through the sanctioned CLI when `claude` is installed; with no
    token there is no --header, so nothing sensitive lands on argv."""
    runner = FakeRunner()
    adapter = ClaudeCodeAdapter(home=tmp_path, cwd=tmp_path, which=lambda name: "/usr/bin/claude", runner=runner)
    result = adapter.write("agno", URL, None)

    assert result.method == "cli"
    args = runner.calls[0]
    assert args[:3] == ["claude", "mcp", "add"]
    assert "--header" not in args  # no token, nothing on argv to expose
    # Flags precede the positional name and URL, or Claude Code's parser eats the positionals.
    assert args.index("--transport") < args.index("agno") < args.index(URL)


def test_claude_tokenless_cli_retries_on_already_exists(tmp_path: Path):
    runner = FakeRunner(
        results=[
            subprocess.CompletedProcess([], 1, stdout="", stderr="MCP server agno already exists"),
            subprocess.CompletedProcess([], 0, stdout="", stderr=""),
            subprocess.CompletedProcess([], 0, stdout="", stderr=""),
        ]
    )
    adapter = ClaudeCodeAdapter(home=tmp_path, cwd=tmp_path, which=lambda name: "/usr/bin/claude", runner=runner)
    adapter.write("agno", URL, None)
    assert runner.calls[1][:3] == ["claude", "mcp", "remove"]
    assert runner.calls[2][:3] == ["claude", "mcp", "add"]


def test_claude_write_file_fallback_user_scope(tmp_path: Path):
    """Without the binary, user-scope writes land in ~/.claude.json, never a VCS-shared file."""
    adapter = ClaudeCodeAdapter(home=tmp_path, cwd=tmp_path, which=lambda name: None)
    result = adapter.write("agno", URL, TOKEN)

    assert result.method == "file"
    config = json.loads((tmp_path / ".claude.json").read_text())
    entry = config["mcpServers"]["agno"]
    assert entry["url"] == URL
    assert entry["headers"]["Authorization"] == "Bearer " + TOKEN
    assert ((tmp_path / ".claude.json").stat().st_mode & 0o777) == 0o600
    assert not (tmp_path / ".mcp.json").exists()


def test_claude_write_file_fallback_project_scope_warns(tmp_path: Path):
    adapter = ClaudeCodeAdapter(home=tmp_path, cwd=tmp_path, scope="project", which=lambda name: None)
    result = adapter.write("agno", URL, TOKEN)
    config = json.loads((tmp_path / ".mcp.json").read_text())
    assert config["mcpServers"]["agno"]["url"] == URL
    assert result.note is not None and "version control" in result.note


def test_claude_write_preserves_unrelated_user_config(tmp_path: Path):
    (tmp_path / ".claude.json").write_text(json.dumps({"onboarding": True, "projects": {"/x": {}}}))
    adapter = ClaudeCodeAdapter(home=tmp_path, cwd=tmp_path, which=lambda name: None)
    adapter.write("agno", URL, TOKEN)
    config = json.loads((tmp_path / ".claude.json").read_text())
    assert config["onboarding"] is True
    assert config["projects"] == {"/x": {}}
    assert config["mcpServers"]["agno"]["url"] == URL


def test_claude_write_refuses_corrupt_config(tmp_path: Path):
    (tmp_path / ".claude.json").write_text("{not json")
    adapter = ClaudeCodeAdapter(home=tmp_path, cwd=tmp_path, which=lambda name: None)
    with pytest.raises(CLIError) as exc_info:
        adapter.write("agno", URL, TOKEN)
    assert "Refusing to modify" in exc_info.value.message
    assert (tmp_path / ".claude.json").read_text() == "{not json"


def test_claude_write_without_token_omits_headers(tmp_path: Path):
    adapter = ClaudeCodeAdapter(home=tmp_path, cwd=tmp_path, which=lambda name: None)
    adapter.write("agno", URL, None)
    entry = json.loads((tmp_path / ".claude.json").read_text())["mcpServers"]["agno"]
    assert "headers" not in entry


def test_claude_read_existing_roundtrip(tmp_path: Path):
    adapter = ClaudeCodeAdapter(home=tmp_path, cwd=tmp_path, which=lambda name: None)
    adapter.write("agno", URL, TOKEN)
    entry = adapter.read_existing("agno")
    assert entry is not None
    assert entry.url == URL
    assert entry.token == TOKEN


def test_claude_local_scope_wins_over_user_scope(tmp_path: Path):
    """Claude Code resolves local > project > user; read_existing must match."""
    (tmp_path / ".claude.json").write_text(
        json.dumps(
            {
                "mcpServers": {"agno": {"url": "http://user-scope/mcp"}},
                "projects": {str(tmp_path): {"mcpServers": {"agno": {"url": "http://local-scope/mcp"}}}},
            }
        )
    )
    adapter = ClaudeCodeAdapter(home=tmp_path, cwd=tmp_path, which=lambda name: None)
    entry = adapter.read_existing("agno")
    assert entry is not None
    assert entry.url == "http://local-scope/mcp"


def test_claude_read_existing_user_scope(tmp_path: Path):
    (tmp_path / ".claude.json").write_text(
        json.dumps(
            {"mcpServers": {"agno": {"type": "http", "url": URL, "headers": {"Authorization": "Bearer " + TOKEN}}}}
        )
    )
    adapter = ClaudeCodeAdapter(home=tmp_path, cwd=tmp_path, which=lambda name: None)
    entry = adapter.read_existing("agno")
    assert entry is not None
    assert entry.token == TOKEN


def test_claude_read_existing_local_scope(tmp_path: Path):
    cwd = tmp_path / "project"
    cwd.mkdir()
    (tmp_path / ".claude.json").write_text(json.dumps({"projects": {str(cwd): {"mcpServers": {"agno": {"url": URL}}}}}))
    adapter = ClaudeCodeAdapter(home=tmp_path, cwd=cwd, which=lambda name: None)
    entry = adapter.read_existing("agno")
    assert entry is not None
    assert entry.token is None


def test_claude_detect(tmp_path: Path):
    adapter = ClaudeCodeAdapter(home=tmp_path, cwd=tmp_path, which=lambda name: None)
    assert adapter.detect() is False
    (tmp_path / ".claude.json").write_text("{}")
    assert adapter.detect() is True


# -- Codex -----------------------------------------------------------------------------


def test_codex_write_creates_config(tmp_path: Path):
    adapter = CodexAdapter(home=tmp_path)
    result = adapter.write("agno", URL, TOKEN)

    assert result.method == "file"
    parsed = tomllib.loads(adapter.config_path.read_text())
    assert parsed["mcp_servers"]["agno"]["url"] == URL
    assert parsed["mcp_servers"]["agno"]["http_headers"]["Authorization"] == "Bearer " + TOKEN
    assert (adapter.config_path.stat().st_mode & 0o777) == 0o600


def test_codex_write_preserves_other_content(tmp_path: Path):
    config_dir = tmp_path / ".codex"
    config_dir.mkdir()
    (config_dir / "config.toml").write_text(
        '# my settings\nmodel = "o5"\n\n[mcp_servers.other]\nurl = "https://example.com/mcp"\n'
    )
    adapter = CodexAdapter(home=tmp_path)
    adapter.write("agno", URL, TOKEN)

    text = adapter.config_path.read_text()
    assert "# my settings" in text
    parsed = tomllib.loads(text)
    assert parsed["model"] == "o5"
    assert parsed["mcp_servers"]["other"]["url"] == "https://example.com/mcp"
    assert parsed["mcp_servers"]["agno"]["url"] == URL


def test_codex_write_replaces_existing_entry(tmp_path: Path):
    adapter = CodexAdapter(home=tmp_path)
    adapter.write("agno", "http://old:1/mcp", "agno_pat_old")
    adapter.write("agno", URL, TOKEN)

    parsed = tomllib.loads(adapter.config_path.read_text())
    assert parsed["mcp_servers"]["agno"]["url"] == URL
    assert parsed["mcp_servers"]["agno"]["http_headers"]["Authorization"] == "Bearer " + TOKEN
    assert adapter.config_path.read_text().count("[mcp_servers.agno]") == 1


def test_codex_replaces_dotted_subtables(tmp_path: Path):
    config_dir = tmp_path / ".codex"
    config_dir.mkdir()
    (config_dir / "config.toml").write_text(
        '[mcp_servers.agno]\nurl = "http://old:1/mcp"\n\n[mcp_servers.agno.http_headers]\nAuthorization = "Bearer old"\n\n[mcp_servers.keep]\nurl = "https://keep/mcp"\n'
    )
    adapter = CodexAdapter(home=tmp_path)
    adapter.write("agno", URL, TOKEN)

    parsed = tomllib.loads(adapter.config_path.read_text())
    assert parsed["mcp_servers"]["agno"]["url"] == URL
    assert parsed["mcp_servers"]["keep"]["url"] == "https://keep/mcp"
    assert "Bearer old" not in adapter.config_path.read_text()


def test_codex_replaces_inline_entry_under_mcp_servers_table(tmp_path: Path):
    """A hand-written inline `agno = {...}` under [mcp_servers] is replaced, not duplicated
    (which would make the re-parse reject the file and leave Codex unconnectable)."""
    config_dir = tmp_path / ".codex"
    config_dir.mkdir()
    (config_dir / "config.toml").write_text(
        '[mcp_servers]\nagno = { url = "http://old:1/mcp" }\nkeep = { url = "https://keep/mcp" }\n'
    )
    adapter = CodexAdapter(home=tmp_path)
    adapter.write("agno", URL, TOKEN)

    parsed = tomllib.loads(adapter.config_path.read_text())  # must parse (no "defined twice")
    assert parsed["mcp_servers"]["agno"]["url"] == URL
    assert parsed["mcp_servers"]["agno"]["http_headers"]["Authorization"] == "Bearer " + TOKEN
    assert parsed["mcp_servers"]["keep"]["url"] == "https://keep/mcp"


def test_codex_write_preserves_multiline_string_containing_key_like_line(tmp_path: Path):
    """A sibling key's triple-quoted value whose interior line reads like `agno = ...` must
    NOT be treated as an inline entry and dropped (only real `agno = {...}` inline tables are)."""
    config_dir = tmp_path / ".codex"
    config_dir.mkdir()
    (config_dir / "config.toml").write_text(
        '[mcp_servers]\ndescription = """\nUsage:\nagno = your primary server\n"""\n'
    )
    adapter = CodexAdapter(home=tmp_path)
    adapter.write("agno", URL, TOKEN)

    parsed = tomllib.loads(adapter.config_path.read_text())
    assert "agno = your primary server" in parsed["mcp_servers"]["description"]
    assert parsed["mcp_servers"]["agno"]["url"] == URL


def test_codex_replaces_quoted_header(tmp_path: Path):
    """A quoted table header [mcp_servers."agno"] is recognised as ours and replaced."""
    config_dir = tmp_path / ".codex"
    config_dir.mkdir()
    (config_dir / "config.toml").write_text('[mcp_servers."agno"]\nurl = "http://old:1/mcp"\n')
    adapter = CodexAdapter(home=tmp_path)
    adapter.write("agno", URL, TOKEN)

    parsed = tomllib.loads(adapter.config_path.read_text())
    assert parsed["mcp_servers"]["agno"]["url"] == URL
    assert "http://old:1/mcp" not in adapter.config_path.read_text()


def test_codex_read_existing_case_insensitive_authorization(tmp_path: Path):
    """A lowercase `authorization` header key still yields the token (HTTP header names are
    case-insensitive), so connect does not needlessly rotate a working entry."""
    config_dir = tmp_path / ".codex"
    config_dir.mkdir()
    (config_dir / "config.toml").write_text(
        '[mcp_servers.agno]\nurl = "' + URL + '"\nhttp_headers = { authorization = "Bearer ' + TOKEN + '" }\n'
    )
    adapter = CodexAdapter(home=tmp_path)
    entry = adapter.read_existing("agno")

    assert entry is not None
    assert entry.token == TOKEN


def test_codex_read_existing_roundtrip(tmp_path: Path):
    adapter = CodexAdapter(home=tmp_path)
    adapter.write("agno", URL, TOKEN)
    entry = adapter.read_existing("agno")
    assert entry is not None
    assert entry.url == URL
    assert entry.token == TOKEN


def test_codex_read_missing_or_malformed(tmp_path: Path):
    adapter = CodexAdapter(home=tmp_path)
    assert adapter.read_existing("agno") is None
    adapter.config_path.parent.mkdir(parents=True)
    adapter.config_path.write_text("this is [not valid toml")
    assert adapter.read_existing("agno") is None


def test_codex_write_refuses_corrupt_config(tmp_path: Path):
    adapter = CodexAdapter(home=tmp_path)
    adapter.config_path.parent.mkdir(parents=True)
    adapter.config_path.write_text("this is [not valid toml")
    with pytest.raises(CLIError) as exc_info:
        adapter.write("agno", URL, TOKEN)
    assert "Refusing to modify" in exc_info.value.message


def test_codex_preserves_array_of_tables_after_section(tmp_path: Path):
    """[[array-of-tables]] following the managed section must survive a rewrite."""
    config_dir = tmp_path / ".codex"
    config_dir.mkdir()
    original = (
        '[mcp_servers.agno]\nurl = "http://old:1/mcp"\n\n'
        "# profiles below\n"
        '[[profiles]]\nname = "work"\n\n'
        '[[profiles]]\nname = "personal"\n'
    )
    (config_dir / "config.toml").write_text(original)
    adapter = CodexAdapter(home=tmp_path)
    adapter.write("agno", URL, TOKEN)

    parsed = tomllib.loads(adapter.config_path.read_text())
    assert parsed["mcp_servers"]["agno"]["url"] == URL
    assert [p["name"] for p in parsed["profiles"]] == ["work", "personal"]
    assert "# profiles below" in adapter.config_path.read_text()


# -- Cursor ----------------------------------------------------------------------------


def test_cursor_write_global(tmp_path: Path):
    adapter = CursorAdapter(home=tmp_path, cwd=tmp_path)
    result = adapter.write("agno", URL, TOKEN)

    assert result.method == "file"
    config = json.loads((tmp_path / ".cursor" / "mcp.json").read_text())
    assert config["mcpServers"]["agno"]["url"] == URL
    assert config["mcpServers"]["agno"]["headers"]["Authorization"] == "Bearer " + TOKEN
    assert ((tmp_path / ".cursor" / "mcp.json").stat().st_mode & 0o777) == 0o600


def test_cursor_write_project_scope(tmp_path: Path):
    cwd = tmp_path / "project"
    cwd.mkdir()
    adapter = CursorAdapter(home=tmp_path, cwd=cwd, project=True)
    adapter.write("agno", URL, TOKEN)
    assert (cwd / ".cursor" / "mcp.json").exists()


def test_cursor_write_preserves_other_servers(tmp_path: Path):
    config_dir = tmp_path / ".cursor"
    config_dir.mkdir()
    (config_dir / "mcp.json").write_text(json.dumps({"mcpServers": {"other": {"url": "https://other/mcp"}}}))
    adapter = CursorAdapter(home=tmp_path, cwd=tmp_path)
    adapter.write("agno", URL, TOKEN)

    config = json.loads((config_dir / "mcp.json").read_text())
    assert config["mcpServers"]["other"]["url"] == "https://other/mcp"
    assert config["mcpServers"]["agno"]["url"] == URL


def test_cursor_read_prefers_project_config(tmp_path: Path):
    cwd = tmp_path / "project"
    (cwd / ".cursor").mkdir(parents=True)
    (tmp_path / ".cursor").mkdir()
    (cwd / ".cursor" / "mcp.json").write_text(json.dumps({"mcpServers": {"agno": {"url": "http://project/mcp"}}}))
    (tmp_path / ".cursor" / "mcp.json").write_text(json.dumps({"mcpServers": {"agno": {"url": "http://global/mcp"}}}))
    adapter = CursorAdapter(home=tmp_path, cwd=cwd)
    entry = adapter.read_existing("agno")
    assert entry is not None
    assert entry.url == "http://project/mcp"


def test_cursor_detect(tmp_path: Path):
    adapter = CursorAdapter(home=tmp_path, cwd=tmp_path)
    assert adapter.detect() is False
    (tmp_path / ".cursor").mkdir()
    assert adapter.detect() is True


def test_cursor_write_refuses_corrupt_config(tmp_path: Path):
    config_dir = tmp_path / ".cursor"
    config_dir.mkdir()
    (config_dir / "mcp.json").write_text("{broken")
    adapter = CursorAdapter(home=tmp_path, cwd=tmp_path)
    with pytest.raises(CLIError) as exc_info:
        adapter.write("agno", URL, TOKEN)
    assert "Refusing to modify" in exc_info.value.message
    assert (config_dir / "mcp.json").read_text() == "{broken"


def test_cursor_malformed_servers_shape_is_tolerated_on_read(tmp_path: Path):
    config_dir = tmp_path / ".cursor"
    config_dir.mkdir()
    (config_dir / "mcp.json").write_text(json.dumps({"mcpServers": ["not", "a", "dict"]}))
    adapter = CursorAdapter(home=tmp_path, cwd=tmp_path)
    assert adapter.read_existing("agno") is None
    with pytest.raises(CLIError):
        adapter.write("agno", URL, TOKEN)


# -- Atomic, permission-safe writes ----------------------------------------------------


@pytest.fixture
def permissive_umask():
    """Run the test as if the process umask were 0, so a naive write would create a
    world-readable file. The atomic writer must still land the secret at 0600."""
    old = os.umask(0)
    try:
        yield
    finally:
        os.umask(old)


def _file_writing_adapters(tmp_path: Path):
    """Each (adapter, config_path) that persists a token to a file directly (not via a CLI)."""
    return [
        (ClaudeCodeAdapter(home=tmp_path, cwd=tmp_path, which=lambda name: None), tmp_path / ".claude.json"),
        (CodexAdapter(home=tmp_path), tmp_path / ".codex" / "config.toml"),
        (CursorAdapter(home=tmp_path, cwd=tmp_path), tmp_path / ".cursor" / "mcp.json"),
        (
            ClaudeDesktopAdapter(home=tmp_path, config_path=tmp_path / "claude_desktop_config.json"),
            tmp_path / "claude_desktop_config.json",
        ),
    ]


def test_token_write_is_created_0600_even_under_permissive_umask(tmp_path: Path, permissive_umask):
    """A fresh config carrying a token must be created 0600, never a wider mode -- the
    file must never exist at 0644 with the secret in it, not even transiently."""
    for adapter, path in _file_writing_adapters(tmp_path):
        adapter.write("agno", URL, TOKEN)
        assert path.exists()
        assert _mode(path) == 0o600, (adapter.key, oct(_mode(path)))


def test_token_write_merged_into_existing_config_tightens_to_0600(tmp_path: Path, permissive_umask):
    """Merging a token into a pre-existing 0644 config must still end at 0600 -- the
    merge case must not leave the secret at the old, wider permissions."""
    # Claude Code user scope: an existing ~/.claude.json with unrelated state at 0644.
    claude_path = tmp_path / ".claude.json"
    claude_path.write_text(json.dumps({"onboarding": True}))
    claude_path.chmod(0o644)
    ClaudeCodeAdapter(home=tmp_path, cwd=tmp_path, which=lambda name: None).write("agno", URL, TOKEN)
    assert _mode(claude_path) == 0o600
    merged = json.loads(claude_path.read_text())
    assert merged["onboarding"] is True and merged["mcpServers"]["agno"]["url"] == URL

    # Cursor: an existing global mcp.json with another server at 0644.
    cursor_dir = tmp_path / ".cursor"
    cursor_dir.mkdir()
    cursor_path = cursor_dir / "mcp.json"
    cursor_path.write_text(json.dumps({"mcpServers": {"other": {"url": "https://other/mcp"}}}))
    cursor_path.chmod(0o644)
    CursorAdapter(home=tmp_path, cwd=tmp_path).write("agno", URL, TOKEN)
    assert _mode(cursor_path) == 0o600

    # Codex: an existing config.toml with a comment and another server at 0644.
    codex_dir = tmp_path / ".codex"
    codex_dir.mkdir()
    codex_path = codex_dir / "config.toml"
    codex_path.write_text('# mine\n[mcp_servers.other]\nurl = "https://other/mcp"\n')
    codex_path.chmod(0o644)
    CodexAdapter(home=tmp_path).write("agno", URL, TOKEN)
    assert _mode(codex_path) == 0o600


def test_tokenless_write_does_not_tighten_existing_mode(tmp_path: Path):
    """A write with no token must not silently re-permission an existing shared config;
    it keeps the file's current mode."""
    path = tmp_path / ".claude.json"
    path.write_text(json.dumps({"onboarding": True}))
    path.chmod(0o644)
    ClaudeCodeAdapter(home=tmp_path, cwd=tmp_path, which=lambda name: None).write("agno", URL, None)
    assert _mode(path) == 0o644


def test_writes_leave_no_temp_files_behind(tmp_path: Path):
    for adapter, path in _file_writing_adapters(tmp_path):
        adapter.write("agno", URL, TOKEN)
        leftovers = [p.name for p in path.parent.iterdir() if p.name != path.name and p.suffix == ".tmp"]
        assert leftovers == [], (adapter.key, leftovers)


def test_failed_replace_preserves_original_and_cleans_up(tmp_path: Path, monkeypatch):
    """If the final atomic replace fails, the pre-existing config is left intact and no
    partial temp file is left lying around."""
    path = tmp_path / ".claude.json"
    original = json.dumps({"onboarding": True})
    path.write_text(original)

    def boom(src, dst):
        raise OSError("simulated replace failure")

    monkeypatch.setattr(base_module.os, "replace", boom)
    with pytest.raises(OSError):
        ClaudeCodeAdapter(home=tmp_path, cwd=tmp_path, which=lambda name: None).write("agno", URL, TOKEN)

    assert path.read_text() == original
    leftovers = [p.name for p in tmp_path.iterdir() if p.suffix == ".tmp"]
    assert leftovers == []


def test_atomic_write_text_direct_secure(tmp_path: Path, permissive_umask):
    target = tmp_path / "nested" / "secret.txt"
    target.parent.mkdir()
    atomic_write_text(target, "s3cr3t", secure=True)
    assert target.read_text() == "s3cr3t"
    assert _mode(target) == 0o600
