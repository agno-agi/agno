"""Credential-handling guardrails: plaintext-HTTP refusal, name validation."""

import pytest

from agnoctl.commands._common import (
    _is_loopback_host,
    derive_server_name,
    ensure_env_file_url_trusted,
    require_secure_url,
    validate_project_name,
    validate_server_name,
)
from agnoctl.errors import CLIError

# -- require_secure_url ----------------------------------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        "https://os.example.com/mcp",
        "http://localhost:7777/mcp",
        "http://127.0.0.1:7777",
        "http://127.0.0.5:8000",
        "http://0.0.0.0:7777",
        "http://[::1]:7777",
    ],
)
def test_require_secure_url_allows_https_and_loopback(url):
    require_secure_url(url, allow_http=False)  # must not raise


@pytest.mark.parametrize(
    "url",
    [
        "http://os.example.com/mcp",
        "http://10.0.0.5:7777",
        "http://192.168.1.10:8000/mcp",
    ],
)
def test_require_secure_url_refuses_remote_http(url):
    with pytest.raises(CLIError) as exc:
        require_secure_url(url, allow_http=False, what="the admin credential")
    assert "plaintext HTTP" in exc.value.message
    assert "--allow-http" in (exc.value.hint or "")


def test_require_secure_url_allow_http_override():
    require_secure_url("http://os.example.com/mcp", allow_http=True)  # must not raise


def test_is_loopback_host():
    assert _is_loopback_host("localhost")
    assert _is_loopback_host("127.0.0.1")
    assert _is_loopback_host("::1")
    assert _is_loopback_host("0.0.0.0")
    assert not _is_loopback_host("example.com")
    assert not _is_loopback_host("10.0.0.1")
    assert not _is_loopback_host(None)


# -- ensure_env_file_url_trusted -------------------------------------------------------


def test_env_file_gate_refuses_remote_in_automation():
    """A non-loopback env-file URL is refused in --json/non-TTY runs unless opted in."""
    with pytest.raises(CLIError) as exc:
        ensure_env_file_url_trusted(
            "https://prod.example.com", "env-file", ".env.production", assume_yes=False, json_mode=True
        )
    assert "remote host" in exc.value.message
    assert "--url" in (exc.value.hint or "") and "--yes" in (exc.value.hint or "")


def test_env_file_gate_allows_remote_with_assume_yes():
    ensure_env_file_url_trusted(
        "https://prod.example.com", "env-file", ".env.production", assume_yes=True, json_mode=True
    )  # must not raise


def test_env_file_gate_allows_loopback_env_file():
    ensure_env_file_url_trusted(
        "http://localhost:7777", "env-file", ".env", assume_yes=False, json_mode=True
    )  # must not raise


@pytest.mark.parametrize("source", ["env", "flag", "default"])
def test_env_file_gate_ignores_non_file_sources(source):
    # An exported AGENTOS_URL or an explicit --url is not an ambient file; never gated.
    ensure_env_file_url_trusted(
        "https://prod.example.com", source, None, assume_yes=False, json_mode=True
    )  # must not raise


def test_env_file_gate_prompts_interactively(monkeypatch):
    import agnoctl.commands._common as common

    monkeypatch.setattr(common, "stdin_is_interactive", lambda: True)
    monkeypatch.setattr(common.typer, "confirm", lambda *a, **k: False)
    with pytest.raises(CLIError) as exc:
        ensure_env_file_url_trusted(
            "https://prod.example.com", "env-file", ".env.production", assume_yes=False, json_mode=False
        )
    assert "Aborted" in exc.value.message

    monkeypatch.setattr(common.typer, "confirm", lambda *a, **k: True)
    ensure_env_file_url_trusted(
        "https://prod.example.com", "env-file", ".env.production", assume_yes=False, json_mode=False
    )  # must not raise


def test_env_file_gate_interactive_default_is_trust(monkeypatch):
    """Enter on the interactive prompt trusts the URL (the env-file URL is almost always
    the one the operator's own deploy just wrote); automation above stays fail-closed."""
    import agnoctl.commands._common as common

    monkeypatch.setattr(common, "stdin_is_interactive", lambda: True)
    captured = {}

    def confirm(prompt, default=None):
        captured["default"] = default
        return default  # answer with the default, i.e. a bare Enter

    monkeypatch.setattr(common.typer, "confirm", confirm)
    ensure_env_file_url_trusted(
        "https://prod.example.com", "env-file", ".env.production", assume_yes=False, json_mode=False
    )  # must not raise: Enter accepts
    assert captured["default"] is True


# -- derive_server_name ----------------------------------------------------------------


@pytest.mark.parametrize(
    ("os_name", "expected"),
    [
        ("AgentOS", "agentos"),
        ("Customer Support", "customer-support"),
        ("acme.prod v2", "acme-prod-v2"),
        ("  weird -- name  ", "weird-name"),
        ("!!!", "agentos"),
        ("", "agentos"),
        (None, "agentos"),
    ],
)
def test_derive_server_name(os_name, expected):
    derived = derive_server_name(os_name)
    assert derived == expected
    validate_server_name(derived)  # every derived name must pass the entry-name gate


# -- validate_project_name -------------------------------------------------------------


@pytest.mark.parametrize("name", ["my-app", "agentos_1", "Project", "a"])
def test_validate_project_name_accepts_flat_names(name):
    validate_project_name(name)  # must not raise


@pytest.mark.parametrize(
    "name",
    [
        "",
        "..",
        "../evil",
        "a/b",
        "/abs/path",
        "a\\b",
        "with space",
        "dot.name",
        "~/home",
    ],
)
def test_validate_project_name_rejects_traversal_and_separators(name):
    with pytest.raises(CLIError):
        validate_project_name(name)
