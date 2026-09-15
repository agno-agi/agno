"""`agno connect` end-to-end flows against the fake AgentOS and tmp client configs."""

import json
from pathlib import Path

import httpx
import pytest
from typer.testing import CliRunner

import agnoctl.commands.connect as connect_module
from agnoctl.clients.claude_code import ClaudeCodeAdapter
from agnoctl.clients.codex import CodexAdapter
from agnoctl.clients.cursor import CursorAdapter
from agnoctl.errors import CLIError
from agnoctl.main import app
from tests.conftest import FakeAgentOS, install_fake
from tests.conftest import all_output as _all_output

runner = CliRunner()

URL_ARGS = ["--url", "http://localhost:7777"]
MCP_URL = "http://localhost:7777/mcp"


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

    # Tokens landed in the client configs (Claude user scope = ~/.claude.json), under
    # the derived default entry name (the fake OS serves no name -> "agentos").
    claude_config = json.loads((fake_clients / ".claude.json").read_text())
    assert claude_config["mcpServers"]["agentos"]["url"] == MCP_URL
    cursor_config = json.loads((fake_clients / ".cursor" / "mcp.json").read_text())
    token = cursor_config["mcpServers"]["agentos"]["headers"]["Authorization"]
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
    assert cursor_config["mcpServers"]["agentos"]["headers"]["Authorization"] == "Bearer " + new_token


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
    assert "headers" not in cursor_config["mcpServers"]["agentos"]


def test_connect_mcp_disabled(monkeypatch, fake_clients):
    fake = FakeAgentOS(mcp_enabled=False)
    install_fake(monkeypatch, fake)
    result = _connect()
    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert "mcp_server=True" in payload["error"]


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
    foreign = {
        "mcpServers": {"agentos": {"url": "http://other-os:9999/mcp", "headers": {"Authorization": "Bearer keep"}}}
    }
    (fake_clients / ".cursor" / "mcp.json").write_text(json.dumps(foreign))

    result = _connect(["--clients", "cursor", "--skip-existing"])
    payload = json.loads(result.output)
    assert payload["results"][0]["status"] == "skipped"
    assert "other-os" in payload["results"][0]["error"]
    config = json.loads((fake_clients / ".cursor" / "mcp.json").read_text())
    assert config["mcpServers"]["agentos"]["url"] == "http://other-os:9999/mcp"
    assert config["mcpServers"]["agentos"]["headers"]["Authorization"] == "Bearer keep"
    assert fake_os.create_calls == 0


def test_connect_replacing_foreign_entry_is_reported(monkeypatch, fake_os, fake_clients):
    monkeypatch.setenv("AGNO_ADMIN_TOKEN", fake_os.security_key)
    foreign = {"mcpServers": {"agentos": {"url": "http://other-os:9999/mcp"}}}
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
        json.dumps({"projects": {str(fake_clients): {"mcpServers": {"agentos": {"url": "http://stale:1/mcp"}}}}})
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
    shared_token = claude_config["mcpServers"]["agentos"]["headers"]["Authorization"].split(" ", 1)[1]

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
    assert cursor_config["mcpServers"]["agentos"]["headers"]["Authorization"] == "Bearer " + shared_token


# -- multi-target selection, derived names, restart hints, legacy migration ------------


def _install_two_hosts(monkeypatch, tmp_path):
    """A deployed OS (env-file URL) and a local one, both live: the reported scenario."""
    (tmp_path / ".env.production").write_text("AGENTOS_URL=http://prodhost:9000\n")
    monkeypatch.chdir(tmp_path)
    remote = FakeAgentOS(auth_mode="none", name="Live Railway")
    local = FakeAgentOS(auth_mode="none", name="Local Dev")

    def handler(request: httpx.Request) -> httpx.Response:
        key = request.url.host + ":" + str(request.url.port)
        if key == "prodhost:9000":
            return remote.handler(request)
        if key == "localhost:7777":
            return local.handler(request)
        raise httpx.ConnectError("connection refused", request=request)

    import agnoctl.http as http_module

    monkeypatch.setattr(http_module, "_transport_override", httpx.MockTransport(handler))
    for var in ("AGNO_ADMIN_TOKEN", "OS_SECURITY_KEY", "AGENTOS_URL"):
        monkeypatch.delenv(var, raising=False)
    return remote, local


