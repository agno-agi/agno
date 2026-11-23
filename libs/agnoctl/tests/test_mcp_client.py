"""MCP verification client: JSON and SSE payloads, auth failures."""

from agnoctl.mcp_client import verify_mcp
from tests.conftest import FakeAgentOS, install_fake

MCP_URL = "http://localhost:7777/mcp"


def test_verify_ok_with_valid_token(monkeypatch, fake_os):
    result = verify_mcp(MCP_URL, token=fake_os.security_key)
    assert result.ok is True
    assert "run_agent" in result.tools


def test_verify_rejected_without_token(monkeypatch, fake_os):
    result = verify_mcp(MCP_URL, token=None)
    assert result.ok is False
    assert result.status_code == 401


def test_verify_rejected_with_bad_token(monkeypatch, fake_os):
    result = verify_mcp(MCP_URL, token="agno_pat_wrong")
    assert result.ok is False
    assert result.status_code == 401


def test_verify_parses_sse_responses(monkeypatch):
    fake = FakeAgentOS(sse_responses=True)
    install_fake(monkeypatch, fake)
    result = verify_mcp(MCP_URL, token=fake.security_key)
    assert result.ok is True
    assert result.tools == fake.mcp_tools


def test_verify_open_server_no_token(monkeypatch):
    fake = FakeAgentOS(auth_mode="none")
    install_fake(monkeypatch, fake)
    result = verify_mcp(MCP_URL, token=None)
    assert result.ok is True


def test_verify_404_when_mcp_disabled(monkeypatch):
    fake = FakeAgentOS(mcp_enabled=False)
    install_fake(monkeypatch, fake)
    result = verify_mcp(MCP_URL, token=fake.security_key)
    assert result.ok is False
    assert result.status_code == 404


def test_verify_never_raises_on_malformed_result(monkeypatch):
    """A server returning a garbage tools/list result must yield a failed result, not a traceback."""
    import httpx

    def handler(request: httpx.Request) -> httpx.Response:
        import json as json_module

        message = json_module.loads(request.content) if request.content else {}
        if message.get("method") == "initialize":
            return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": {}})
        if message.get("method") == "tools/list":
            return httpx.Response(200, json={"jsonrpc": "2.0", "id": 2, "result": "not-a-dict"})
        return httpx.Response(202)

    import agnoctl.http as http_module

    monkeypatch.setattr(http_module, "_transport_override", httpx.MockTransport(handler))
    result = verify_mcp(MCP_URL, token="anything")
    assert result.ok is True
    assert result.tools == []


def test_verify_expect_oauth_challenge_accepts_401_with_www_authenticate(monkeypatch):
    fake = FakeAgentOS(auth_mode="none", oauth=True)
    install_fake(monkeypatch, fake)
    result = verify_mcp("http://localhost:7777/mcp", token=None, expect_oauth_challenge=True)
    assert result.ok is True
    assert result.oauth_challenge is True
    assert result.status_code == 401
    assert result.tools == []


def test_verify_expect_oauth_challenge_rejects_bare_401(monkeypatch):
    """A 401 without a WWW-Authenticate header means clients cannot discover the AS:
    that is a broken OAuth setup, not a healthy one."""
    fake = FakeAgentOS(auth_mode="security_key")
    install_fake(monkeypatch, fake)
    result = verify_mcp("http://localhost:7777/mcp", token=None, expect_oauth_challenge=True)
    assert result.ok is False
    assert "no WWW-Authenticate" in (result.error or "")


def test_verify_401_without_expectation_still_fails(monkeypatch):
    fake = FakeAgentOS(auth_mode="none", oauth=True)
    install_fake(monkeypatch, fake)
    result = verify_mcp("http://localhost:7777/mcp", token=None)
    assert result.ok is False
