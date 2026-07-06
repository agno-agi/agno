"""`agno connect` end-to-end flows against the fake AgentOS and tmp client configs."""

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

import agnoctl.commands.connect as connect_module
from agnoctl.clients.claude_code import ClaudeCodeAdapter
from agnoctl.clients.codex import CodexAdapter
from agnoctl.clients.cursor import CursorAdapter
from agnoctl.errors import CLIError
from agnoctl.main import app
from tests.conftest import FakeAgentOS, install_fake

runner = CliRunner()

URL_ARGS = ["--url", "http://localhost:7777"]
MCP_URL = "http://localhost:7777/mcp"


@pytest.fixture
def fake_clients(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """All three clients 'installed' under a tmp home, wired into the connect command."""
    (tmp_path / ".claude.json").write_text("{}")
    (tmp_path / ".codex").mkdir()
    (tmp_path / ".cursor").mkdir()

    def build(home=None, cwd=None, project=False):
        return {
            "claude-code": ClaudeCodeAdapter(home=tmp_path, cwd=tmp_path, which=lambda name: None),
            "codex": CodexAdapter(home=tmp_path),
            "cursor": CursorAdapter(home=tmp_path, cwd=tmp_path, project=project),
        }

    monkeypatch.setattr(connect_module, "build_adapters", build)
    return tmp_path


@pytest.fixture
def no_clients(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A headless box: adapters build against an empty home, so nothing detects."""

    def build(home=None, cwd=None, project=False):
        return {
            "claude-code": ClaudeCodeAdapter(home=tmp_path, cwd=tmp_path, which=lambda name: None),
            "codex": CodexAdapter(home=tmp_path),
            "cursor": CursorAdapter(home=tmp_path, cwd=tmp_path, project=project),
        }

    monkeypatch.setattr(connect_module, "build_adapters", build)
    return tmp_path


def _connect(args=(), **kwargs):
    return runner.invoke(app, ["connect", "--json"] + URL_ARGS + list(args), **kwargs)


def test_connect_happy_path(monkeypatch, fake_os, fake_clients):
    monkeypatch.setenv("AGNO_ADMIN_TOKEN", fake_os.security_key)
    result = _connect()
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)

    assert {r["client"] for r in payload["results"]} == {"claude-code", "codex", "cursor"}
    assert all(r["status"] == "connected" for r in payload["results"])
    assert all(r["verify"]["ok"] for r in payload["results"])
    assert sorted(fake_os.accounts.keys()) == ["claude-code", "codex", "cursor"]

    # No plaintext token anywhere in the report.
    for account in fake_os.accounts.values():
        assert account["token"] not in result.output

    # Tokens landed in the client configs (Claude user scope = ~/.claude.json).
    claude_config = json.loads((fake_clients / ".claude.json").read_text())
    assert claude_config["mcpServers"]["agno"]["url"] == MCP_URL
    cursor_config = json.loads((fake_clients / ".cursor" / "mcp.json").read_text())
    token = cursor_config["mcpServers"]["agno"]["headers"]["Authorization"]
    assert token == "Bearer " + fake_os.accounts["cursor"]["token"]


def test_connect_rerun_is_idempotent(monkeypatch, fake_os, fake_clients):
    monkeypatch.setenv("AGNO_ADMIN_TOKEN", fake_os.security_key)
    first = _connect()
    assert first.exit_code == 0, first.output
    creates_after_first = fake_os.create_calls

    second = _connect()
    assert second.exit_code == 0, second.output
    payload = json.loads(second.output)
    assert all(r["status"] == "already-connected" for r in payload["results"])
    assert fake_os.create_calls == creates_after_first


def test_connect_conflict_without_rotate_fails_noninteractive(monkeypatch, fake_os, fake_clients):
    monkeypatch.setenv("AGNO_ADMIN_TOKEN", fake_os.security_key)
    assert _connect().exit_code == 0

    # Wipe client configs but keep server-side accounts: mint now conflicts.
    (fake_clients / ".claude.json").write_text("{}")
    (fake_clients / ".codex" / "config.toml").unlink()
    (fake_clients / ".cursor" / "mcp.json").unlink()

    result = _connect()
    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert all("already exists" in (r["error"] or "") for r in payload["results"])


def test_connect_rotate_replaces_accounts(monkeypatch, fake_os, fake_clients):
    monkeypatch.setenv("AGNO_ADMIN_TOKEN", fake_os.security_key)
    assert _connect().exit_code == 0
    old_token = fake_os.accounts["cursor"]["token"]

    result = _connect(["--rotate"])
    assert result.exit_code == 0, result.output
    new_token = fake_os.accounts["cursor"]["token"]
    assert new_token != old_token

    cursor_config = json.loads((fake_clients / ".cursor" / "mcp.json").read_text())
    assert cursor_config["mcpServers"]["agno"]["headers"]["Authorization"] == "Bearer " + new_token


def test_connect_rotate_flags_rotated_in_json(monkeypatch, fake_os, fake_clients):
    """A rotated token is flagged so callers know the running client must reconnect."""
    monkeypatch.setenv("AGNO_ADMIN_TOKEN", fake_os.security_key)
    assert _connect(["--clients", "cursor"]).exit_code == 0
    result = _connect(["--clients", "cursor", "--rotate"])
    assert result.exit_code == 0, result.output
    cursor = next(r for r in json.loads(result.output)["results"] if r["client"] == "cursor")
    assert cursor["status"] == "connected"
    assert cursor.get("rotated") is True


def test_connect_first_time_is_not_flagged_rotated(monkeypatch, fake_os, fake_clients):
    monkeypatch.setenv("AGNO_ADMIN_TOKEN", fake_os.security_key)
    result = _connect(["--clients", "cursor"])
    assert result.exit_code == 0, result.output
    cursor = next(r for r in json.loads(result.output)["results"] if r["client"] == "cursor")
    assert "rotated" not in cursor


def test_connect_rotate_prints_restart_reminder(monkeypatch, fake_os, fake_clients):
    monkeypatch.setenv("AGNO_ADMIN_TOKEN", fake_os.security_key)
    runner.invoke(app, ["connect"] + URL_ARGS + ["--clients", "cursor"])
    result = runner.invoke(app, ["connect"] + URL_ARGS + ["--clients", "cursor", "--rotate"])
    assert result.exit_code == 0, result.output
    assert "Restart" in result.output and "rotated" in result.output.lower()


def test_connect_rotates_stale_entry(monkeypatch, fake_os, fake_clients):
    """A config entry whose token was revoked server-side gets rotated on re-run."""
    monkeypatch.setenv("AGNO_ADMIN_TOKEN", fake_os.security_key)
    assert _connect().exit_code == 0
    for account in list(fake_os.accounts.values()):
        account["revoked_at"] = 1780000001

    result = _connect(["--rotate"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert all(r["status"] == "connected" for r in payload["results"])


def test_connect_no_auth_mode(monkeypatch, fake_clients):
    fake = FakeAgentOS(auth_mode="none")
    install_fake(monkeypatch, fake)
    result = _connect()
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert all(r["status"] == "connected" for r in payload["results"])
    assert fake.create_calls == 0
    cursor_config = json.loads((fake_clients / ".cursor" / "mcp.json").read_text())
    assert "headers" not in cursor_config["mcpServers"]["agno"]


def test_connect_mcp_disabled(monkeypatch, fake_clients):
    fake = FakeAgentOS(mcp_enabled=False)
    install_fake(monkeypatch, fake)
    result = _connect()
    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert "enable_mcp_server=True" in payload["error"]


def test_connect_warns_when_mcp_unauthenticated(monkeypatch, fake_clients):
    fake = FakeAgentOS(mcp_requires_token=False)
    install_fake(monkeypatch, fake)
    monkeypatch.setenv("AGNO_ADMIN_TOKEN", fake.security_key)
    result = _connect()
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["warning"] is not None
    assert "unauthenticated" in payload["warning"]


def test_connect_shared_account_with_name(monkeypatch, fake_os, fake_clients):
    monkeypatch.setenv("AGNO_ADMIN_TOKEN", fake_os.security_key)
    result = _connect(["--name", "my-machine"])
    assert result.exit_code == 0, result.output
    assert list(fake_os.accounts.keys()) == ["my-machine"]
    assert fake_os.create_calls == 1


def test_connect_explicit_client_selection(monkeypatch, fake_os, fake_clients):
    monkeypatch.setenv("AGNO_ADMIN_TOKEN", fake_os.security_key)
    result = _connect(["--clients", "cursor"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert [r["client"] for r in payload["results"]] == ["cursor"]
    assert list(fake_os.accounts.keys()) == ["cursor"]


def test_connect_unknown_client(monkeypatch, fake_os, fake_clients):
    result = _connect(["--clients", "emacs"])
    assert result.exit_code == 1
    assert "Unknown client" in json.loads(result.output)["error"]


def test_connect_missing_admin_credential(monkeypatch, fake_os, fake_clients):
    result = _connect()
    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert "AGNO_ADMIN_TOKEN" in payload["hint"]


def _connect_remote(args=(), **kwargs):
    return runner.invoke(app, ["connect", "--json", "--url", "http://os.example.com:7777"] + list(args), **kwargs)


def test_connect_refuses_plaintext_http_when_minting(monkeypatch, fake_os, fake_clients):
    """Minting attaches the admin token and writes minted PATs; refuse to do that over
    plaintext HTTP to a non-loopback host, and mint nothing."""
    monkeypatch.setenv("AGNO_ADMIN_TOKEN", fake_os.security_key)
    result = _connect_remote(["--clients", "cursor"])
    assert result.exit_code == 1
    assert "plaintext HTTP" in json.loads(result.output)["error"]
    assert fake_os.accounts == {}


def test_connect_allow_http_permits_remote_http(monkeypatch, fake_os, fake_clients):
    monkeypatch.setenv("AGNO_ADMIN_TOKEN", fake_os.security_key)
    result = _connect_remote(["--clients", "cursor", "--allow-http"])
    assert result.exit_code == 0, result.output
    assert list(fake_os.accounts.keys()) == ["cursor"]


def test_connect_no_auth_over_http_is_allowed(monkeypatch, fake_clients):
    """With auth disabled there is no credential to protect, so a remote http OS connects
    without requiring --allow-http (no token is ever written)."""
    from tests.conftest import FakeAgentOS, install_fake

    install_fake(monkeypatch, FakeAgentOS(auth_mode="none"))
    result = _connect_remote(["--clients", "cursor"])
    assert result.exit_code == 0, result.output
    assert fake_clients  # config written, no token


def test_connect_skip_existing_leaves_broken_entry(monkeypatch, fake_os, fake_clients):
    monkeypatch.setenv("AGNO_ADMIN_TOKEN", fake_os.security_key)
    assert _connect().exit_code == 0
    for account in list(fake_os.accounts.values()):
        account["revoked_at"] = 1780000001

    result = _connect(["--skip-existing"])
    payload = json.loads(result.output)
    assert all(r["status"] == "skipped" for r in payload["results"])
    assert result.exit_code == 1


def test_connect_skip_existing_never_touches_foreign_entry(monkeypatch, fake_os, fake_clients):
    """An entry pointing at a DIFFERENT AgentOS is untouchable under --skip-existing."""
    monkeypatch.setenv("AGNO_ADMIN_TOKEN", fake_os.security_key)
    foreign = {"mcpServers": {"agno": {"url": "http://other-os:9999/mcp", "headers": {"Authorization": "Bearer keep"}}}}
    (fake_clients / ".cursor" / "mcp.json").write_text(json.dumps(foreign))

    result = _connect(["--clients", "cursor", "--skip-existing"])
    payload = json.loads(result.output)
    assert payload["results"][0]["status"] == "skipped"
    assert "other-os" in payload["results"][0]["error"]
    config = json.loads((fake_clients / ".cursor" / "mcp.json").read_text())
    assert config["mcpServers"]["agno"]["url"] == "http://other-os:9999/mcp"
    assert config["mcpServers"]["agno"]["headers"]["Authorization"] == "Bearer keep"
    assert fake_os.create_calls == 0


def test_connect_replacing_foreign_entry_is_reported(monkeypatch, fake_os, fake_clients):
    monkeypatch.setenv("AGNO_ADMIN_TOKEN", fake_os.security_key)
    foreign = {"mcpServers": {"agno": {"url": "http://other-os:9999/mcp"}}}
    (fake_clients / ".cursor" / "mcp.json").write_text(json.dumps(foreign))

    result = _connect(["--clients", "cursor"])
    payload = json.loads(result.output)
    assert payload["results"][0]["status"] == "connected"
    assert payload["results"][0]["replaced_url"] == "http://other-os:9999/mcp"


def test_connect_partial_failure_keeps_json_contract(monkeypatch, fake_os, fake_clients):
    """One corrupt client config fails that client only; output stays one JSON document, exit 3."""
    monkeypatch.setenv("AGNO_ADMIN_TOKEN", fake_os.security_key)
    (fake_clients / ".cursor" / "mcp.json").write_text("{corrupt")

    result = _connect()
    payload = json.loads(result.output)
    by_client = {r["client"]: r for r in payload["results"]}
    assert by_client["cursor"]["status"] == "failed"
    assert "Refusing to modify" in by_client["cursor"]["error"]
    assert by_client["claude-code"]["status"] == "connected"
    assert by_client["codex"]["status"] == "connected"
    assert result.exit_code == 3


def test_connect_detects_shadowing_claude_local_entry(monkeypatch, fake_os, fake_clients):
    """A stale local-scope entry shadows the user-scope write; connect must fail loudly, not lie."""
    monkeypatch.setenv("AGNO_ADMIN_TOKEN", fake_os.security_key)
    (fake_clients / ".claude.json").write_text(
        json.dumps({"projects": {str(fake_clients): {"mcpServers": {"agno": {"url": "http://stale:1/mcp"}}}}})
    )

    result = _connect(["--clients", "claude-code", "--rotate"])
    payload = json.loads(result.output)
    assert payload["results"][0]["status"] == "failed"
    assert "shadow" in payload["results"][0]["error"]
    assert result.exit_code == 1


def test_connect_chatgpt_prints_manual_instructions(monkeypatch, fake_os, fake_clients):
    """chatgpt is opt-in, mints nothing, and reports a 'manual' status (exit 0)."""
    result = _connect(["--clients", "chatgpt"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert len(payload["results"]) == 1
    entry = payload["results"][0]
    assert entry["client"] == "chatgpt"
    assert entry["status"] == "manual"
    assert entry["url"] == MCP_URL
    assert entry["instructions"]
    # localhost AgentOS is unreachable from ChatGPT's cloud: the note must say so.
    assert "public HTTPS" in entry["note"]
    # No account minted, and no admin credential was required.
    assert fake_os.create_calls == 0


def test_connect_chatgpt_public_url_has_no_unreachable_note(monkeypatch, fake_clients):
    fake = FakeAgentOS()
    install_fake(monkeypatch, fake)
    result = runner.invoke(app, ["connect", "--json", "--url", "https://os.example.com", "--clients", "chatgpt"])
    assert result.exit_code == 0, result.output
    entry = json.loads(result.output)["results"][0]
    assert entry["status"] == "manual"
    assert entry["url"] == "https://os.example.com/mcp"
    assert entry["note"] is None


def test_connect_claude_ai_prints_manual_instructions(monkeypatch, fake_os, fake_clients):
    """claude-ai is opt-in like chatgpt: mints nothing, reports a 'manual' status (exit 0)."""
    result = _connect(["--clients", "claude-ai"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert len(payload["results"]) == 1
    entry = payload["results"][0]
    assert entry["client"] == "claude-ai"
    assert entry["status"] == "manual"
    assert entry["url"] == MCP_URL
    assert any("claude.ai" in step for step in entry["instructions"])
    # localhost AgentOS is unreachable from Claude's cloud: the note must say so.
    assert "public HTTPS" in entry["note"]
    assert fake_os.create_calls == 0


def test_connect_public_url_surfaces_chat_apps(monkeypatch, fake_clients):
    """AGENTOS_URL pointing at a deployed, token-free AgentOS: coding agents connect to
    it, and the report additionally surfaces the Claude and ChatGPT app setup steps."""
    fake = FakeAgentOS(auth_mode="none")
    install_fake(monkeypatch, fake)
    monkeypatch.setenv("AGENTOS_URL", "https://os.example.com")
    result = runner.invoke(app, ["connect", "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)

    assert payload["os"]["url"] == "https://os.example.com"
    assert payload["os"]["url_source"] == "env"
    by_client = {r["client"]: r for r in payload["results"]}
    assert set(by_client) == {"claude-code", "codex", "cursor", "claude-ai", "chatgpt"}
    for client in ("claude-code", "codex", "cursor"):
        assert by_client[client]["status"] == "connected"
    for chat_app in ("claude-ai", "chatgpt"):
        assert by_client[chat_app]["status"] == "manual"
        assert by_client[chat_app]["url"] == "https://os.example.com/mcp"
        assert by_client[chat_app]["note"] is None


def test_connect_token_protected_public_url_does_not_auto_surface(monkeypatch, fake_clients):
    """The chat apps' Connectors UIs authenticate with OAuth, not bearer tokens, so a
    token-protected AgentOS cannot be added there -- don't advertise steps that the
    instructions themselves say cannot work. Explicit --clients still prints them."""
    fake = FakeAgentOS()  # security_key mode
    install_fake(monkeypatch, fake)
    monkeypatch.setenv("AGENTOS_URL", "https://os.example.com")
    monkeypatch.setenv("AGNO_ADMIN_TOKEN", fake.security_key)
    result = runner.invoke(app, ["connect", "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert {r["client"] for r in payload["results"]} == {"claude-code", "codex", "cursor"}


def test_connect_headless_deploy_box_surfaces_chat_apps(no_clients, monkeypatch):
    """The auto-surface's primary home is a deploy box with no local coding agents:
    the run must not die on 'no supported clients detected' when there are chat apps
    to report for the deployed URL."""
    fake = FakeAgentOS(auth_mode="none")
    install_fake(monkeypatch, fake)
    monkeypatch.setenv("AGENTOS_URL", "https://os.example.com")
    result = runner.invoke(app, ["connect", "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    by_client = {r["client"]: r for r in payload["results"]}
    assert set(by_client) == {"claude-ai", "chatgpt"}
    assert all(r["status"] == "manual" for r in payload["results"])


def test_connect_headless_localhost_still_errors(no_clients, monkeypatch):
    """With nothing to surface (localhost) and no local clients, the original
    actionable error remains."""
    fake = FakeAgentOS(auth_mode="none")
    install_fake(monkeypatch, fake)
    result = _connect()
    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert "No supported clients detected" in payload["error"]


def test_connect_all_real_clients_failing_exits_failure(monkeypatch, fake_clients):
    """Auto-added manual chat-app entries must not soften total failure into partial:
    every real adapter failing is exit 1, not 3."""
    fake = FakeAgentOS(auth_mode="none")
    install_fake(monkeypatch, fake)
    monkeypatch.setenv("AGENTOS_URL", "https://os.example.com")

    def boom(**kwargs):
        raise CLIError("client exploded")

    monkeypatch.setattr(connect_module, "_connect_one", boom)
    result = runner.invoke(app, ["connect", "--json"])
    assert result.exit_code == 1, result.output
    payload = json.loads(result.output)
    by_client = {r["client"]: r for r in payload["results"]}
    for client in ("claude-code", "codex", "cursor"):
        assert by_client[client]["status"] == "failed"
    for chat_app in ("claude-ai", "chatgpt"):
        assert by_client[chat_app]["status"] == "manual"


def test_connect_localhost_does_not_surface_chat_apps(monkeypatch, fake_os, fake_clients):
    """The chat apps' clouds cannot reach localhost, so auto-detect must not offer them."""
    monkeypatch.setenv("AGNO_ADMIN_TOKEN", fake_os.security_key)
    result = _connect()
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert {r["client"] for r in payload["results"]} == {"claude-code", "codex", "cursor"}


def test_connect_explicit_clients_suppress_chat_app_autodetect(monkeypatch, fake_clients):
    """--clients scopes the run: no chat-app entries are appended even on a public URL."""
    fake = FakeAgentOS()
    install_fake(monkeypatch, fake)
    monkeypatch.setenv("AGNO_ADMIN_TOKEN", fake.security_key)
    result = runner.invoke(app, ["connect", "--json", "--url", "https://os.example.com", "--clients", "cursor"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert {r["client"] for r in payload["results"]} == {"cursor"}


def test_connect_mixes_chatgpt_with_a_real_client(monkeypatch, fake_os, fake_clients):
    """cursor connects and verifies; chatgpt is manual; the run still exits 0."""
    monkeypatch.setenv("AGNO_ADMIN_TOKEN", fake_os.security_key)
    result = _connect(["--clients", "cursor,chatgpt"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    by_client = {r["client"]: r for r in payload["results"]}
    assert by_client["cursor"]["status"] == "connected"
    assert by_client["chatgpt"]["status"] == "manual"
    # Only the real client minted an account.
    assert list(fake_os.accounts.keys()) == ["cursor"]


def test_connect_shared_account_reuses_token_for_new_client(monkeypatch, fake_os, fake_clients):
    """Regression: in shared-account mode, an already-connected client must hand the
    shared token to clients connecting later, instead of the later client hitting the
    name conflict and re-minting (which revoked the token just reported OK)."""
    monkeypatch.setenv("AGNO_ADMIN_TOKEN", fake_os.security_key)
    result = _connect(["--name", "shared"])
    assert result.exit_code == 0, result.output
    assert fake_os.create_calls == 1

    claude_config = json.loads((fake_clients / ".claude.json").read_text())
    shared_token = claude_config["mcpServers"]["agno"]["headers"]["Authorization"].split(" ", 1)[1]

    # A new client appears after the first run: cursor has no entry yet.
    (fake_clients / ".cursor" / "mcp.json").unlink(missing_ok=True)

    result = _connect(["--name", "shared"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    statuses = {r["client"]: r["status"] for r in payload["results"]}
    assert statuses["claude-code"] == "already-connected"
    assert statuses["cursor"] == "connected"

    # No second mint, no revocation: the shared token still verifies everywhere.
    assert fake_os.create_calls == 1
    assert fake_os.active_tokens() == [shared_token]
    cursor_config = json.loads((fake_clients / ".cursor" / "mcp.json").read_text())
    assert cursor_config["mcpServers"]["agno"]["headers"]["Authorization"] == "Bearer " + shared_token
