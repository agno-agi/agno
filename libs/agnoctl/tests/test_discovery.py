"""Discovery: structured /info fields, probe fallbacks, and failure modes."""

import httpx
import pytest

from agnoctl.discovery import _agentos_url_from_env_files, _read_env_value, discover, discover_all
from agnoctl.errors import CLIError
from tests.conftest import FakeAgentOS, install_fake


def _install_hosts(monkeypatch, live):
    """Transport where only 'host:port' keys in `live` answer (with that fake AgentOS);
    every other URL is connection-refused, like a dead localhost port."""
    import agnoctl.http as http_module

    def handler(request: httpx.Request) -> httpx.Response:
        fake = live.get(request.url.host + ":" + str(request.url.port))
        if fake is None:
            raise httpx.ConnectError("connection refused", request=request)
        return fake.handler(request)

    monkeypatch.setattr(http_module, "_transport_override", httpx.MockTransport(handler))
    for var in ("AGNO_ADMIN_TOKEN", "OS_SECURITY_KEY", "AGENTOS_URL"):
        monkeypatch.delenv(var, raising=False)


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


def test_read_env_value_strips_inline_comment(tmp_path):
    """An unquoted value ends at a whitespace-preceded '#' (as a deploy note might append)."""
    path = tmp_path / ".env.production"
    path.write_text("AGENTOS_URL=http://host:9000  # deployed by up.sh\n")
    assert _read_env_value(path, "AGENTOS_URL") == "http://host:9000"


def test_read_env_value_keeps_url_fragment(tmp_path):
    """A '#' with no leading whitespace is a literal (URL fragment), not a comment."""
    path = tmp_path / ".env"
    path.write_text("AGENTOS_URL=http://host:9000/path#frag\n")
    assert _read_env_value(path, "AGENTOS_URL") == "http://host:9000/path#frag"


def test_read_env_value_quoted_value_ignores_trailing_comment(tmp_path):
    """A quoted value keeps only its inner text; a trailing inline comment is dropped."""
    path = tmp_path / ".env"
    path.write_text('AGENTOS_URL="http://host:9000"  # prod\n')
    assert _read_env_value(path, "AGENTOS_URL") == "http://host:9000"


def test_read_env_value_handles_utf8_bom(tmp_path):
    """A BOM-prefixed file (some Windows editors add one) still resolves the key."""
    path = tmp_path / ".env.production"
    path.write_text("AGENTOS_URL=http://host:9000\n", encoding="utf-8-sig")
    assert _read_env_value(path, "AGENTOS_URL") == "http://host:9000"


def test_read_env_value_non_utf8_returns_none(tmp_path):
    """A non-UTF-8 file is skipped (None), not a crash."""
    path = tmp_path / ".env.production"
    path.write_bytes(b"AGENTOS_URL=http://host\xff\xfe\n")
    assert _read_env_value(path, "AGENTOS_URL") is None


def test_read_env_value_empty_assignment_clears_earlier(tmp_path):
    """The last assignment wins, so a trailing empty AGENTOS_URL= clears an earlier value."""
    path = tmp_path / ".env.production"
    path.write_text("AGENTOS_URL=http://old:9000\nAGENTOS_URL=\n")
    assert _read_env_value(path, "AGENTOS_URL") is None


def test_env_file_slash_only_value_falls_through(monkeypatch, tmp_path):
    """A slash-only .env.production value normalizes to empty, so .env is still consulted."""
    (tmp_path / ".env.production").write_text("AGENTOS_URL=/\n")
    (tmp_path / ".env").write_text("AGENTOS_URL=http://realhost:9000\n")
    monkeypatch.chdir(tmp_path)
    assert _agentos_url_from_env_files() == ("http://realhost:9000", ".env")