def _make_interactive(monkeypatch):
    import agnoctl.commands._common as common

    monkeypatch.setattr(common, "stdin_is_interactive", lambda: True)
    monkeypatch.setattr(connect_module, "stdin_is_interactive", lambda: True)


def test_connect_menu_pick_local_skips_trust_prompt(monkeypatch, tmp_path, fake_clients):
    """Selecting the local OS from the menu connects silently: no env-file trust prompt."""
    _install_two_hosts(monkeypatch, tmp_path)
    _make_interactive(monkeypatch)

    result = runner.invoke(app, ["connect", "--clients", "cursor"], input="2\n")
    assert result.exit_code == 0, _all_output(result)
    out = _all_output(result)
    assert "Which one do you want to connect?" in out
    assert "Trust AGENTOS_URL" not in out

    cursor_config = json.loads((fake_clients / ".cursor" / "mcp.json").read_text())
    assert cursor_config["mcpServers"]["local-dev"]["url"] == MCP_URL


def test_connect_menu_default_is_remote_and_trust_defaults_yes(monkeypatch, tmp_path, fake_clients):
    """Enter-Enter targets the env-file (deployed) OS: the menu defaults to it, and the
    trust prompt accepts on Enter ([Y/n])."""
    _install_two_hosts(monkeypatch, tmp_path)
    _make_interactive(monkeypatch)

    result = runner.invoke(app, ["connect", "--clients", "cursor"], input="\n\n")
    assert result.exit_code == 0, _all_output(result)
    assert "Trust AGENTOS_URL=http://prodhost:9000" in _all_output(result)

    cursor_config = json.loads((fake_clients / ".cursor" / "mcp.json").read_text())
    assert cursor_config["mcpServers"]["live-railway"]["url"] == "http://prodhost:9000/mcp"


def test_connect_menu_explicit_no_still_aborts_trust(monkeypatch, tmp_path, fake_clients):
    _install_two_hosts(monkeypatch, tmp_path)
    _make_interactive(monkeypatch)

    result = runner.invoke(app, ["connect", "--clients", "cursor"], input="1\nn\n")
    assert result.exit_code != 0
    assert "did not trust" in _all_output(result)


