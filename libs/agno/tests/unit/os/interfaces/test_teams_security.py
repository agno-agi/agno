from unittest.mock import AsyncMock, patch

import pytest

from agno.os.interfaces.teams import security as teams_security
from agno.os.interfaces.teams.security import validate_bot_framework_jwt

APP_ID = "test-app-id"


def _reset_jwks_state():
    teams_security._jwks_cache["keys"] = None
    teams_security._jwks_cache["fetched_at"] = 0.0
    teams_security._jwks_cache["fetched_monotonic"] = 0.0
    teams_security._jwks_cache["jwks_uri"] = None
    # The async lock is bound to the loop that created it; a leaked one would
    # be reused by the next test's loop.
    teams_security._async_jwks_lock = None


@pytest.fixture(autouse=True)
def _clear_jwks_cache():
    _reset_jwks_state()
    yield
    _reset_jwks_state()


# === Header shape rejection (fast-path, no JWKS fetch) ===


@pytest.mark.asyncio
async def test_missing_auth_header_returns_false():
    assert await validate_bot_framework_jwt(None, APP_ID) is False


@pytest.mark.asyncio
async def test_empty_auth_header_returns_false():
    assert await validate_bot_framework_jwt("", APP_ID) is False


@pytest.mark.asyncio
async def test_missing_bearer_prefix_returns_false():
    assert await validate_bot_framework_jwt("Basic abc", APP_ID) is False


@pytest.mark.asyncio
async def test_bearer_prefix_is_case_insensitive():
    with patch("agno.os.interfaces.teams.security._get_jwks", new_callable=AsyncMock, return_value=[]):
        assert await validate_bot_framework_jwt("bearer not-a-real-jwt", APP_ID) is False


@pytest.mark.asyncio
async def test_malformed_jwt_returns_false():
    with patch("agno.os.interfaces.teams.security._get_jwks", new_callable=AsyncMock, return_value=[]):
        assert await validate_bot_framework_jwt("Bearer garbage.not.jwt", APP_ID) is False


# === Skip flag for local dev ===


@pytest.mark.asyncio
async def test_skip_flag_bypasses_validation():
    # No app id configured — the only shape in which the bypass applies.
    with patch.dict("os.environ", {"MICROSOFT_APP_SKIP_JWT_VALIDATION": "true"}, clear=True):
        assert await validate_bot_framework_jwt(None, "") is True
        assert await validate_bot_framework_jwt("Bearer garbage", "") is True
        assert await validate_bot_framework_jwt("", "") is True


@pytest.mark.asyncio
async def test_skip_flag_case_insensitive():
    with patch.dict("os.environ", {"MICROSOFT_APP_SKIP_JWT_VALIDATION": "True"}, clear=True):
        assert await validate_bot_framework_jwt(None, "") is True


@pytest.mark.asyncio
async def test_skip_flag_false_still_validates():
    with patch.dict("os.environ", {"MICROSOFT_APP_SKIP_JWT_VALIDATION": "false"}, clear=True):
        assert await validate_bot_framework_jwt(None, APP_ID) is False


# === JWKS refetch amplification (driven through the webhook) ===


def _client_that_really_validates():
    """A webhook whose JWT check actually runs: credentials set, no dev bypass."""
    from types import SimpleNamespace

    from fastapi import APIRouter, FastAPI
    from fastapi.testclient import TestClient

    from agno.os.interfaces.teams.router import attach_routes

    router = APIRouter()
    env = patch.dict(
        "os.environ",
        {"MICROSOFT_APP_ID": APP_ID, "MICROSOFT_APP_PASSWORD": "secret"},
        clear=True,
    )
    env.start()
    attach_routes(router, agent=SimpleNamespace(id="a-1", name="A", db=None))
    app = FastAPI()
    app.include_router(router)
    return TestClient(app), env


def _token_with_kid(kid: str) -> str:
    import jwt as pyjwt

    # Only the header matters: the kid lookup happens before any signature work.
    return pyjwt.encode({"aud": APP_ID}, "irrelevant", algorithm="HS256", headers={"kid": kid})