def test_discover_invalid_env_file_url_raises_clean_error(monkeypatch, tmp_path):
    """A malformed env-file URL (e.g. an un-expanded ${PORT}) fails as a CLIError, not a traceback."""
    (tmp_path / ".env.production").write_text("AGENTOS_URL=http://host:${PORT}\n")
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("AGENTOS_URL", raising=False)
    with pytest.raises(CLIError) as exc_info:
        discover(None)
    assert "Invalid AgentOS URL" in exc_info.value.message


# -- discover_all ------------------------------------------------------------------------


def test_discover_all_unions_env_file_and_localhost(monkeypatch, tmp_path):
    """A deploy's env-file URL must not mask a locally running OS: both are returned,
    env-file first (it is the default the selection menu offers)."""
    (tmp_path / ".env.production").write_text("AGENTOS_URL=http://prodhost:9000\n")
    monkeypatch.chdir(tmp_path)
    _install_hosts(
        monkeypatch,
        {"prodhost:9000": FakeAgentOS(name="Live Railway"), "localhost:7777": FakeAgentOS()},
    )
    found = discover_all(None)
    assert [i.base_url for i in found] == ["http://prodhost:9000", "http://localhost:7777"]
    assert found[0].url_source == "env-file"
    assert found[0].url_source_file == ".env.production"
    assert found[0].name == "Live Railway"
    assert found[1].url_source == "default"


def test_discover_all_only_local_when_env_file_target_is_down(monkeypatch, tmp_path):
    (tmp_path / ".env.production").write_text("AGENTOS_URL=http://prodhost:9000\n")
    monkeypatch.chdir(tmp_path)
    _install_hosts(monkeypatch, {"localhost:7777": FakeAgentOS()})
    found = discover_all(None)
    assert [i.base_url for i in found] == ["http://localhost:7777"]


def test_discover_all_explicit_url_is_single_target(monkeypatch, tmp_path):
    """--url is authoritative: no localhost probing behind the operator's back."""
    monkeypatch.chdir(tmp_path)
    _install_hosts(monkeypatch, {"flaghost:9000": FakeAgentOS(), "localhost:7777": FakeAgentOS()})
    found = discover_all("http://flaghost:9000")
    assert [i.base_url for i in found] == ["http://flaghost:9000"]
    assert found[0].url_source == "flag"


def test_discover_all_exported_env_var_is_single_target(monkeypatch, tmp_path):
    """An exported AGENTOS_URL is deliberate (not ambient): it stays a single target."""
    monkeypatch.chdir(tmp_path)
    _install_hosts(monkeypatch, {"envhost:9000": FakeAgentOS(), "localhost:7777": FakeAgentOS()})
    monkeypatch.setenv("AGENTOS_URL", "http://envhost:9000")
    found = discover_all(None)
    assert [i.base_url for i in found] == ["http://envhost:9000"]
    assert found[0].url_source == "env"


def test_discover_all_env_file_url_equal_to_default_is_deduped(monkeypatch, tmp_path):
    (tmp_path / ".env").write_text("AGENTOS_URL=http://localhost:7777\n")
    monkeypatch.chdir(tmp_path)
    _install_hosts(monkeypatch, {"localhost:7777": FakeAgentOS()})
    found = discover_all(None)
    assert [i.base_url for i in found] == ["http://localhost:7777"]
    assert found[0].url_source == "env-file"


def test_discover_all_none_alive_raises(monkeypatch, tmp_path):
    (tmp_path / ".env.production").write_text("AGENTOS_URL=http://prodhost:9000\n")
    monkeypatch.chdir(tmp_path)
    _install_hosts(monkeypatch, {})
    with pytest.raises(CLIError) as exc_info:
        discover_all(None)
    assert "No running AgentOS" in exc_info.value.message
    assert "http://prodhost:9000" in exc_info.value.message


def test_discover_invalid_env_file_url_raises_in_discover_all(monkeypatch, tmp_path):
    (tmp_path / ".env.production").write_text("AGENTOS_URL=http://host:${PORT}\n")
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("AGENTOS_URL", raising=False)
    with pytest.raises(CLIError) as exc_info:
        discover_all(None)
    assert "Invalid AgentOS URL" in exc_info.value.message


