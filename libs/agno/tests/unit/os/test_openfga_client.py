"""OpenFGAClient — the adapter that puts a real OpenFGA behind FGAAuthorizationProvider.

Everything else in the FGA tier is exercised against an in-memory stand-in, which
means the one piece that talks to a real engine -- the translation from agno's
(user, relation, object) triple into the SDK's request objects, and back from its
response -- had no coverage at all. A mistake there is invisible until someone points
the provider at a live OpenFGA.

``openfga_sdk`` is an optional extra (``agno[fga]``) and is not installed in the dev
environment, so these install a stand-in module and assert on what the adapter asks
it for. That covers the mapping and the response handling; it deliberately does NOT
claim to verify wire compatibility with a real server.
"""

import sys
from types import ModuleType, SimpleNamespace

import pytest


@pytest.fixture
def fake_sdk(monkeypatch):
    """Install a minimal stand-in for openfga_sdk and hand back the calls it records."""
    recorded = SimpleNamespace(config=None, checks=[], list_objects=[], response_allowed=True, response_objects=[])

    class ClientConfiguration:
        def __init__(self, **kwargs):
            recorded.config = kwargs

    class ClientCheckRequest:
        def __init__(self, user, relation, object):  # noqa: A002 - the SDK's own kwarg name
            self.user, self.relation, self.object = user, relation, object

    class ClientListObjectsRequest:
        def __init__(self, user, relation, type):  # noqa: A002 - the SDK's own kwarg name
            self.user, self.relation, self.type = user, relation, type

    class OpenFgaClient:
        def __init__(self, configuration):
            self.configuration = configuration

        def check(self, request):
            recorded.checks.append((request.user, request.relation, request.object))
            return SimpleNamespace(allowed=recorded.response_allowed)

        def list_objects(self, request):
            recorded.list_objects.append((request.user, request.relation, request.type))
            return SimpleNamespace(objects=recorded.response_objects)

    root = ModuleType("openfga_sdk")
    root.ClientConfiguration = ClientConfiguration  # type: ignore[attr-defined]
    root.ClientCheckRequest = ClientCheckRequest  # type: ignore[attr-defined]
    root.ClientListObjectsRequest = ClientListObjectsRequest  # type: ignore[attr-defined]
    sync = ModuleType("openfga_sdk.sync")
    sync.OpenFgaClient = OpenFgaClient  # type: ignore[attr-defined]

    monkeypatch.setitem(sys.modules, "openfga_sdk", root)
    monkeypatch.setitem(sys.modules, "openfga_sdk.sync", sync)
    return recorded


def test_constructor_passes_connection_settings_through(fake_sdk):
    from agno.os.authz.fga import OpenFGAClient

    OpenFGAClient(api_url="http://localhost:8080", store_id="store-1", authorization_model_id="model-1")

    assert fake_sdk.config == {
        "api_url": "http://localhost:8080",
        "store_id": "store-1",
        "authorization_model_id": "model-1",
        "credentials": None,
    }


def test_check_maps_the_triple_and_reads_allowed(fake_sdk):
    from agno.os.authz.fga import OpenFGAClient

    client = OpenFGAClient(api_url="http://x", store_id="s")

    fake_sdk.response_allowed = True
    assert client.check("user:alice", "run", "agents:research-agent") is True
    fake_sdk.response_allowed = False
    assert client.check("user:bob", "run", "agents:research-agent") is False

    assert fake_sdk.checks == [
        ("user:alice", "run", "agents:research-agent"),
        ("user:bob", "run", "agents:research-agent"),
    ]


def test_list_objects_maps_the_query_and_returns_the_objects(fake_sdk):
    from agno.os.authz.fga import OpenFGAClient

    client = OpenFGAClient(api_url="http://x", store_id="s")
    fake_sdk.response_objects = ["agents:a1", "agents:a2"]

    assert client.list_objects("user:alice", "read", "agents") == ["agents:a1", "agents:a2"]
    assert fake_sdk.list_objects == [("user:alice", "read", "agents")]


def test_missing_or_empty_response_fields_are_not_an_allow(fake_sdk):
    """A response without the field must read as deny / empty, never as access."""
    from agno.os.authz.fga import OpenFGAClient

    client = OpenFGAClient(api_url="http://x", store_id="s")

    fake_sdk.response_allowed = None
    assert client.check("user:alice", "run", "agents:a1") is False

    fake_sdk.response_objects = None
    assert client.list_objects("user:alice", "read", "agents") == []


def test_it_satisfies_the_port_the_provider_consumes(fake_sdk):
    """The adapter must be usable wherever the in-memory stand-in is -- that is the
    whole promise of the FGAClient port, and what the cookbook tells users to rely on."""
    from agno.os.authz.fga import FGAAuthorizationProvider, OpenFGAClient
    from agno.os.authz.provider import AuthorizationContext

    provider = FGAAuthorizationProvider(OpenFGAClient(api_url="http://x", store_id="s"))

    fake_sdk.response_allowed = True
    ctx = AuthorizationContext(principal_id="alice", resource_type="agents", resource_id="a1", action="run")
    assert provider.check(ctx) is True
    # the provider's user_type prefix and relation mapping reach the SDK intact
    assert fake_sdk.checks[-1] == ("user:alice", "run", "agents:a1")


def test_helpful_error_when_the_extra_is_not_installed(monkeypatch):
    """Without agno[fga] the import must say so, not raise a bare ImportError."""
    monkeypatch.setitem(sys.modules, "openfga_sdk", None)
    from agno.os.authz.fga import OpenFGAClient

    with pytest.raises(ImportError, match=r"agno\[fga\]"):
        OpenFGAClient(api_url="http://x", store_id="s")
