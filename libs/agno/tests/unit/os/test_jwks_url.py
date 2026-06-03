"""Remote JWKS URL support in JWTValidator.

An IdP (WorkOS/Auth0) publishes its public keys at a URL and rotates them. The
validator should fetch them at startup, validate tokens signed by those keys, and
re-fetch when a token arrives with a key id it hasn't seen (rotation) - without a
static key file to snapshot.
"""

import json
from datetime import UTC, datetime, timedelta

import jwt
from jwt.algorithms import RSAAlgorithm

from agno.os.middleware.jwt import JWTValidator
from agno.utils.cryptography import generate_rsa_keys


def _jwks(public_pem: str, kid: str) -> dict:
    jwk = json.loads(RSAAlgorithm.to_jwk(RSAAlgorithm(RSAAlgorithm.SHA256).prepare_key(public_pem)))
    jwk.update({"kid": kid, "use": "sig", "alg": "RS256"})
    return {"keys": [jwk]}


def _token(private_pem: str, kid: str) -> str:
    return jwt.encode(
        {"sub": "alice", "exp": datetime.now(UTC) + timedelta(hours=1)},
        private_pem, algorithm="RS256", headers={"kid": kid},
    )


class _FakeResp:
    def __init__(self, data):
        self._data = data

    def raise_for_status(self):
        pass

    def json(self):
        return self._data


def test_jwks_url_fetched_at_startup_and_validates(monkeypatch):
    private, public = generate_rsa_keys()
    monkeypatch.setattr("httpx.get", lambda url, timeout=5.0: _FakeResp(_jwks(public, "k1")))

    validator = JWTValidator(jwks_url="https://idp.example/jwks", algorithm="RS256")
    payload = validator.validate_token(_token(private, "k1"))
    assert payload["sub"] == "alice"


def test_jwks_url_refetches_on_key_rotation(monkeypatch):
    priv1, pub1 = generate_rsa_keys()
    priv2, pub2 = generate_rsa_keys()
    served = {"jwks": _jwks(pub1, "k1")}
    monkeypatch.setattr("httpx.get", lambda url, timeout=5.0: _FakeResp(served["jwks"]))

    validator = JWTValidator(jwks_url="https://idp.example/jwks", algorithm="RS256")
    validator._jwks_min_refresh_seconds = 0  # allow an immediate refetch for the test

    # IdP rotates to a brand new key the validator has never seen.
    served["jwks"] = _jwks(pub2, "k2")
    payload = validator.validate_token(_token(priv2, "k2"))
    assert payload["sub"] == "alice"


def test_jwks_url_startup_failure_is_not_fatal(monkeypatch):
    def boom(url, timeout=5.0):
        raise RuntimeError("idp unreachable")

    monkeypatch.setattr("httpx.get", boom)
    # Construction must not raise even if the IdP is down at boot.
    validator = JWTValidator(jwks_url="https://idp.example/jwks", algorithm="RS256")
    assert validator.jwks_url == "https://idp.example/jwks"


def test_unknown_kid_refetch_is_rate_limited(monkeypatch):
    priv1, pub1 = generate_rsa_keys()
    priv2, pub2 = generate_rsa_keys()
    served = {"jwks": _jwks(pub1, "k1")}
    calls = {"n": 0}

    def fake_get(url, timeout=5.0):
        calls["n"] += 1
        return _FakeResp(served["jwks"])

    monkeypatch.setattr("httpx.get", fake_get)
    validator = JWTValidator(jwks_url="https://idp.example/jwks", algorithm="RS256")
    assert calls["n"] == 1  # startup fetch

    # A token with an unknown kid arrives but the refresh window hasn't elapsed,
    # so we should NOT hammer the IdP; validation fails without a second fetch.
    served["jwks"] = _jwks(pub2, "k2")
    try:
        validator.validate_token(_token(priv2, "k2"))
    except jwt.InvalidTokenError:
        pass
    assert calls["n"] == 1  # still just the startup fetch (rate-limited)
