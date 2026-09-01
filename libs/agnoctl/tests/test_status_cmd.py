"""`agno status` output: the OS posture summary and per-client connection state."""

import json

from typer.testing import CliRunner

from agnoctl.main import app
from tests.conftest import FakeAgentOS, install_fake
from tests.conftest import all_output as _all_output

runner = CliRunner()

URL_ARGS = ["--url", "http://localhost:7777"]
MCP_URL = "http://localhost:7777/mcp"


def test_status_reports_mcp_oauth_alongside_rest_auth_mode(monkeypatch, fake_os, fake_clients):
    """auth_mode is the REST plane only; without the MCP auth line an OAuth-protected
    /mcp would read as an unsecured deployment ("Auth mode: none")."""
    install_fake(monkeypatch, FakeAgentOS(auth_mode="none", oauth=True))

    result = runner.invoke(app, ["status"] + URL_ARGS)
    assert result.exit_code == 0, _all_output(result)
    out = _all_output(result)
    assert "Auth mode: none" in out
    assert "MCP auth: OAuth via http://localhost:7777/mcp/auth" in out


def test_status_no_mcp_auth_line_without_oauth_block(monkeypatch, fake_os, fake_clients):
    result = runner.invoke(app, ["status"] + URL_ARGS)
    assert result.exit_code == 0, _all_output(result)
    assert "MCP auth" not in _all_output(result)


def test_status_finds_the_derived_entry_name_connect_writes(monkeypatch, fake_clients):
    """The default lookup must match what connect writes today (the OS-name slug),
    not the legacy "agno" naming -- otherwise every default status run reports
    freshly connected clients as not connected."""
    fake = FakeAgentOS(name="Customer Support")
    install_fake(monkeypatch, fake)
    monkeypatch.setenv("AGNO_ADMIN_TOKEN", fake.security_key)
    connect = runner.invoke(app, ["connect", "--json"] + URL_ARGS + ["--clients", "cursor"])
    assert connect.exit_code == 0, connect.output

    result = runner.invoke(app, ["status", "--json"] + URL_ARGS)
    assert result.exit_code == 0, result.output
    clients = {c["client"]: c for c in json.loads(result.output)["clients"]}
    assert clients["cursor"]["configured"] is True
