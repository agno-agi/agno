"""`agno disconnect` flows: URL-matched removal, offline fallback, and --revoke."""

import json

import httpx
from typer.testing import CliRunner

from agnoctl.main import app
from tests.conftest import FakeAgentOS, install_fake
from tests.conftest import all_output as _all_output

runner = CliRunner()

URL_ARGS = ["--url", "http://localhost:7777"]
MCP_URL = "http://localhost:7777/mcp"


def _connect(args=(), **kwargs):
    return runner.invoke(app, ["connect", "--json"] + URL_ARGS + list(args), **kwargs)


def _disconnect(args=(), **kwargs):
    return runner.invoke(app, ["disconnect", "--json"] + URL_ARGS + list(args), **kwargs)


def _refuse_all(monkeypatch):
    """No AgentOS answers anywhere: the torn-down-deployment situation."""

    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    import agnoctl.http as http_module

    monkeypatch.setattr(http_module, "_transport_override", httpx.MockTransport(refuse))


def test_disconnect_removes_connected_entries(monkeypatch, fake_os, fake_clients):
    monkeypatch.setenv("AGNO_ADMIN_TOKEN", fake_os.security_key)
    assert _connect().exit_code == 0

    result = _disconnect()
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert {r["client"] for r in payload["results"]} == {"claude-code", "codex", "cursor"}
    assert all(r["status"] == "removed" for r in payload["results"])
    assert all(r["removed"] == ["agentos"] for r in payload["results"])

    cursor_config = json.loads((fake_clients / ".cursor" / "mcp.json").read_text())
    assert "agentos" not in cursor_config["mcpServers"]
    claude_config = json.loads((fake_clients / ".claude.json").read_text())
    assert "agentos" not in (claude_config.get("mcpServers") or {})


def test_disconnect_json_document_shape(monkeypatch, fake_os, fake_clients):
    monkeypatch.setenv("AGNO_ADMIN_TOKEN", fake_os.security_key)
    assert _connect().exit_code == 0
    payload = json.loads(_disconnect().output)
    assert set(payload) == {"os", "server_name", "target_urls", "results", "revocations", "exit_code"}
    assert payload["os"]["url"] == "http://localhost:7777"
    assert payload["server_name"] is None
    assert payload["target_urls"] == ["http://localhost:7777"]
    assert payload["revocations"] == []
    assert payload["exit_code"] == 0


def test_disconnect_absent_entry_is_not_found(monkeypatch, fake_os, fake_clients):
    result = _disconnect()
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert all(r["status"] == "not-found" for r in payload["results"])