def test_repeated_unknown_kid_refetches_jwks_only_once():
    """An unknown kid means "keys may have rotated", so the cache is dropped and
    refetched. get_unverified_header verifies nothing, so any unauthenticated
    caller can trigger that with a made-up kid — and without a floor, every
    request does it again."""
    calls = {"meta": 0, "keys": 0}

    def fake_metadata():
        calls["meta"] += 1
        return {"jwks_uri": "https://example/keys", "issuer": "https://api.botframework.com"}

    def fake_keys(uri):
        calls["keys"] += 1
        return [{"kty": "RSA", "kid": "a-real-kid"}]

    client, env = _client_that_really_validates()
    try:
        with (
            patch("agno.os.interfaces.teams.security._fetch_openid_metadata", side_effect=fake_metadata),
            patch("agno.os.interfaces.teams.security._fetch_jwks", side_effect=fake_keys),
        ):
            headers = {"Authorization": f"Bearer {_token_with_kid('made-up-kid')}"}
            for _ in range(5):
                assert (
                    client.post("/messages", json={"type": "message", "text": "x"}, headers=headers).status_code == 403
                )
    finally:
        env.stop()

    assert calls["meta"] == 1
    assert calls["keys"] == 1


def test_jwks_is_fetched_with_the_async_client_not_the_blocking_one():
    """The webhook handler is a coroutine; a synchronous httpx.Client inside it
    stalls the whole event loop for the duration of the fetch.

    Both clients are patched: the sync one so the assertion can see it, the async
    one so the test never leaves the machine. Patching only httpx.Client would
    let the async path make a real request to Microsoft and still pass.
    """
    client, env = _client_that_really_validates()
    try:
        with patch("httpx.AsyncClient") as async_client, patch("httpx.Client") as blocking_client:
            headers = {"Authorization": f"Bearer {_token_with_kid('made-up-kid')}"}
            client.post("/messages", json={"type": "message", "text": "x"}, headers=headers)
    finally:
        env.stop()

    blocking_client.assert_not_called()
    assert async_client.called, "the JWKS fetch did not go through httpx.AsyncClient"


@pytest.mark.asyncio
async def test_missing_crypto_extra_raises_install_hint_not_a_rejection():
    """pyjwt without the crypto extra is a configuration error, not a bad token.

    `from jwt import PyJWKClient` succeeds without cryptography -- pyjwt guards
    its own crypto imports -- so the existing ImportError guard never fires.
    Verification then fails deep inside and the operator sees 403 "Invalid Bot
    Framework token", sending them to debug their Azure registration instead of
    their install.
    """
    from fastapi import HTTPException

    with patch.dict("os.environ", {"MICROSOFT_APP_ID": APP_ID}, clear=True):
        with patch("jwt.algorithms.has_crypto", False):
            with pytest.raises(HTTPException) as exc:
                await validate_bot_framework_jwt("Bearer x.y.z", APP_ID)

    assert exc.value.status_code == 500
    assert "pyjwt[crypto]" in exc.value.detail


@pytest.mark.asyncio
async def test_skip_flag_is_ignored_when_credentials_are_configured():
    """A configured deployment must not be downgradable by an env var.

    whatsapp/security.py consults its bypass only when WHATSAPP_APP_SECRET is
    absent, and the framework decides enforcement the same way
    (os/app.py: auth_configured = bool(... or jwt_env_configured or security_key)).
    With an app id configured there is a real audience to verify against, so the
    flag must not disable the check.
    """
    with patch.dict(
        "os.environ",
        {"MICROSOFT_APP_ID": APP_ID, "MICROSOFT_APP_SKIP_JWT_VALIDATION": "true"},
        clear=True,
    ):
        assert await validate_bot_framework_jwt(None, APP_ID) is False
        assert await validate_bot_framework_jwt("Bearer garbage", APP_ID) is False


@pytest.mark.asyncio
async def test_skip_flag_bypasses_only_without_credentials():
    """The local-development path stays open: no credentials configured, flag set
    explicitly, nothing to validate against."""
    with patch.dict("os.environ", {"MICROSOFT_APP_SKIP_JWT_VALIDATION": "true"}, clear=True):
        assert await validate_bot_framework_jwt(None, "") is True
        assert await validate_bot_framework_jwt("Bearer garbage", "") is True


# === Signature verification path (mocked jwt.decode) ===


