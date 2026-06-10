"""Unit tests for loading JWKS from a URL (jwks_url / JWT_JWKS_URL)."""

import json
from unittest.mock import MagicMock, patch

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt.algorithms import RSAAlgorithm

from agno.os.middleware import JWTMiddleware
from agno.os.middleware.jwt import JWTValidator


def _rsa_key_and_jwks(kid="key-1"):
    """Generate an RSA key and a single-key JWKS exposing its public key."""
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_jwk = json.loads(RSAAlgorithm.to_jwk(key.public_key()))
    public_jwk.update({"kid": kid, "alg": "RS256", "use": "sig"})
    return key, {"keys": [public_jwk]}


def _mock_response(jwks):
    resp = MagicMock()
    resp.json.return_value = jwks
    resp.raise_for_status.return_value = None
    return resp


def test_jwks_url_loads_keys():
    """jwks_url fetches the endpoint and parses its keys."""
    _, jwks = _rsa_key_and_jwks()
    with patch("httpx.get", return_value=_mock_response(jwks)) as mock_get:
        validator = JWTValidator(jwks_url="https://idp.example/jwks", algorithm="RS256")

    mock_get.assert_called_once()
    assert "key-1" in validator.jwks_keys


def test_jwks_url_validates_token():
    """A token signed by the key behind jwks_url validates."""
    key, jwks = _rsa_key_and_jwks()
    with patch("httpx.get", return_value=_mock_response(jwks)):
        validator = JWTValidator(jwks_url="https://idp.example/jwks", algorithm="RS256")

    token = jwt.encode({"sub": "u", "scopes": ["agents:read"]}, key, algorithm="RS256", headers={"kid": "key-1"})
    claims = validator.validate_token(token)
    assert claims is not None
    assert claims["sub"] == "u"


def test_jwt_jwks_url_env_var(monkeypatch):
    """JWT_JWKS_URL env var is used when no param is given."""
    _, jwks = _rsa_key_and_jwks()
    monkeypatch.setenv("JWT_JWKS_URL", "https://idp.example/jwks")
    with patch("httpx.get", return_value=_mock_response(jwks)) as mock_get:
        validator = JWTValidator(algorithm="RS256")

    mock_get.assert_called_once()
    assert "key-1" in validator.jwks_keys


def test_jwks_url_fetch_failure_raises():
    """A failed fetch raises a clear ValueError."""
    import httpx

    with patch("httpx.get", side_effect=httpx.ConnectError("boom")):
        with pytest.raises(ValueError, match="Failed to fetch JWKS"):
            JWTValidator(jwks_url="https://idp.example/jwks", algorithm="RS256")


def test_middleware_passes_jwks_url():
    """JWTMiddleware threads jwks_url through to its validator."""
    _, jwks = _rsa_key_and_jwks()
    with patch("httpx.get", return_value=_mock_response(jwks)):
        middleware = JWTMiddleware(app=None, jwks_url="https://idp.example/jwks", algorithm="RS256")

    assert "key-1" in middleware.validator.jwks_keys


def test_jwks_url_non_object_json_raises():
    """A valid-JSON-but-wrong-shape response (a list) raises a clear ValueError, not AttributeError."""
    resp = MagicMock()
    resp.json.return_value = ["not", "a", "dict"]
    resp.raise_for_status.return_value = None
    with patch("httpx.get", return_value=resp):
        with pytest.raises(ValueError, match="JWKS must be a JSON object"):
            JWTValidator(jwks_url="https://idp.example/jwks", algorithm="RS256")


def test_jwt_jwks_url_counts_as_configured(monkeypatch):
    """JWT_JWKS_URL marks JWT as configured, like JWT_VERIFICATION_KEY / JWT_JWKS_FILE."""
    from agno.os.auth import _is_jwt_configured

    monkeypatch.delenv("JWT_VERIFICATION_KEY", raising=False)
    monkeypatch.delenv("JWT_JWKS_FILE", raising=False)
    monkeypatch.delenv("JWT_JWKS_URL", raising=False)
    assert _is_jwt_configured() is False

    monkeypatch.setenv("JWT_JWKS_URL", "https://idp.example/jwks")
    assert _is_jwt_configured() is True
