"""Credential-handling guardrails: plaintext-HTTP refusal, name validation."""

import pytest

from agnoctl.commands._common import _is_loopback_host, require_secure_url, validate_project_name
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
