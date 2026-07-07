"""Discovery: structured /info fields, probe fallbacks, and failure modes."""

import httpx
import pytest

from agnoctl.discovery import discover
from agnoctl.errors import CLIError
from tests.conftest import FakeAgentOS, install_fake


def test_discover_via_info_fields(fake_os):
    info = discover("http://localhost:7777")
    assert info.discovered_via == "info"
    assert info.mcp_enabled is True
    assert info.mcp_url == "http://localhost:7777/mcp"
    assert info.auth_mode == "security_key"
    assert info.version == "2.7.0"


def test_discover_probe_fallback_security_key(monkeypatch):
    fake = FakeAgentOS(info_discovery=False)
    install_fake(monkeypatch, fake)
    info = discover("http://localhost:7777")
    assert info.discovered_via == "probe"
    assert info.mcp_enabled is True
    assert info.auth_mode == "security_key"


def test_discover_probe_fallback_jwt(monkeypatch):
    fake = FakeAgentOS(info_discovery=False, auth_mode="jwt")
    install_fake(monkeypatch, fake)
    info = discover("http://localhost:7777")
    assert info.auth_mode == "jwt"


def test_discover_probe_fallback_none_auth(monkeypatch):
    fake = FakeAgentOS(info_discovery=False, auth_mode="none")
    install_fake(monkeypatch, fake)
    info = discover("http://localhost:7777")
    assert info.auth_mode == "none"


def test_discover_probe_detects_mcp_disabled(monkeypatch):
    fake = FakeAgentOS(info_discovery=False, mcp_enabled=False)
    install_fake(monkeypatch, fake)
    info = discover("http://localhost:7777")
    assert info.mcp_enabled is False
    assert info.mcp_path is None


def test_discover_unreachable_raises(monkeypatch):
    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    import agnoctl.http as http_module

    monkeypatch.setattr(http_module, "_transport_override", httpx.MockTransport(refuse))
    monkeypatch.delenv("AGENTOS_URL", raising=False)
    with pytest.raises(CLIError) as exc_info:
        discover(None)
    assert "No running AgentOS" in exc_info.value.message


def test_discover_env_var_url(monkeypatch, fake_os):
    monkeypatch.setenv("AGENTOS_URL", "http://envhost:9000")
    info = discover(None)
    assert info.base_url == "http://envhost:9000"


def test_default_urls_probe_bumped_ports():
    from agnoctl.discovery import DEFAULT_URLS

    # When 7777 is taken, users commonly bump to 7778/7779; those must be probed too.
    assert "http://localhost:7778" in DEFAULT_URLS
    assert "http://localhost:7779" in DEFAULT_URLS


def test_discover_finds_os_on_bumped_port_when_7777_is_taken(monkeypatch):
    """An AgentOS on 7778 (7777 occupied) must be found by autodiscovery, not missed."""
    fake = FakeAgentOS()

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.port != 7778:
            raise httpx.ConnectError("connection refused", request=request)
        return fake.handler(request)

    import agnoctl.http as http_module

    monkeypatch.setattr(http_module, "_transport_override", httpx.MockTransport(handler))
    monkeypatch.delenv("AGENTOS_URL", raising=False)

    info = discover(None)
    assert info.base_url == "http://localhost:7778"
    assert info.mcp_url == "http://localhost:7778/mcp"
