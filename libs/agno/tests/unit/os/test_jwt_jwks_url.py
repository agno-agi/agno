"""Unit tests for verifying JWTs against a remote JWKS URL (jwks_url / JWT_JWKS_URL)."""

import json
from unittest.mock import MagicMock, patch

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
from jwt.algorithms import RSAAlgorithm

from agno.os.middleware import jwt as jwt_module
from agno.os.middleware.jwt import (
    JWKS_URL_CACHE_SECONDS,
    JWKS_URL_MIN_REFETCH_SECONDS,
    JWTMiddleware,
    JWTValidator,
    avalidate_with,
    jwt_kwargs_have_key_source,
)

JWKS_URL = "https://idp.example/jwks.json"


def _rsa_key(kid):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_jwk = json.loads(RSAAlgorithm.to_jwk(key.public_key()))
    public_jwk.update({"kid": kid, "alg": "RS256", "use": "sig"})
    return key, public_jwk


def _token(key, kid, **claims):
    payload = {"sub": "user-1", "scopes": ["agent_os:admin"], **claims}
    return jwt.encode(payload, key, algorithm="RS256", headers={"kid": kid})


def _response(*public_jwks):
    resp = MagicMock()
    resp.json.return_value = {"keys": list(public_jwks)}
    resp.raise_for_status.return_value = None
    return resp


class _Clock:
    """Stands in for time.monotonic inside the jwt module so cache ages can be stepped."""

    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


@pytest.fixture
def clock(monkeypatch):
    c = _Clock()
    monkeypatch.setattr(jwt_module.time, "monotonic", c)
    return c


@pytest.fixture(autouse=True)
def _no_jwt_env(monkeypatch):
    for name in ("JWT_VERIFICATION_KEY", "JWT_JWKS_FILE", "JWT_JWKS_URL"):
        monkeypatch.delenv(name, raising=False)


def test_construction_does_not_fetch():
    """An unreachable issuer must not stop the app from booting, so nothing is fetched up front."""
    with patch("httpx.get") as get:
        validator = JWTValidator(jwks_url=JWKS_URL)
    get.assert_not_called()
    assert validator.jwks_url == JWKS_URL


def test_first_token_fetches_and_validates(clock):
    key, public = _rsa_key("k1")
    validator = JWTValidator(jwks_url=JWKS_URL)
    with patch("httpx.get", return_value=_response(public)) as get:
        claims = validator.validate_token(_token(key, "k1"))
    get.assert_called_once()
    assert claims["sub"] == "user-1"


def test_cached_keys_are_reused(clock):
    key, public = _rsa_key("k1")
    validator = JWTValidator(jwks_url=JWKS_URL)
    with patch("httpx.get", return_value=_response(public)) as get:
        validator.validate_token(_token(key, "k1"))
        clock.now += JWKS_URL_CACHE_SECONDS - 1
        validator.validate_token(_token(key, "k1"))
    assert get.call_count == 1


def test_cache_expiry_refetches(clock):
    key, public = _rsa_key("k1")
    validator = JWTValidator(jwks_url=JWKS_URL)
    with patch("httpx.get", return_value=_response(public)) as get:
        validator.validate_token(_token(key, "k1"))
        clock.now += JWKS_URL_CACHE_SECONDS
        validator.validate_token(_token(key, "k1"))
    assert get.call_count == 2


def test_rotated_key_is_picked_up_on_unknown_kid(clock):
    """The issuer publishes a new key: a token signed with it triggers one refetch and validates."""
    old_key, old_public = _rsa_key("old")
    new_key, new_public = _rsa_key("new")
    validator = JWTValidator(jwks_url=JWKS_URL)
    with patch("httpx.get", return_value=_response(old_public)):
        validator.validate_token(_token(old_key, "old"))

    clock.now += JWKS_URL_MIN_REFETCH_SECONDS
    with patch("httpx.get", return_value=_response(old_public, new_public)) as get:
        claims = validator.validate_token(_token(new_key, "new"))
    get.assert_called_once()
    assert claims["sub"] == "user-1"


def test_unknown_kids_are_throttled(clock):
    """Tokens with random kids cannot turn every request into an outbound fetch."""
    key, public = _rsa_key("k1")
    validator = JWTValidator(jwks_url=JWKS_URL)
    with patch("httpx.get", return_value=_response(public)) as get:
        validator.validate_token(_token(key, "k1"))
        for i in range(20):
            with pytest.raises(jwt.InvalidTokenError):
                validator.validate_token(_token(key, f"random-{i}"))
    assert get.call_count == 1