def test_connect_json_multi_candidate_is_deterministic(monkeypatch, tmp_path, fake_clients):
    """--json never prompts: the single highest-priority (env-file) target is resolved,
    and the remote env-file trust gate still requires --yes -- no automation regression."""
    _install_two_hosts(monkeypatch, tmp_path)

    refused = runner.invoke(app, ["connect", "--json", "--clients", "cursor"])
    assert refused.exit_code == 1
    assert "--yes" in json.loads(refused.output)["hint"]

    result = runner.invoke(app, ["connect", "--json", "--clients", "cursor", "--yes"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["os"]["url"] == "http://prodhost:9000"
    assert payload["server_name"] == "live-railway"


def test_connect_json_dead_env_file_target_stays_a_hard_failure(monkeypatch, tmp_path, fake_clients):
    """Automation must never be silently retargeted: with the env-file OS down and a
    local OS up, --json fails like single-target discovery always has, instead of
    minting against whatever else happens to be running."""
    (tmp_path / ".env.production").write_text("AGENTOS_URL=http://prodhost:9000\n")
    monkeypatch.chdir(tmp_path)
    local = FakeAgentOS(auth_mode="none")

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host + ":" + str(request.url.port) == "localhost:7777":
            return local.handler(request)
        raise httpx.ConnectError("connection refused", request=request)

    import agnoctl.http as http_module

    monkeypatch.setattr(http_module, "_transport_override", httpx.MockTransport(handler))
    for var in ("AGNO_ADMIN_TOKEN", "OS_SECURITY_KEY", "AGENTOS_URL"):
        monkeypatch.delenv(var, raising=False)

    result = runner.invoke(app, ["connect", "--json", "--clients", "cursor", "--yes"])
    assert result.exit_code == 1
    assert "No running AgentOS" in json.loads(result.output)["error"]
    cursor_config = (
        json.loads((fake_clients / ".cursor" / "mcp.json").read_text())
        if (fake_clients / ".cursor" / "mcp.json").exists()
        else {"mcpServers": {}}
    )
    assert cursor_config.get("mcpServers", {}) == {}


def test_connect_interactive_notes_dead_env_file_url(monkeypatch, tmp_path, fake_clients):
    """Interactively, a dead env-file OS falls through to the local one -- with a note,
    so the stale AGENTOS_URL does not go unnoticed forever."""
    (tmp_path / ".env.production").write_text("AGENTOS_URL=http://prodhost:9000\n")
    monkeypatch.chdir(tmp_path)
    local = FakeAgentOS(auth_mode="none", name="Local Dev")

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host + ":" + str(request.url.port) == "localhost:7777":
            return local.handler(request)
        raise httpx.ConnectError("connection refused", request=request)

    import agnoctl.http as http_module

    monkeypatch.setattr(http_module, "_transport_override", httpx.MockTransport(handler))
    for var in ("AGNO_ADMIN_TOKEN", "OS_SECURITY_KEY", "AGENTOS_URL"):
        monkeypatch.delenv(var, raising=False)
    _make_interactive(monkeypatch)

    result = runner.invoke(app, ["connect", "--clients", "cursor"])
    assert result.exit_code == 0, _all_output(result)
    out = _all_output(result)
    assert "did not answer" in out
    cursor_config = json.loads((fake_clients / ".cursor" / "mcp.json").read_text())
    assert cursor_config["mcpServers"]["local-dev"]["url"] == MCP_URL


def test_connect_custom_scopes_skip_legacy_token_reuse(monkeypatch, fake_os, fake_clients):
    """Explicit --scopes means the operator wants a freshly provisioned account, so the
    legacy entry's old (differently scoped) token is not silently reused."""
    monkeypatch.setenv("AGNO_ADMIN_TOKEN", fake_os.security_key)
    assert _connect(["--server-name", "agno", "--clients", "cursor"]).exit_code == 0

    result = _connect(["--clients", "cursor", "--scopes", "agents:run"])
    assert result.exit_code == 1
    assert "already exists" in (json.loads(result.output)["results"][0]["error"] or "")


def test_connect_derives_server_name_from_os_name(monkeypatch, fake_clients):
    fake = FakeAgentOS(name="Customer Support", os_id="os-123")
    install_fake(monkeypatch, fake)
    monkeypatch.setenv("AGNO_ADMIN_TOKEN", fake.security_key)

    result = _connect(["--clients", "cursor"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["server_name"] == "customer-support"
    assert payload["os"]["name"] == "Customer Support"
    cursor_config = json.loads((fake_clients / ".cursor" / "mcp.json").read_text())
    assert "customer-support" in cursor_config["mcpServers"]


def test_connect_server_name_flag_overrides_derived(monkeypatch, fake_clients):
    fake = FakeAgentOS(name="Customer Support")
    install_fake(monkeypatch, fake)
    monkeypatch.setenv("AGNO_ADMIN_TOKEN", fake.security_key)

    result = _connect(["--clients", "cursor", "--server-name", "custom"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["server_name"] == "custom"
    cursor_config = json.loads((fake_clients / ".cursor" / "mcp.json").read_text())
    assert "custom" in cursor_config["mcpServers"]
    assert "customer-support" not in cursor_config["mcpServers"]


def test_connect_fresh_connect_prints_restart_hint(monkeypatch, fake_os, fake_clients):
    """A fresh connect (not just a rotation) tells the operator to restart the apps."""
    monkeypatch.setenv("AGNO_ADMIN_TOKEN", fake_os.security_key)
    result = runner.invoke(app, ["connect"] + URL_ARGS + ["--clients", "cursor"])
    assert result.exit_code == 0, _all_output(result)
    out = _all_output(result)
    assert "Restart" in out
    assert "Cursor" in out


def test_connect_renames_legacy_agno_entry(monkeypatch, fake_os, fake_clients):
    """Round-1 configs hold an entry named "agno". A re-connect under the derived name
    must rename it in place: reuse its working token (no re-mint, no revocation) and
    drop the stale "agno" entry instead of leaving two servers behind."""
    monkeypatch.setenv("AGNO_ADMIN_TOKEN", fake_os.security_key)
    assert _connect(["--server-name", "agno"]).exit_code == 0
    creates_after_round1 = fake_os.create_calls
    old_tokens = set(fake_os.active_tokens())

    result = _connect()
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert all(r["status"] == "connected" for r in payload["results"])
    assert all(r.get("replaced_legacy") == "agno" for r in payload["results"])

    # Tokens were reused, not re-minted: no new accounts, nothing revoked.
    assert fake_os.create_calls == creates_after_round1
    assert set(fake_os.active_tokens()) == old_tokens

    cursor_config = json.loads((fake_clients / ".cursor" / "mcp.json").read_text())
    assert "agno" not in cursor_config["mcpServers"]
    assert cursor_config["mcpServers"]["agentos"]["url"] == MCP_URL


def test_connect_leaves_foreign_agno_entry_alone(monkeypatch, fake_os, fake_clients):
    """An "agno" entry pointing at a DIFFERENT OS is not ours to clean up."""
    monkeypatch.setenv("AGNO_ADMIN_TOKEN", fake_os.security_key)
    foreign = {"mcpServers": {"agno": {"url": "http://other-os:9999/mcp"}}}
    (fake_clients / ".cursor" / "mcp.json").write_text(json.dumps(foreign))

    result = _connect(["--clients", "cursor"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["results"][0].get("replaced_legacy") is None
    cursor_config = json.loads((fake_clients / ".cursor" / "mcp.json").read_text())
    assert cursor_config["mcpServers"]["agno"]["url"] == "http://other-os:9999/mcp"
    assert cursor_config["mcpServers"]["agentos"]["url"] == MCP_URL


# -- OAuth-protected MCP endpoints -------------------------------------------------------


def test_connect_oauth_writes_tokenless_entries_and_mints_nothing(monkeypatch, fake_clients):
    """On an OAuth-protected /mcp, apps sign in themselves: entries carry no token, no
    service accounts are minted, and each result says how to complete the sign-in."""
    fake = FakeAgentOS(auth_mode="none", oauth=True, name="OAuth OS")
    install_fake(monkeypatch, fake)

    result = _connect()
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert all(r["status"] == "needs-login" for r in payload["results"])
    assert all(r["verify"]["oauth_challenge"] for r in payload["results"])
    assert fake.create_calls == 0
    by_client = {r["client"]: r for r in payload["results"]}
    assert "codex mcp login oauth-os" in by_client["codex"]["instructions"][0]
    assert "claude mcp login oauth-os" in by_client["claude-code"]["instructions"][0]

    cursor_config = json.loads((fake_clients / ".cursor" / "mcp.json").read_text())
    assert "headers" not in cursor_config["mcpServers"]["oauth-os"]
    assert payload["os"]["mcp"]["oauth"]["authorization_servers"] == ["http://localhost:7777/mcp/auth"]


def test_connect_oauth_rerun_is_already_connected(monkeypatch, fake_clients):
    install_fake(monkeypatch, FakeAgentOS(auth_mode="none", oauth=True))
    assert _connect(["--clients", "cursor"]).exit_code == 0

    result = _connect(["--clients", "cursor"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["results"][0]["status"] == "already-connected"


def test_connect_oauth_pat_flag_mints_bearers(monkeypatch, fake_os, fake_clients):
    """--pat opts back into minted tokens on an OAuth OS (headless clients cannot run
    a browser flow); the server accepts both kinds of credential. Minting needs a REST
    credential, so this is the composed shape (security key + OAuth on /mcp)."""
    fake = FakeAgentOS(auth_mode="security_key", oauth=True)
    install_fake(monkeypatch, fake)
    monkeypatch.setenv("AGNO_ADMIN_TOKEN", fake.security_key)

    result = _connect(["--clients", "cursor", "--pat"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["results"][0]["status"] == "connected"
    assert list(fake.accounts.keys()) == ["cursor"]
    cursor_config = json.loads((fake_clients / ".cursor" / "mcp.json").read_text())
    assert cursor_config["mcpServers"]["agentos"]["headers"]["Authorization"].startswith("Bearer agno_pat_")


def test_connect_oauth_existing_pat_entry_stays_connected(monkeypatch, fake_clients):
    """A round-1 PAT entry keeps verifying on an OAuth OS (the server accepts both), so
    a re-run without --pat reports already-connected instead of tearing it down."""
    fake = FakeAgentOS(auth_mode="security_key", oauth=True)
    install_fake(monkeypatch, fake)
    monkeypatch.setenv("AGNO_ADMIN_TOKEN", fake.security_key)
    assert _connect(["--clients", "cursor", "--pat"]).exit_code == 0

    result = _connect(["--clients", "cursor"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["results"][0]["status"] == "already-connected"


def test_connect_oauth_rotate_converts_pat_entry_to_oauth(monkeypatch, fake_clients):
    install_fake(monkeypatch, FakeAgentOS(auth_mode="none", oauth=True))
    fake_token_entry = {"mcpServers": {"agentos": {"url": MCP_URL, "headers": {"Authorization": "Bearer stale"}}}}
    (fake_clients / ".cursor" / "mcp.json").write_text(json.dumps(fake_token_entry))

    result = _connect(["--clients", "cursor", "--rotate"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["results"][0]["status"] == "needs-login"
    cursor_config = json.loads((fake_clients / ".cursor" / "mcp.json").read_text())
    assert "headers" not in cursor_config["mcpServers"]["agentos"]


def test_connect_oauth_auto_surfaces_chat_apps(monkeypatch, fake_clients):
    """OAuth is exactly what the hosted Connectors UIs speak: a public HTTPS OAuth OS
    auto-surfaces claude.ai and ChatGPT setup steps (previously auth_mode none only)."""
    install_fake(monkeypatch, FakeAgentOS(auth_mode="none", oauth=True))
    result = runner.invoke(app, ["connect", "--json", "--url", "https://os.example.com"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    by_client = {r["client"]: r for r in payload["results"]}
    assert by_client["claude-ai"]["status"] == "manual"
    assert by_client["chatgpt"]["status"] == "manual"
    assert any("asked to authorize" in step for step in by_client["chatgpt"]["instructions"])


def test_connect_oauth_prints_signin_summary(monkeypatch, fake_clients):
    install_fake(monkeypatch, FakeAgentOS(auth_mode="none", oauth=True, name="OAuth OS"))
    result = runner.invoke(app, ["connect"] + URL_ARGS + ["--clients", "cursor"])
    assert result.exit_code == 0, _all_output(result)
    out = _all_output(result)
    assert "OAuth-protected" in out
    assert "sign in" in out
    assert "Restart" in out
    # auth_mode "none" describes only the REST plane; saying authorization is disabled
    # would misdescribe the OAuth-protected /mcp being connected.
    assert "Authorization is disabled" not in out


def test_connect_pat_on_oauth_only_os_fails_before_credentials(monkeypatch, fake_clients):
    """An OS whose ONLY auth is the OAuth provider refuses anonymous mints, so --pat
    with no exported credential must fail up front naming the server's missing REST
    credential -- before any prompt or config write."""
    fake = FakeAgentOS(auth_mode="none", oauth=True)
    install_fake(monkeypatch, fake)

    result = _connect(["--clients", "cursor", "--pat"])
    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert "no authentication configured" in payload["error"]
    assert "OS_SECURITY_KEY" in payload["hint"]
    assert "drop --pat" in payload["hint"]
    assert fake.create_calls == 0


def test_connect_pat_with_non_pat_credential_on_open_plane_names_the_mismatch(monkeypatch, fake_clients):
    """The open plane "accepts" any credential on reads, so a typed non-PAT value would
    pass a preflight and then fail the mint. Only a service-account bearer can
    authenticate on a server with no REST auth; the error must say exactly that
    instead of blaming a credential the server never evaluated."""
    fake = FakeAgentOS(auth_mode="none", oauth=True)
    install_fake(monkeypatch, fake)
    monkeypatch.setenv("AGNO_ADMIN_TOKEN", "any-typed-value")

    result = _connect(["--clients", "cursor", "--pat"])
    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert "only a service-account token" in payload["error"]
    assert fake.create_calls == 0


def test_connect_pat_with_seeded_admin_pat_mints_on_open_plane(monkeypatch, fake_clients):
    """The anonymous-mint refusal is anonymous-only: a verified service-account bearer
    authenticates by prefix even on an open REST plane, and one holding a minting
    scope may mint. A durable admin PAT from a protected era must keep working."""
    fake = FakeAgentOS(auth_mode="none", oauth=True)
    install_fake(monkeypatch, fake)
    monkeypatch.setenv("AGNO_ADMIN_TOKEN", fake.seed_account("ops", ["admin"]))

    result = _connect(["--clients", "cursor", "--pat"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["results"][0]["status"] == "connected"
    assert "cursor" in fake.accounts
    cursor_config = json.loads((fake_clients / ".cursor" / "mcp.json").read_text())
    assert cursor_config["mcpServers"]["agentos"]["headers"]["Authorization"].startswith("Bearer agno_pat_")


def test_connect_pat_on_plain_open_os_errors_instead_of_silently_connecting(monkeypatch, fake_clients):
    """--pat asks for durable bearers; a plain open OS cannot mint any, and silently
    writing the tokenless entry the operator opted out of would misreport success."""
    fake = FakeAgentOS(auth_mode="none")
    install_fake(monkeypatch, fake)

    result = _connect(["--clients", "cursor", "--pat"])
    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert "refuses anonymous minting" in payload["error"]
    assert "drop --pat" in payload["hint"]
    assert not (fake_clients / ".cursor" / "mcp.json").exists()


def test_connect_bare_verifier_on_open_plane_fails_before_writes(monkeypatch, fake_clients):
    """A token-protected /mcp with no authorization server to sign in through and no
    way to mint is a dead end: fail up front, never write an entry that can only 401."""
    fake = FakeAgentOS(auth_mode="none", oauth={"authorization_servers": None, "resource": None})
    install_fake(monkeypatch, fake)

    result = _connect(["--clients", "cursor"])
    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert "refuses anonymous minting" in payload["error"]
    assert "--pat" in payload["hint"]
    assert not (fake_clients / ".cursor" / "mcp.json").exists()


def test_connect_reverify_requires_secure_url_for_stored_token(monkeypatch, fake_clients):
    """Re-verification re-sends a token already stored in a matching entry, so the
    plaintext-HTTP rule applies to re-runs too, not only to fresh mints."""
    install_fake(monkeypatch, FakeAgentOS(auth_mode="none", oauth=True))
    remote_mcp = "http://10.0.0.5:7777/mcp"
    (fake_clients / ".cursor" / "mcp.json").write_text(
        json.dumps({"mcpServers": {"agentos": {"url": remote_mcp, "headers": {"Authorization": "Bearer agno_pat_x"}}}})
    )

    result = runner.invoke(app, ["connect", "--json", "--url", "http://10.0.0.5:7777", "--clients", "cursor"])
    assert result.exit_code == 1
    assert "Refusing to send" in json.loads(result.output)["error"]

    allowed = runner.invoke(
        app, ["connect", "--json", "--url", "http://10.0.0.5:7777", "--clients", "cursor", "--allow-http"]
    )
    assert allowed.exit_code == 0, allowed.output


def test_connect_oauth_mint_shaping_flags_require_pat(monkeypatch, fake_clients):
    """--name/--scopes/--expires/--privileged shape minted tokens; an OAuth run mints
    nothing, so silently ignoring them would connect with different access than the
    operator asked for. Erroring names the flags and the way out."""
    install_fake(monkeypatch, FakeAgentOS(auth_mode="none", oauth=True))

    result = _connect(["--clients", "cursor", "--scopes", "agents:run", "--expires", "7d"])
    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert "--scopes" in payload["error"] and "--expires" in payload["error"]
    assert "--pat" in payload["hint"]


def test_connect_oauth_shaping_flags_with_pat_still_mint(monkeypatch, fake_os, fake_clients):
    fake = FakeAgentOS(auth_mode="security_key", oauth=True)
    install_fake(monkeypatch, fake)
    monkeypatch.setenv("AGNO_ADMIN_TOKEN", fake.security_key)

    result = _connect(["--clients", "cursor", "--pat", "--scopes", "agents:run"])
    assert result.exit_code == 0, result.output
    assert fake.accounts["cursor"]["scopes"] == ["agents:run"]


def test_connect_oauth_rotate_notes_dangling_account(monkeypatch, fake_clients):
    """Converting a PAT entry to OAuth sign-in erases the bearer from disk but cannot
    revoke the account behind it (an OAuth run resolves no admin credential); the
    operator must be pointed at `agno tokens revoke`."""
    install_fake(monkeypatch, FakeAgentOS(auth_mode="none", oauth=True))
    fake_token_entry = {"mcpServers": {"agentos": {"url": MCP_URL, "headers": {"Authorization": "Bearer stale"}}}}
    (fake_clients / ".cursor" / "mcp.json").write_text(json.dumps(fake_token_entry))

    result = _connect(["--clients", "cursor", "--rotate"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["results"][0]["replaced_token_entry"] is True

    (fake_clients / ".cursor" / "mcp.json").write_text(json.dumps(fake_token_entry))
    human = runner.invoke(app, ["connect"] + URL_ARGS + ["--clients", "cursor", "--rotate"])
    assert human.exit_code == 0, _all_output(human)
    out = _all_output(human)
    assert "stay valid" in out
    assert "agno tokens revoke" in out


def test_connect_treats_oauth_without_authorization_servers_as_token_protected(monkeypatch, fake_os, fake_clients):
    """A bare token verifier as mcp_auth serves an mcp.oauth block with no authorization
    servers; there is nothing to sign in through, so connect mints as usual instead of
    writing a tokenless entry whose sign-in could never complete."""
    fake = FakeAgentOS(auth_mode="security_key", oauth={"authorization_servers": None, "resource": None})
    install_fake(monkeypatch, fake)
    monkeypatch.setenv("AGNO_ADMIN_TOKEN", fake.security_key)

    result = _connect(["--clients", "cursor"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["results"][0]["status"] == "connected"
    assert list(fake.accounts.keys()) == ["cursor"]


def test_connect_oauth_report_consolidates_next_steps(monkeypatch, fake_clients):
    """The prod-connect story in one readable arc: one-line rows, a single aggregated
    note for the entries this run replaced (with how to keep both OSes), a numbered
    To-finish section holding restart + per-app sign-in, and the auto-surfaced chat
    apps as one compact aside instead of two full instruction blocks."""
    prod = "https://os.example.com"
    fake = FakeAgentOS(
        auth_mode="none",
        oauth={"authorization_servers": [prod + "/"], "resource": prod + "/mcp"},
        name="AgentOS",
    )
    install_fake(monkeypatch, fake)
    (fake_clients / ".cursor" / "mcp.json").write_text(
        json.dumps({"mcpServers": {"agentos": {"url": "http://localhost:8000/mcp"}}})
    )

    result = runner.invoke(app, ["connect", "--url", prod])
    assert result.exit_code == 0, _all_output(result)
    out = _all_output(result)
    # The builtin AS is the OS itself; naming it as an issuer reads like a third party.
    assert "one-time sign-in." in out and "sign-in via" not in out
    # rich wraps at the console width, so assert the pieces, not the whole line
    assert "which pointed at" in out and "http://localhost:8000/mcp" in out
    assert "To use both" in out
    assert "To finish:" in out
    assert "1. Restart" in out
    assert "claude mcp login agentos" in out
    assert "Also reachable from the hosted chat apps" in out
    # The compact aside replaces the two full manual blocks for auto-surfaced apps.
    assert "action needed" not in out


def test_connect_menu_offers_client_config_os(monkeypatch, tmp_path, fake_clients):
    """A previously connected OS lives only in the client configs (there is no other
    memory of it); the interactive picker offers it next to the local default with
    provenance, and picking the remote still runs the trust gate."""
    from tests.test_discovery import _install_hosts

    monkeypatch.chdir(tmp_path)
    _make_interactive(monkeypatch)
    (fake_clients / ".cursor" / "mcp.json").write_text(
        json.dumps({"mcpServers": {"prod-os": {"url": "http://prodhost:9000/mcp"}}})
    )
    _install_hosts(
        monkeypatch,
        {"localhost:7777": FakeAgentOS(), "prodhost:9000": FakeAgentOS(name="Prod OS", auth_mode="none", oauth=True)},
    )

    result = runner.invoke(app, ["connect", "--clients", "cursor"], input="2\n\n")
    assert result.exit_code == 0, _all_output(result)
    out = _all_output(result)
    assert "Which one do you want to connect?" in out
    assert "configured in Cursor" in out
    assert "from your Cursor MCP config" in out
    # The existing tokenless entry for the OAuth-protected prod OS verifies in place.
    assert "already ok" in out
