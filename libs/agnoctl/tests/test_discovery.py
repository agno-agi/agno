"""Discovery: structured /info fields, probe fallbacks, and failure modes."""

import httpx
import pytest

from agnoctl.discovery import _read_env_value, discover
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


def test_discover_unreachable_raises(monkeypatch, tmp_path):
    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    import agnoctl.http as http_module

    monkeypatch.setattr(http_module, "_transport_override", httpx.MockTransport(refuse))
    monkeypatch.delenv("AGENTOS_URL", raising=False)
    monkeypatch.chdir(tmp_path)  # no AGENTOS_URL in a .env file to pick up
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


def test_discover_finds_os_on_bumped_port_when_7777_is_taken(monkeypatch, tmp_path):
    """An AgentOS on 7778 (7777 occupied) must be found by autodiscovery, not missed."""
    fake = FakeAgentOS()

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.port != 7778:
            raise httpx.ConnectError("connection refused", request=request)
        return fake.handler(request)

    import agnoctl.http as http_module

    monkeypatch.setattr(http_module, "_transport_override", httpx.MockTransport(handler))
    monkeypatch.delenv("AGENTOS_URL", raising=False)
    monkeypatch.chdir(tmp_path)  # exercise the localhost-defaults path, not a .env file

    info = discover(None)
    assert info.base_url == "http://localhost:7778"
    assert info.mcp_url == "http://localhost:7778/mcp"


def test_discover_env_file_url(monkeypatch, tmp_path, fake_os):
    """AGENTOS_URL in .env.production is picked up when neither --url nor the env var is set."""
    (tmp_path / ".env.production").write_text('AGENTOS_URL="http://filehost:9000"\n')
    monkeypatch.chdir(tmp_path)
    info = discover(None)
    assert info.base_url == "http://filehost:9000"
    assert info.url_source == "env-file"
    assert info.url_source_file == ".env.production"


def test_discover_env_var_beats_env_file(monkeypatch, tmp_path, fake_os):
    """The process environment takes precedence over a value sitting in a .env file."""
    (tmp_path / ".env.production").write_text("AGENTOS_URL=http://filehost:9000\n")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("AGENTOS_URL", "http://envhost:9000")
    info = discover(None)
    assert info.base_url == "http://envhost:9000"
    assert info.url_source == "env"


def test_discover_env_production_beats_env(monkeypatch, tmp_path, fake_os):
    """.env.production is preferred over .env when both define AGENTOS_URL."""
    (tmp_path / ".env.production").write_text("AGENTOS_URL=http://prodhost:9000\n")
    (tmp_path / ".env").write_text("AGENTOS_URL=http://localhost:7777\n")
    monkeypatch.chdir(tmp_path)
    info = discover(None)
    assert info.base_url == "http://prodhost:9000"
    assert info.url_source_file == ".env.production"


def test_read_env_value_parsing(tmp_path):
    """export prefix and surrounding quotes are stripped; the last uncommented value wins."""
    path = tmp_path / ".env.production"
    path.write_text("# comment\nexport AGENTOS_URL='http://first'\nAGENTOS_URL=\"http://second\"\n")
    assert _read_env_value(path, "AGENTOS_URL") == "http://second"


def test_read_env_value_ignores_comments_and_missing(tmp_path):
    """A commented-out assignment (as `down.sh` leaves on teardown) is not read; absent → None."""
    path = tmp_path / ".env.production"
    path.write_text("# AGENTOS_URL=http://commented\nOTHER=x\n")
    assert _read_env_value(path, "AGENTOS_URL") is None
    assert _read_env_value(tmp_path / "does-not-exist", "AGENTOS_URL") is None
