"""Claude Desktop adapter: the mcp-remote bridge entry in claude_desktop_config.json."""

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

import agnoctl.commands.connect as connect_module
from agnoctl.clients.claude_desktop import ClaudeDesktopAdapter, _default_config_path
from agnoctl.errors import CLIError
from agnoctl.main import app

URL = "http://localhost:7777/mcp"
TOKEN = "agno_pat_test123"


def _adapter(tmp_path: Path, npx: bool = True) -> ClaudeDesktopAdapter:
    return ClaudeDesktopAdapter(
        home=tmp_path,
        config_path=tmp_path / "claude_desktop_config.json",
        which=lambda name: "/usr/bin/npx" if npx else None,
    )


def test_write_creates_mcp_remote_bridge(tmp_path: Path):
    adapter = _adapter(tmp_path)
    result = adapter.write("agno", URL, TOKEN)

    assert result.method == "file"
    entry = json.loads(adapter.config_path.read_text())["mcpServers"]["agno"]
    assert entry["command"] == "npx"
    # URL is bridged as a positional arg; the token rides an env var, not argv.
    assert entry["args"][:3] == ["-y", "mcp-remote", URL]
    assert entry["args"][-2:] == ["--header", "Authorization:${AGNO_AUTH_HEADER}"]
    assert entry["env"]["AGNO_AUTH_HEADER"] == "Bearer " + TOKEN
    assert (adapter.config_path.stat().st_mode & 0o777) == 0o600


def test_write_without_token_omits_header_and_env(tmp_path: Path):
    adapter = _adapter(tmp_path)
    adapter.write("agno", URL, None)
    entry = json.loads(adapter.config_path.read_text())["mcpServers"]["agno"]
    assert entry["args"] == ["-y", "mcp-remote", URL]
    assert "env" not in entry
    assert "--header" not in entry["args"]


def test_read_existing_roundtrip(tmp_path: Path):
    adapter = _adapter(tmp_path)
    adapter.write("agno", URL, TOKEN)
    entry = adapter.read_existing("agno")
    assert entry is not None
    assert entry.url == URL
    assert entry.token == TOKEN


def test_read_existing_resolves_env_ref_token(tmp_path: Path):
    """A hand-written bridge whose header points at an env var still yields the token."""
    adapter = _adapter(tmp_path)
    adapter.config_path.write_text(
        json.dumps(
            {
                "mcpServers": {
                    "agno": {
                        "command": "npx",
                        "args": ["-y", "mcp-remote", URL, "--header", "Authorization:${MY_KEY}"],
                        "env": {"MY_KEY": "Bearer " + TOKEN},
                    }
                }
            }
        )
    )
    entry = adapter.read_existing("agno")
    assert entry is not None
    assert entry.token == TOKEN


def test_read_existing_inline_header_token(tmp_path: Path):
    adapter = _adapter(tmp_path)
    adapter.config_path.write_text(
        json.dumps(
            {
                "mcpServers": {
                    "agno": {
                        "command": "npx",
                        "args": ["-y", "mcp-remote", URL, "--header", "Authorization: Bearer " + TOKEN],
                    }
                }
            }
        )
    )
    entry = adapter.read_existing("agno")
    assert entry is not None
    assert entry.token == TOKEN


def test_read_existing_native_remote_entry_forward_compat(tmp_path: Path):
    """If a future Claude Desktop writes a native http entry, we still read it."""
    adapter = _adapter(tmp_path)
    adapter.config_path.write_text(
        json.dumps(
            {"mcpServers": {"agno": {"type": "http", "url": URL, "headers": {"Authorization": "Bearer " + TOKEN}}}}
        )
    )
    entry = adapter.read_existing("agno")
    assert entry is not None
    assert entry.url == URL
    assert entry.token == TOKEN


def test_read_existing_missing_returns_none(tmp_path: Path):
    assert _adapter(tmp_path).read_existing("agno") is None


def test_write_preserves_other_servers(tmp_path: Path):
    adapter = _adapter(tmp_path)
    adapter.config_path.write_text(
        json.dumps({"globalShortcut": "Cmd+X", "mcpServers": {"other": {"command": "node", "args": ["x.js"]}}})
    )
    adapter.write("agno", URL, TOKEN)
    config = json.loads(adapter.config_path.read_text())
    assert config["globalShortcut"] == "Cmd+X"
    assert config["mcpServers"]["other"]["command"] == "node"
    assert config["mcpServers"]["agno"]["command"] == "npx"


def test_write_refuses_corrupt_config(tmp_path: Path):
    adapter = _adapter(tmp_path)
    adapter.config_path.write_text("{not json")
    with pytest.raises(CLIError) as exc_info:
        adapter.write("agno", URL, TOKEN)
    assert "Refusing to modify" in exc_info.value.message
    assert adapter.config_path.read_text() == "{not json"


def test_write_notes_missing_npx(tmp_path: Path):
    adapter = _adapter(tmp_path, npx=False)
    result = adapter.write("agno", URL, TOKEN)
    assert result.note is not None and "npx" in result.note


def test_write_no_note_when_npx_present(tmp_path: Path):
    assert _adapter(tmp_path).write("agno", URL, TOKEN).note is None


def test_detect(tmp_path: Path):
    adapter = _adapter(tmp_path)  # config_path under tmp_path, parent (tmp_path) exists
    # Parent dir present but no file yet: treated as installed.
    assert adapter.detect() is True
    missing = ClaudeDesktopAdapter(home=tmp_path, config_path=tmp_path / "nope" / "config.json")
    assert missing.detect() is False
    (tmp_path / "nope").mkdir()
    assert missing.detect() is True


def test_default_config_path_per_os(tmp_path: Path):
    mac = _default_config_path(tmp_path, "darwin")
    assert mac == tmp_path / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json"
    linux = _default_config_path(tmp_path, "linux")
    assert linux == tmp_path / ".config" / "Claude" / "claude_desktop_config.json"
    win = _default_config_path(tmp_path, "win32")
    assert win.name == "claude_desktop_config.json" and "Claude" in str(win)


def test_connect_configures_claude_desktop_end_to_end(monkeypatch, fake_os, tmp_path: Path):
    """Mint -> bridge write -> readback token match -> verify: the full connect coupling."""
    monkeypatch.setenv("AGNO_ADMIN_TOKEN", fake_os.security_key)
    cfg = tmp_path / "claude_desktop_config.json"

    def build(home=None, cwd=None, project=False):
        return {
            "claude-desktop": ClaudeDesktopAdapter(home=tmp_path, config_path=cfg, which=lambda name: "/usr/bin/npx")
        }

    monkeypatch.setattr(connect_module, "build_adapters", build)
    result = CliRunner().invoke(app, ["connect", "--json", "--url", "http://localhost:7777"])
    assert result.exit_code == 0, result.output

    payload = json.loads(result.output)
    assert payload["results"][0]["client"] == "claude-desktop"
    assert payload["results"][0]["status"] == "connected"
    assert payload["results"][0]["verify"]["ok"] is True

    entry = json.loads(cfg.read_text())["mcpServers"]["agentos"]
    assert entry["env"]["AGNO_AUTH_HEADER"].startswith("Bearer agno_pat_")
    # The minted token never leaks into the JSON report.
    assert fake_os.accounts["claude-desktop"]["token"] not in result.output
