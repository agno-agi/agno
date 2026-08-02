from unittest.mock import patch

import pytest

from agno.os.interfaces.teams import security as teams_security
from agno.os.interfaces.teams.security import validate_bot_framework_jwt

APP_ID = "test-app-id"


@pytest.fixture(autouse=True)
def _clear_jwks_cache():
    teams_security._jwks_cache["keys"] = None
    teams_security._jwks_cache["fetched_at"] = 0.0
    teams_security._jwks_cache["jwks_uri"] = None
    yield
    teams_security._jwks_cache["keys"] = None
    teams_security._jwks_cache["fetched_at"] = 0.0
    teams_security._jwks_cache["jwks_uri"] = None


# === Header shape rejection (fast-path, no JWKS fetch) ===


def test_missing_auth_header_returns_false():
    assert validate_bot_framework_jwt(None, APP_ID) is False


def test_empty_auth_header_returns_false():
    assert validate_bot_framework_jwt("", APP_ID) is False


def test_missing_bearer_prefix_returns_false():
    assert validate_bot_framework_jwt("Basic abc", APP_ID) is False


def test_bearer_prefix_is_case_insensitive():
    with patch("agno.os.interfaces.teams.security._get_jwks", return_value=[]):
        assert validate_bot_framework_jwt("bearer not-a-real-jwt", APP_ID) is False


def test_malformed_jwt_returns_false():
    with patch("agno.os.interfaces.teams.security._get_jwks", return_value=[]):
        assert validate_bot_framework_jwt("Bearer garbage.not.jwt", APP_ID) is False


# === Skip flag for local dev ===


def test_skip_flag_bypasses_validation():
    with patch.dict("os.environ", {"MICROSOFT_APP_SKIP_JWT_VALIDATION": "true"}, clear=True):
        assert validate_bot_framework_jwt(None, APP_ID) is True
        assert validate_bot_framework_jwt("Bearer garbage", APP_ID) is True
        assert validate_bot_framework_jwt("", APP_ID) is True


def test_skip_flag_case_insensitive():
    with patch.dict("os.environ", {"MICROSOFT_APP_SKIP_JWT_VALIDATION": "True"}, clear=True):
        assert validate_bot_framework_jwt(None, APP_ID) is True


def test_skip_flag_false_still_validates():
    with patch.dict("os.environ", {"MICROSOFT_APP_SKIP_JWT_VALIDATION": "false"}, clear=True):
        assert validate_bot_framework_jwt(None, APP_ID) is False


# === Signature verification path (mocked jwt.decode) ===


def test_valid_signature_returns_true():
    fake_key = {"kty": "RSA", "kid": "test-kid", "n": "AA", "e": "AQAB"}

    with (
        patch("agno.os.interfaces.teams.security._get_jwks", return_value=[fake_key]),
        patch("jwt.get_unverified_header", return_value={"kid": "test-kid", "alg": "RS256"}),
        patch("jwt.algorithms.RSAAlgorithm.from_jwk", return_value="fake-public-key"),
        patch("jwt.decode", return_value={"iss": "https://api.botframework.com", "aud": APP_ID, "exp": 9999999999}),
    ):
        assert validate_bot_framework_jwt("Bearer x.y.z", APP_ID) is True


def test_signature_verification_failure_returns_false():
    import jwt

    fake_key = {"kty": "RSA", "kid": "test-kid", "n": "AA", "e": "AQAB"}

    with (
        patch("agno.os.interfaces.teams.security._get_jwks", return_value=[fake_key]),
        patch("jwt.get_unverified_header", return_value={"kid": "test-kid"}),
        patch("jwt.algorithms.RSAAlgorithm.from_jwk", return_value="fake-public-key"),
        patch("jwt.decode", side_effect=jwt.InvalidSignatureError("bad sig")),
    ):
        assert validate_bot_framework_jwt("Bearer x.y.z", APP_ID) is False


def test_unknown_kid_forces_refresh_then_fails():
    """When the kid isn't in cached JWKS, we refresh once. If still missing, reject."""
    call_count = {"n": 0}

    def fake_get_jwks():
        call_count["n"] += 1
        return []  # empty both times

    with (
        patch("agno.os.interfaces.teams.security._get_jwks", side_effect=fake_get_jwks),
        patch("jwt.get_unverified_header", return_value={"kid": "unknown-kid"}),
    ):
        assert validate_bot_framework_jwt("Bearer x.y.z", APP_ID) is False
        assert call_count["n"] == 2


def test_missing_kid_in_header_returns_false():
    with patch("jwt.get_unverified_header", return_value={"alg": "RS256"}):
        assert validate_bot_framework_jwt("Bearer x.y.z", APP_ID) is False


def test_wrong_audience_returns_false():
    import jwt

    fake_key = {"kty": "RSA", "kid": "test-kid", "n": "AA", "e": "AQAB"}

    with (
        patch("agno.os.interfaces.teams.security._get_jwks", return_value=[fake_key]),
        patch("jwt.get_unverified_header", return_value={"kid": "test-kid"}),
        patch("jwt.algorithms.RSAAlgorithm.from_jwk", return_value="fake-public-key"),
        patch("jwt.decode", side_effect=jwt.InvalidAudienceError("wrong aud")),
    ):
        assert validate_bot_framework_jwt("Bearer x.y.z", APP_ID) is False


def test_wrong_issuer_returns_false():
    import jwt

    fake_key = {"kty": "RSA", "kid": "test-kid", "n": "AA", "e": "AQAB"}

    with (
        patch("agno.os.interfaces.teams.security._get_jwks", return_value=[fake_key]),
        patch("jwt.get_unverified_header", return_value={"kid": "test-kid"}),
        patch("jwt.algorithms.RSAAlgorithm.from_jwk", return_value="fake-public-key"),
        patch("jwt.decode", side_effect=jwt.InvalidIssuerError("wrong iss")),
    ):
        assert validate_bot_framework_jwt("Bearer x.y.z", APP_ID) is False


def test_expired_token_returns_false():
    import jwt

    fake_key = {"kty": "RSA", "kid": "test-kid", "n": "AA", "e": "AQAB"}

    with (
        patch("agno.os.interfaces.teams.security._get_jwks", return_value=[fake_key]),
        patch("jwt.get_unverified_header", return_value={"kid": "test-kid"}),
        patch("jwt.algorithms.RSAAlgorithm.from_jwk", return_value="fake-public-key"),
        patch("jwt.decode", side_effect=jwt.ExpiredSignatureError("expired")),
    ):
        assert validate_bot_framework_jwt("Bearer x.y.z", APP_ID) is False