@pytest.mark.asyncio
async def test_valid_signature_returns_true():
    fake_key = {"kty": "RSA", "kid": "test-kid", "n": "AA", "e": "AQAB"}

    with (
        patch("agno.os.interfaces.teams.security._get_jwks", new_callable=AsyncMock, return_value=[fake_key]),
        patch("jwt.get_unverified_header", return_value={"kid": "test-kid", "alg": "RS256"}),
        patch("jwt.algorithms.RSAAlgorithm.from_jwk", return_value="fake-public-key"),
        patch("jwt.decode", return_value={"iss": "https://api.botframework.com", "aud": APP_ID, "exp": 9999999999}),
    ):
        assert await validate_bot_framework_jwt("Bearer x.y.z", APP_ID) is True


@pytest.mark.asyncio
async def test_signature_verification_failure_returns_false():
    import jwt

    fake_key = {"kty": "RSA", "kid": "test-kid", "n": "AA", "e": "AQAB"}

    with (
        patch("agno.os.interfaces.teams.security._get_jwks", new_callable=AsyncMock, return_value=[fake_key]),
        patch("jwt.get_unverified_header", return_value={"kid": "test-kid"}),
        patch("jwt.algorithms.RSAAlgorithm.from_jwk", return_value="fake-public-key"),
        patch("jwt.decode", side_effect=jwt.InvalidSignatureError("bad sig")),
    ):
        assert await validate_bot_framework_jwt("Bearer x.y.z", APP_ID) is False


@pytest.mark.asyncio
async def test_unknown_kid_forces_refresh_then_fails():
    """When the kid isn't in cached JWKS, we refresh once. If still missing, reject."""
    call_count = {"n": 0}

    async def fake_get_jwks():
        call_count["n"] += 1
        return []  # empty both times

    with (
        patch("agno.os.interfaces.teams.security._get_jwks", new_callable=AsyncMock, side_effect=fake_get_jwks),
        patch("jwt.get_unverified_header", return_value={"kid": "unknown-kid"}),
    ):
        assert await validate_bot_framework_jwt("Bearer x.y.z", APP_ID) is False
        assert call_count["n"] == 2


@pytest.mark.asyncio
async def test_missing_kid_in_header_returns_false():
    with patch("jwt.get_unverified_header", return_value={"alg": "RS256"}):
        assert await validate_bot_framework_jwt("Bearer x.y.z", APP_ID) is False


@pytest.mark.asyncio
async def test_wrong_audience_returns_false():
    import jwt

    fake_key = {"kty": "RSA", "kid": "test-kid", "n": "AA", "e": "AQAB"}

    with (
        patch("agno.os.interfaces.teams.security._get_jwks", new_callable=AsyncMock, return_value=[fake_key]),
        patch("jwt.get_unverified_header", return_value={"kid": "test-kid"}),
        patch("jwt.algorithms.RSAAlgorithm.from_jwk", return_value="fake-public-key"),
        patch("jwt.decode", side_effect=jwt.InvalidAudienceError("wrong aud")),
    ):
        assert await validate_bot_framework_jwt("Bearer x.y.z", APP_ID) is False


@pytest.mark.asyncio
async def test_wrong_issuer_returns_false():
    import jwt

    fake_key = {"kty": "RSA", "kid": "test-kid", "n": "AA", "e": "AQAB"}

    with (
        patch("agno.os.interfaces.teams.security._get_jwks", new_callable=AsyncMock, return_value=[fake_key]),
        patch("jwt.get_unverified_header", return_value={"kid": "test-kid"}),
        patch("jwt.algorithms.RSAAlgorithm.from_jwk", return_value="fake-public-key"),
        patch("jwt.decode", side_effect=jwt.InvalidIssuerError("wrong iss")),
    ):
        assert await validate_bot_framework_jwt("Bearer x.y.z", APP_ID) is False


@pytest.mark.asyncio
async def test_expired_token_returns_false():
    import jwt

    fake_key = {"kty": "RSA", "kid": "test-kid", "n": "AA", "e": "AQAB"}

    with (
        patch("agno.os.interfaces.teams.security._get_jwks", new_callable=AsyncMock, return_value=[fake_key]),
        patch("jwt.get_unverified_header", return_value={"kid": "test-kid"}),
        patch("jwt.algorithms.RSAAlgorithm.from_jwk", return_value="fake-public-key"),
        patch("jwt.decode", side_effect=jwt.ExpiredSignatureError("expired")),
    ):
        assert await validate_bot_framework_jwt("Bearer x.y.z", APP_ID) is False