def test_failed_refetch_keeps_known_keys(clock):
    """A short issuer outage after expiry does not reject tokens signed by a key already known."""
    key, public = _rsa_key("k1")
    validator = JWTValidator(jwks_url=JWKS_URL)
    with patch("httpx.get", return_value=_response(public)):
        validator.validate_token(_token(key, "k1"))

    clock.now += JWKS_URL_CACHE_SECONDS
    with patch("httpx.get", side_effect=httpx.ConnectError("down")):
        claims = validator.validate_token(_token(key, "k1"))
    assert claims["sub"] == "user-1"


def test_unreachable_issuer_rejects_without_crashing(clock):
    key, _ = _rsa_key("k1")
    validator = JWTValidator(jwks_url=JWKS_URL)
    with patch("httpx.get", side_effect=httpx.ConnectError("down")) as get:
        with pytest.raises(jwt.InvalidTokenError):
            validator.validate_token(_token(key, "k1"))
        # The retry waits for the minimum gap, so an outage is not hammered.
        with pytest.raises(jwt.InvalidTokenError):
            validator.validate_token(_token(key, "k1"))
    assert get.call_count == 1


def test_non_object_jwks_is_rejected(clock):
    key, _ = _rsa_key("k1")
    resp = MagicMock()
    resp.json.return_value = ["not", "a", "jwks"]
    resp.raise_for_status.return_value = None
    validator = JWTValidator(jwks_url=JWKS_URL)
    with patch("httpx.get", return_value=resp):
        with pytest.raises(jwt.InvalidTokenError):
            validator.validate_token(_token(key, "k1"))


def test_jwks_file_parser_rejects_non_object():
    with pytest.raises(ValueError, match="JWKS must be a JSON object"):
        JWTValidator._jwks_keys_from_data(["not", "a", "jwks"])


async def test_async_validation_fetches(clock):
    key, public = _rsa_key("k1")
    validator = JWTValidator(jwks_url=JWKS_URL)
    with patch("httpx.get", return_value=_response(public)) as get:
        claims = await validator.avalidate_token(_token(key, "k1"))
    get.assert_called_once()
    assert claims["sub"] == "user-1"


async def test_avalidate_with_supports_sync_only_validators():
    """Custom validators written before avalidate_token existed keep working."""

    class _SyncOnly:
        def validate_token(self, token, expected_audience=None):
            return {"sub": token}

    assert (await avalidate_with(_SyncOnly(), "abc"))["sub"] == "abc"


def test_env_var_configures_url(monkeypatch):
    from agno.os.auth import is_jwt_env_configured

    assert is_jwt_env_configured() is False
    monkeypatch.setenv("JWT_JWKS_URL", JWKS_URL)
    assert is_jwt_env_configured() is True
    assert JWTValidator().jwks_url == JWKS_URL


def test_url_counts_as_a_key_source():
    assert jwt_kwargs_have_key_source({"jwks_url": JWKS_URL}) is True
    middleware = JWTMiddleware(app=None, jwks_url=JWKS_URL, authorization=True)
    assert middleware.validator is not None and middleware.validator.jwks_url == JWKS_URL


def test_jwks_url_reaches_middleware_kwargs():
    """jwks_url lives on Authorization (AuthorizationConfig is frozen), so the builder takes it explicitly."""
    from agno.os.authz import Authorization
    from agno.os.middleware.jwt import build_jwt_middleware_kwargs

    authz = Authorization(jwks_url=JWKS_URL)
    assert authz.jwks_url == JWKS_URL
    assert build_jwt_middleware_kwargs(None, authorization=True, jwks_url=authz.jwks_url)["jwks_url"] == JWKS_URL


def test_agent_os_verifies_rest_requests_against_the_url(clock):
    """End to end: AgentOS(authorization=Authorization(jwks_url=...)) accepts a token signed by
    a published key and rejects one signed by an unpublished key."""
    from agno.agent import Agent
    from agno.os import AgentOS
    from agno.os.authz import Authorization

    key, public = _rsa_key("k1")
    rogue_key, _ = _rsa_key("rogue")
    agent_os = AgentOS(agents=[Agent(id="a", name="A")], authorization=Authorization(jwks_url=JWKS_URL))
    client = TestClient(agent_os.get_app())

    with patch("httpx.get", return_value=_response(public)):
        ok = client.get("/agents", headers={"Authorization": f"Bearer {_token(key, 'k1')}"})
        bad = client.get("/agents", headers={"Authorization": f"Bearer {_token(rogue_key, 'k1')}"})
        missing = client.get("/agents")

    assert ok.status_code == 200
    assert bad.status_code == 401
    assert missing.status_code == 401