def test_discover_populates_name_and_os_id(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    fake = FakeAgentOS(name="Customer Support", os_id="os-123")
    install_fake(monkeypatch, fake)
    info = discover("http://localhost:7777")
    assert info.name == "Customer Support"
    assert info.os_id == "os-123"


def test_discover_name_absent_on_older_servers(monkeypatch, tmp_path, fake_os):
    """agno <= 2.7 serves no name/os_id on /info: the fields stay None (callers fall back)."""
    info = discover("http://localhost:7777")
    assert info.name is None
    assert info.os_id is None


def test_discover_all_dedupes_loopback_aliases(monkeypatch, tmp_path):
    """AGENTOS_URL=http://127.0.0.1:7777 (the spelling uvicorn logs) and the
    localhost:7777 default are the same server: one candidate, not a two-entry menu."""
    (tmp_path / ".env").write_text("AGENTOS_URL=http://127.0.0.1:7777\n")
    monkeypatch.chdir(tmp_path)
    fake = FakeAgentOS()
    _install_hosts(monkeypatch, {"127.0.0.1:7777": fake, "localhost:7777": fake})
    found = discover_all(None)
    assert [i.base_url for i in found] == ["http://127.0.0.1:7777"]
    assert found[0].url_source == "env-file"


def test_discover_parses_mcp_oauth(monkeypatch, tmp_path):
    """The MCP OAuth signal is mcp.oauth alone; auth_mode stays the REST plane."""
    monkeypatch.chdir(tmp_path)
    fake = FakeAgentOS(auth_mode="none", oauth=True)
    install_fake(monkeypatch, fake)
    info = discover("http://localhost:7777")
    assert info.auth_mode == "none"
    assert info.oauth_enabled is True
    assert info.oauth is not None
    assert info.oauth.authorization_servers == ["http://localhost:7777/mcp/auth"]
    assert info.oauth.resource == "http://localhost:7777/mcp"
    assert info.public_dict()["mcp"]["oauth"]["resource"] == "http://localhost:7777/mcp"


def test_discover_oauth_absent_on_older_servers(monkeypatch, tmp_path, fake_os):
    """agno <= 2.7 serves no mcp.oauth object: the field stays None and nothing lights up."""
    info = discover("http://localhost:7777")
    assert info.oauth is None
    assert info.oauth_enabled is False


def test_discover_all_includes_client_config_sources(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    _install_hosts(monkeypatch, {"localhost:7777": FakeAgentOS(), "prodhost:8443": FakeAgentOS(name="Prod OS")})
    found = discover_all(None, extra_sources=[("https://prodhost:8443", "client-config", "Claude Code, Cursor")])
    assert [i.base_url for i in found] == ["http://localhost:7777", "https://prodhost:8443"]
    assert found[1].url_source == "client-config"
    assert found[1].source_note() == " (configured in Claude Code, Cursor)"


def test_discover_all_explicit_url_ignores_client_config_sources(monkeypatch, tmp_path):
    """--url names a deliberate single target; config-derived candidates never widen it."""
    monkeypatch.chdir(tmp_path)
    _install_hosts(monkeypatch, {"flaghost:9000": FakeAgentOS(), "prodhost:8443": FakeAgentOS()})
    found = discover_all("http://flaghost:9000", extra_sources=[("https://prodhost:8443", "client-config", "Cursor")])
    assert [i.base_url for i in found] == ["http://flaghost:9000"]


def test_discover_all_dedupes_client_config_against_defaults(monkeypatch, tmp_path):
    """A config entry for the local default (via a loopback alias) adds no candidate."""
    monkeypatch.chdir(tmp_path)
    _install_hosts(monkeypatch, {"localhost:7777": FakeAgentOS()})
    found = discover_all(None, extra_sources=[("http://127.0.0.1:7777", "client-config", "Cursor")])
    assert len(found) == 1