def test_disconnect_scopes_to_requested_clients(monkeypatch, fake_os, fake_clients):
    monkeypatch.setenv("AGNO_ADMIN_TOKEN", fake_os.security_key)
    assert _connect().exit_code == 0

    result = _disconnect(["--clients", "cursor"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert [r["client"] for r in payload["results"]] == ["cursor"]

    # Only cursor was cleared; the Claude Code entry is untouched.
    cursor_config = json.loads((fake_clients / ".cursor" / "mcp.json").read_text())
    assert "agentos" not in cursor_config["mcpServers"]
    claude_config = json.loads((fake_clients / ".claude.json").read_text())
    assert "agentos" in claude_config["mcpServers"]


def test_disconnect_prints_restart_hint_and_token_note(monkeypatch, fake_os, fake_clients):
    monkeypatch.setenv("AGNO_ADMIN_TOKEN", fake_os.security_key)
    assert _connect(["--clients", "cursor"]).exit_code == 0

    result = runner.invoke(app, ["disconnect"] + URL_ARGS + ["--clients", "cursor"])
    assert result.exit_code == 0, _all_output(result)
    out = _all_output(result)
    assert "Restart" in out and "Cursor" in out
    # Without --revoke the minted tokens stay live; the operator must be told.
    assert "stay valid" in out


def test_disconnect_no_token_note_on_authless_os(monkeypatch, fake_clients):
    install_fake(monkeypatch, FakeAgentOS(auth_mode="none"))
    assert _connect(["--clients", "cursor"]).exit_code == 0

    result = runner.invoke(app, ["disconnect"] + URL_ARGS + ["--clients", "cursor"])
    assert result.exit_code == 0, _all_output(result)
    # Nothing was ever minted, so there is nothing to tell the operator to revoke.
    assert "stay valid" not in _all_output(result)


def test_disconnect_removes_derived_named_entry(monkeypatch, fake_clients):
    fake = FakeAgentOS(name="Customer Support")
    install_fake(monkeypatch, fake)
    monkeypatch.setenv("AGNO_ADMIN_TOKEN", fake.security_key)
    assert _connect(["--clients", "cursor"]).exit_code == 0

    result = _disconnect(["--clients", "cursor"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["results"][0]["removed"] == ["customer-support"]


def test_disconnect_server_name_flag_removes_exactly_that_entry(monkeypatch, fake_os, fake_clients):
    monkeypatch.setenv("AGNO_ADMIN_TOKEN", fake_os.security_key)
    assert _connect(["--clients", "cursor", "--server-name", "custom"]).exit_code == 0

    result = _disconnect(["--clients", "cursor", "--server-name", "custom"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["results"][0]["removed"] == ["custom"]


def test_disconnect_server_name_flag_never_touches_other_entries(monkeypatch, fake_os, fake_clients):
    """--server-name means that one entry: an "agno" entry for another OS survives."""
    monkeypatch.setenv("AGNO_ADMIN_TOKEN", fake_os.security_key)
    (fake_clients / ".cursor" / "mcp.json").write_text(
        json.dumps({"mcpServers": {"custom": {"url": MCP_URL}, "agno": {"url": "http://other-os:9999/mcp"}}})
    )

    result = _disconnect(["--clients", "cursor", "--server-name", "custom"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["results"][0]["removed"] == ["custom"]
    kept = json.loads((fake_clients / ".cursor" / "mcp.json").read_text())["mcpServers"]
    assert kept["agno"]["url"] == "http://other-os:9999/mcp"


def test_disconnect_offline_removes_entries_by_url(monkeypatch, tmp_path, fake_clients):
    """The OS is gone (the usual reason to disconnect): entries are located by the
    addresses discovery would have tried -- including identity-derived names the
    offline path could never guess -- and foreign entries survive."""
    (fake_clients / ".cursor" / "mcp.json").write_text(
        json.dumps(
            {
                "mcpServers": {
                    "customer-support": {"url": MCP_URL},
                    "agno": {"url": MCP_URL},
                    "keep-me": {"url": "http://other-os:9999/mcp"},
                }
            }
        )
    )
    _refuse_all(monkeypatch)
    monkeypatch.chdir(tmp_path)

    result = _disconnect(["--clients", "cursor"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["os"] is None
    assert "http://localhost:7777" in payload["target_urls"]
    assert sorted(payload["results"][0]["removed"]) == ["agno", "customer-support"]
    kept = json.loads((fake_clients / ".cursor" / "mcp.json").read_text())["mcpServers"]
    assert list(kept) == ["keep-me"]


def test_disconnect_offline_uses_env_file_url(monkeypatch, tmp_path, fake_clients):
    """A torn-down deployed OS: its env-file address still locates the entries."""
    (fake_clients / ".cursor" / "mcp.json").write_text(
        json.dumps({"mcpServers": {"live-railway": {"url": "https://prodhost:9000/mcp"}}})
    )
    (tmp_path / "work").mkdir()
    (tmp_path / "work" / ".env.production").write_text("AGENTOS_URL=https://prodhost:9000\n")
    _refuse_all(monkeypatch)
    monkeypatch.chdir(tmp_path / "work")

    result = runner.invoke(app, ["disconnect", "--json", "--clients", "cursor"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["results"][0]["removed"] == ["live-railway"]


def test_disconnect_targeted_os_leaves_other_os_entries(monkeypatch, fake_os, fake_clients):
    """Two OSes connected: disconnecting one never touches the other's entries, even
    the legacy-named one."""
    monkeypatch.setenv("AGNO_ADMIN_TOKEN", fake_os.security_key)
    (fake_clients / ".cursor" / "mcp.json").write_text(
        json.dumps({"mcpServers": {"agentos": {"url": MCP_URL}, "agno": {"url": "http://other-os:9999/mcp"}}})
    )

    result = _disconnect(["--clients", "cursor"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["results"][0]["removed"] == ["agentos"]
    kept = json.loads((fake_clients / ".cursor" / "mcp.json").read_text())["mcpServers"]
    assert kept["agno"]["url"] == "http://other-os:9999/mcp"


def test_disconnect_also_clears_legacy_agno_entry(monkeypatch, fake_os, fake_clients):
    """An agnoctl 0.1.x config (entry named "agno") pointing at this OS is cleaned."""
    monkeypatch.setenv("AGNO_ADMIN_TOKEN", fake_os.security_key)
    assert _connect(["--clients", "cursor", "--server-name", "agno"]).exit_code == 0

    result = _disconnect(["--clients", "cursor"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["results"][0]["removed"] == ["agno"]


def test_disconnect_revoke_revokes_service_accounts(monkeypatch, fake_os, fake_clients):
    monkeypatch.setenv("AGNO_ADMIN_TOKEN", fake_os.security_key)
    assert _connect().exit_code == 0
    assert fake_os.active_tokens()

    result = _disconnect(["--revoke"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    revoked = {r["account"]: r["status"] for r in payload["revocations"]}
    assert revoked == {"claude-code": "revoked", "codex": "revoked", "cursor": "revoked"}
    assert fake_os.active_tokens() == []


def test_disconnect_revoke_shared_account_name(monkeypatch, fake_os, fake_clients):
    monkeypatch.setenv("AGNO_ADMIN_TOKEN", fake_os.security_key)
    assert _connect(["--name", "shared"]).exit_code == 0

    result = _disconnect(["--revoke", "--name", "shared"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert [r["account"] for r in payload["revocations"]] == ["shared"]
    assert fake_os.active_tokens() == []


def test_disconnect_revoke_missing_account_is_not_found(monkeypatch, fake_os, fake_clients):
    monkeypatch.setenv("AGNO_ADMIN_TOKEN", fake_os.security_key)
    result = _disconnect(["--revoke", "--clients", "cursor"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["revocations"][0]["status"] == "not-found"


def test_disconnect_revoke_requires_reachable_os(monkeypatch, tmp_path, fake_clients):
    """--revoke must talk to the OS, so an unreachable OS is fatal there (and only there)."""
    _refuse_all(monkeypatch)
    monkeypatch.chdir(tmp_path)

    result = _disconnect(["--revoke"])
    assert result.exit_code == 1
    assert "No running AgentOS" in json.loads(result.output)["error"]


def test_disconnect_chat_apps_print_manual_steps(monkeypatch, fake_os, fake_clients):
    result = _disconnect(["--clients", "chatgpt"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["results"][0]["client"] == "chatgpt"
    assert payload["results"][0]["status"] == "manual"
    assert "Connectors" in payload["results"][0]["instructions"][0]


def test_disconnect_partial_failure_exit_code(monkeypatch, fake_os, fake_clients):
    """A corrupt config fails that client only (via --server-name's strict remove);
    output stays one JSON document, exit 3."""
    monkeypatch.setenv("AGNO_ADMIN_TOKEN", fake_os.security_key)
    assert _connect().exit_code == 0
    (fake_clients / ".cursor" / "mcp.json").write_text("{corrupt")

    result = _disconnect(["--server-name", "agentos"])
    assert result.exit_code == 3
    payload = json.loads(result.output)
    by_client = {r["client"]: r for r in payload["results"]}
    assert by_client["cursor"]["status"] == "failed"
    assert "Refusing to modify" in by_client["cursor"]["error"]
    assert by_client["claude-code"]["status"] == "removed"


def test_disconnect_oauth_os_removes_entry_without_token_note(monkeypatch, fake_clients):
    """Disconnecting from an OAuth OS: URL-matched removal works on tokenless entries,
    and no revoke reminder prints (nothing was minted; sign-in state lives in the app)."""
    install_fake(monkeypatch, FakeAgentOS(auth_mode="none", oauth=True))
    assert _connect(["--clients", "cursor"]).exit_code == 0

    result = runner.invoke(app, ["disconnect"] + URL_ARGS + ["--clients", "cursor"])
    assert result.exit_code == 0, _all_output(result)
    out = _all_output(result)
    assert "Restart" in out
    assert "stay valid" not in out
    cursor_config = json.loads((fake_clients / ".cursor" / "mcp.json").read_text())
    assert cursor_config["mcpServers"] == {}


def test_disconnect_oauth_os_reminds_when_removed_entry_carried_pat(monkeypatch, fake_clients):
    """connect --pat mints real accounts on an OAuth OS, so the revoke reminder must key
    on what the removed entries carried, not on the server's auth mode: this machine's
    entry holds a token whose account stays valid after the config removal."""
    fake = FakeAgentOS(auth_mode="security_key", oauth=True)
    install_fake(monkeypatch, fake)
    monkeypatch.setenv("AGNO_ADMIN_TOKEN", fake.security_key)
    assert _connect(["--clients", "cursor", "--pat"]).exit_code == 0

    result = runner.invoke(app, ["disconnect"] + URL_ARGS + ["--clients", "cursor"])
    assert result.exit_code == 0, _all_output(result)
    assert "stay valid" in _all_output(result)


def test_disconnect_no_token_note_for_tokenless_entries_on_protected_os(monkeypatch, fake_clients):
    """The inverse direction of keying the reminder on removed tokens: a token-protected
    OS whose removed entry carries no token (written when auth was off) has nothing to
    revoke, so no reminder prints."""
    install_fake(monkeypatch, FakeAgentOS(auth_mode="security_key"))
    (fake_clients / ".cursor" / "mcp.json").write_text(json.dumps({"mcpServers": {"agentos": {"url": MCP_URL}}}))

    result = runner.invoke(app, ["disconnect"] + URL_ARGS + ["--clients", "cursor"])
    assert result.exit_code == 0, _all_output(result)
    out = _all_output(result)
    assert "Restart" in out
    assert "stay valid" not in out


def test_matches_targets_respects_base_path():
    """Path-routed deployments: two AgentOS on one host must never match each other,
    and a path prefix only matches on a segment boundary."""
    from agnoctl.commands.disconnect import _matches_targets

    assert _matches_targets("https://os.example.com/customer-a/mcp", ["https://os.example.com/customer-a"])
    assert not _matches_targets("https://os.example.com/customer-b/mcp", ["https://os.example.com/customer-a"])
    assert not _matches_targets("https://os.example.com/customer-abc/mcp", ["https://os.example.com/customer-a"])
    # A pathless target (the usual base URL) matches any path on that host.
    assert _matches_targets("http://localhost:7777/mcp", ["http://localhost:7777"])
    assert _matches_targets("http://localhost:7777/custom/mcp", ["http://localhost:7777"])
    assert not _matches_targets("http://localhost:7778/mcp", ["http://localhost:7777"])


def test_disconnect_path_routed_os_leaves_sibling_entries(monkeypatch, tmp_path, fake_clients):
    """Disconnecting a path-routed OS (--url https://host/customer-a) must not remove a
    sibling tenant's entry on the same host."""
    (fake_clients / ".cursor" / "mcp.json").write_text(
        json.dumps(
            {
                "mcpServers": {
                    "customer-a": {"url": "https://os.example.com/customer-a/mcp"},
                    "customer-b": {"url": "https://os.example.com/customer-b/mcp"},
                }
            }
        )
    )
    _refuse_all(monkeypatch)
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(
        app, ["disconnect", "--json", "--url", "https://os.example.com/customer-a", "--clients", "cursor"]
    )
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["results"][0]["removed"] == ["customer-a"]
    kept = json.loads((fake_clients / ".cursor" / "mcp.json").read_text())["mcpServers"]
    assert list(kept) == ["customer-b"]


def test_disconnect_removes_target_entry_shadowed_by_foreign_same_name(monkeypatch, fake_os, fake_clients):
    """A project-scope entry for ANOTHER OS shadows the global entry for the target OS
    under the same name: the target's entry must still be removed (per-scope URL guard),
    and the foreign shadowing entry must survive."""
    monkeypatch.setenv("AGNO_ADMIN_TOKEN", fake_os.security_key)
    (fake_clients / ".cursor").joinpath("mcp.json").write_text(
        json.dumps({"mcpServers": {"agentos": {"url": MCP_URL}}})
    )
    # fake_clients uses one directory as both home and cwd, so the project scope is
    # cwd/.cursor/mcp.json == home/.cursor/mcp.json; build a distinct project dir.
    import agnoctl.commands.disconnect as disconnect_module
    from agnoctl.clients.cursor import CursorAdapter

    proj = fake_clients / "proj"
    (proj / ".cursor").mkdir(parents=True)
    (proj / ".cursor" / "mcp.json").write_text(
        json.dumps({"mcpServers": {"agentos": {"url": "http://other-os:9999/mcp"}}})
    )

    def build(home=None, cwd=None, project=False):
        return {"cursor": CursorAdapter(home=fake_clients, cwd=proj)}

    monkeypatch.setattr(disconnect_module, "build_adapters", build)

    result = _disconnect(["--clients", "cursor"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["results"][0]["removed"] == ["agentos"]
    # The target's global entry is gone; the foreign project entry survives.
    global_servers = json.loads((fake_clients / ".cursor" / "mcp.json").read_text())["mcpServers"]
    assert "agentos" not in global_servers
    project_servers = json.loads((proj / ".cursor" / "mcp.json").read_text())["mcpServers"]
    assert project_servers["agentos"]["url"] == "http://other-os:9999/mcp"
