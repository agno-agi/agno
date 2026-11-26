"""JWT_VERIFICATION_KEY holds several comma-separated keys for an asymmetric algorithm."""

import time

import jwt
import pytest
from fastapi.testclient import TestClient

from agno.agent import Agent
from agno.os import AgentOS
from agno.os.config import AuthorizationConfig
from agno.os.middleware.jwt import JWTValidator, verification_keys_from_env
from agno.utils.cryptography import generate_rsa_keys

OS_ID = "several-keys-os"


@pytest.fixture(scope="module")
def issuers():
    """Three issuers, each with its own RS256 key pair, as (private, public)."""
    return [generate_rsa_keys() for _ in range(3)]


def _token(private_key, algorithm="RS256", **claims):
    payload = {"sub": "reader", "aud": OS_ID, "scopes": ["agents:read"], "exp": int(time.time()) + 600, **claims}
    return jwt.encode(payload, private_key, algorithm=algorithm)


def _bearer(private_key):
    return {"Authorization": f"Bearer {_token(private_key)}"}


def test_tokens_signed_by_two_keys_both_pass_on_one_agentos(monkeypatch, issuers):
    (first_private, first_public), (second_private, second_public), (other_private, _) = issuers
    monkeypatch.setenv("JWT_VERIFICATION_KEY", f"{first_public},{second_public}")
    agent_os = AgentOS(id=OS_ID, agents=[Agent(id="research", name="Research")], authorization=True, telemetry=False)
    client = TestClient(agent_os.get_app())

    assert client.get("/agents", headers=_bearer(first_private)).status_code == 200
    assert client.get("/agents", headers=_bearer(second_private)).status_code == 200
    # A key that is not in the list still verifies nothing
    assert client.get("/agents", headers=_bearer(other_private)).status_code == 401


def test_each_key_in_the_env_verifies(monkeypatch, issuers):
    (first_private, first_public), (second_private, second_public), (other_private, _) = issuers
    monkeypatch.setenv("JWT_VERIFICATION_KEY", f"{first_public},{second_public}")
    validator = JWTValidator(algorithm="RS256")
    assert validator.verification_keys == [first_public.strip(), second_public.strip()]
    assert validator.validate_token(_token(first_private))["sub"] == "reader"
    assert validator.validate_token(_token(second_private))["sub"] == "reader"
    with pytest.raises(jwt.InvalidTokenError):
        validator.validate_token(_token(other_private))


def test_whitespace_around_the_commas_and_empty_entries_are_dropped(monkeypatch, issuers):
    (_, first_public), (second_private, second_public), _ = issuers
    monkeypatch.setenv("JWT_VERIFICATION_KEY", f"\n{first_public} ,\n\n {second_public},\n ,")
    validator = JWTValidator(algorithm="RS256")
    assert validator.verification_keys == [first_public.strip(), second_public.strip()]
    assert validator.validate_token(_token(second_private))["sub"] == "reader"


def test_one_key_in_the_env_works_as_before(monkeypatch, issuers):
    (first_private, first_public), _, _ = issuers
    monkeypatch.setenv("JWT_VERIFICATION_KEY", first_public)
    validator = JWTValidator(algorithm="RS256")
    assert validator.verification_keys == [first_public.strip()]
    assert validator.validate_token(_token(first_private))["sub"] == "reader"


def test_keys_passed_in_code_come_first_and_are_not_repeated(monkeypatch, issuers):
    (_, first_public), (_, second_public), (_, third_public) = issuers
    monkeypatch.setenv("JWT_VERIFICATION_KEY", f"{first_public},{second_public}")
    validator = JWTValidator(verification_keys=[third_public, first_public.strip()], algorithm="RS256")
    assert validator.verification_keys == [third_public, first_public.strip(), second_public.strip()]


def test_a_shared_secret_with_a_comma_stays_one_key(monkeypatch):
    secret = "first-half-of-a-long-shared-secret,second-half-of-a-long-shared-secret"
    monkeypatch.setenv("JWT_VERIFICATION_KEY", secret)
    validator = JWTValidator(algorithm="HS256")
    assert validator.verification_keys == [secret]
    assert validator.validate_token(_token(secret, algorithm="HS256"))["sub"] == "reader"
    # Neither half verifies a token by itself
    for half in secret.split(","):
        with pytest.raises(jwt.InvalidTokenError):
            validator.validate_token(_token(half, algorithm="HS256"))


def test_a_shared_secret_with_a_comma_still_signs_in_on_agentos(monkeypatch):
    secret = "first-half-of-a-long-shared-secret,second-half-of-a-long-shared-secret"
    monkeypatch.setenv("JWT_VERIFICATION_KEY", secret)
    agent_os = AgentOS(
        id=OS_ID,
        agents=[Agent(id="research", name="Research")],
        authorization=True,
        authorization_config=AuthorizationConfig(algorithm="HS256"),
        telemetry=False,
    )
    client = TestClient(agent_os.get_app())
    whole = {"Authorization": f"Bearer {_token(secret, algorithm='HS256')}"}
    half = {"Authorization": f"Bearer {_token(secret.split(',')[0], algorithm='HS256')}"}
    assert client.get("/agents", headers=whole).status_code == 200
    assert client.get("/agents", headers=half).status_code == 401


@pytest.mark.parametrize(
    "algorithm, expected",
    [
        ("RS256", ["one", "two"]),
        ("ES256", ["one", "two"]),
        ("PS256", ["one", "two"]),
        ("EdDSA", ["one", "two"]),
        ("HS256", ["one,two"]),
        ("HS512", ["one,two"]),
        ("hs256", ["one,two"]),
    ],
)
def test_only_asymmetric_algorithms_split_on_commas(monkeypatch, algorithm, expected):
    monkeypatch.setenv("JWT_VERIFICATION_KEY", "one,two")
    assert verification_keys_from_env(algorithm) == expected


def test_no_env_var_means_no_keys(monkeypatch):
    monkeypatch.delenv("JWT_VERIFICATION_KEY", raising=False)
    assert verification_keys_from_env("RS256") == []
    monkeypatch.setenv("JWT_VERIFICATION_KEY", "")
    assert verification_keys_from_env("RS256") == []
