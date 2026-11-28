"""A custom HTTP client has to be the flavour the installed Anthropic SDK accepts.

anthropic 1.0.0 moved its HTTP layer from ``httpx`` to ``httpx2`` and now raises
``TypeError`` at client construction when handed an ``httpx.Client``. Agno hands the SDK
both the caller's client and, for Azure, its own shared one -- so the check that used to
read ``isinstance(x, httpx.Client)`` has to follow whatever the SDK is built on, and a
client of the wrong flavour has to be dropped rather than passed through.
"""

import httpx
import pytest
from anthropic import DefaultAsyncHttpxClient, DefaultHttpxClient

from agno.models.anthropic.claude import Claude
from agno.utils.models.claude import resolve_http_client, sdk_http_client_type


def test_the_expected_type_is_the_one_the_sdk_is_built_on():
    assert issubclass(DefaultHttpxClient, sdk_http_client_type())
    assert issubclass(DefaultAsyncHttpxClient, sdk_http_client_type(is_async=True))


@pytest.mark.parametrize("is_async", [False, True], ids=["sync", "async"])
def test_a_client_of_the_wrong_flavour_is_dropped(is_async):
    class NotAnHttpClient:
        pass

    assert resolve_http_client(NotAnHttpClient(), is_async=is_async) is None


@pytest.mark.parametrize("is_async", [False, True], ids=["sync", "async"])
def test_a_client_of_the_right_flavour_is_passed_through(is_async):
    client = sdk_http_client_type(is_async)()
    try:
        assert resolve_http_client(client, is_async=is_async) is client
    finally:
        if not is_async:
            client.close()


def test_a_fallback_is_only_used_when_the_sdk_would_take_it():
    expected = sdk_http_client_type()
    usable = expected()
    try:
        assert resolve_http_client(None, fallback=usable) is usable
        assert resolve_http_client(None, fallback=object()) is None
    finally:
        usable.close()


def _azure_claude(**kwargs):
    """Imported here, not at module scope: importing agno.models.azure registers the
    installed `azure` namespace package, and tests/unit/models/azure/ is itself
    collected as `azure.<module>`, which that import would then shadow."""
    from agno.models.azure.claude import Claude as AzureClaude

    return AzureClaude(api_key="test", base_url="https://example.invalid", **kwargs)


MODELS = {
    "anthropic": lambda **kwargs: Claude(api_key="test", **kwargs),
    "azure": _azure_claude,
}


@pytest.mark.parametrize("provider", list(MODELS))
def test_the_client_builds_whatever_flavour_the_caller_brings(provider):
    """An httpx client from the wrong package must not reach the SDK constructor."""
    http_client = httpx.Client()
    try:
        assert MODELS[provider](http_client=http_client).get_client() is not None
    finally:
        http_client.close()


def test_azure_builds_a_client_with_no_custom_http_client():
    """Azure defaults to agno's shared httpx client, which an httpx2 SDK will not take."""
    assert _azure_claude().get_client() is not None
