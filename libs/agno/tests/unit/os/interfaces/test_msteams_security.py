import asyncio
import json
import threading
import time
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import APIRouter, FastAPI, HTTPException
from fastapi.testclient import TestClient

from agno.os.interfaces.msteams import security
from agno.os.interfaces.msteams.router import attach_routes

APP_ID = "test-app-id"
SERVICE_URL = "https://svc/"


@pytest.fixture(scope="module")
def signing_key():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture
def claims():
    return {
        "aud": APP_ID,
        "iss": "https://api.botframework.com",
        "exp": int(time.time()) + 600,
        "serviceurl": SERVICE_URL,
    }


def _token(key, claims, kid="test-kid"):
    return jwt.encode(claims, key, algorithm="RS256", headers={"kid": kid})


@pytest.fixture
def jwks(signing_key, monkeypatch):
    key = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(signing_key.public_key()))
    key.update(kid="test-kid", use="sig", endorsements=["msteams"])
    monkeypatch.setattr(security, "_jwk_client", security._BotFrameworkJWKClient(security._OPENID_METADATA_URL))
    monkeypatch.setattr(
        security, "_fetch_openid_metadata", MagicMock(return_value={"jwks_uri": "https://example.com/keys"})
    )

    # Stub the network fetch, not token decoding or the subclass's endorsement capture.
    def fetch_data(client):
        client._last_successful_fetch = time.monotonic()
        return {"keys": [key]}

    with patch("jwt.PyJWKClient.fetch_data", autospec=True, side_effect=fetch_data) as fetch:
        yield key, fetch


@pytest.mark.asyncio
@pytest.mark.parametrize("header", [None, "", "Basic abc", "Bearer malformed", "Bearer x.y.z"])
async def test_invalid_header_rejected(header):
    assert await security.validate_bot_framework_jwt(header, APP_ID, SERVICE_URL, "msteams") is None


@pytest.mark.asyncio
async def test_valid_signature_returns_claims(signing_key, claims, jwks):
    token = _token(signing_key, claims)
    for _ in range(2):
        assert await security.validate_bot_framework_jwt(f"bearer {token}", APP_ID, SERVICE_URL, "msteams") == claims
    jwks[1].assert_called_once()
    security._fetch_openid_metadata.assert_called_once()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "change", [{"aud": "wrong"}, {"iss": "wrong"}, {"exp": 1}, {"serviceurl": None}, {"serviceurl": "https://other/"}]
)
async def test_invalid_claims_rejected(signing_key, claims, jwks, change):
    claims.update(change)
    if claims["serviceurl"] is None:
        del claims["serviceurl"]
    token = _token(signing_key, claims)
    assert await security.validate_bot_framework_jwt(f"Bearer {token}", APP_ID, SERVICE_URL, "msteams") is None


@pytest.mark.asyncio
@pytest.mark.parametrize("field", ["exp", "aud", "iss", "serviceurl"])
async def test_required_claims(signing_key, claims, jwks, field):
    del claims[field]
    assert (
        await security.validate_bot_framework_jwt(
            f"Bearer {_token(signing_key, claims)}", APP_ID, SERVICE_URL, "msteams"
        )
        is None
    )


@pytest.mark.asyncio
async def test_missing_kid_rejected(signing_key, claims, jwks):
    token = jwt.encode(claims, signing_key, algorithm="RS256")
    assert await security.validate_bot_framework_jwt(f"Bearer {token}", APP_ID, SERVICE_URL, "msteams") is None
    jwks[1].assert_not_called()


@pytest.mark.asyncio
async def test_metadata_without_uri_is_not_accepted(signing_key, claims, jwks):
    security._fetch_openid_metadata.return_value = {}
    assert (
        await security.validate_bot_framework_jwt(
            f"Bearer {_token(signing_key, claims)}", APP_ID, SERVICE_URL, "msteams"
        )
        is None
    )
    jwks[1].assert_not_called()


@pytest.mark.asyncio
async def test_bad_signature_rejected(claims, jwks):
    other_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    token = _token(other_key, claims)
    assert await security.validate_bot_framework_jwt(f"Bearer {token}", APP_ID, SERVICE_URL, "msteams") is None


@pytest.mark.asyncio
async def test_expiry_within_leeway_accepted(signing_key, claims, jwks):
    claims["exp"] = int(time.time()) - 240
    token = _token(signing_key, claims)
    assert await security.validate_bot_framework_jwt(f"Bearer {token}", APP_ID, SERVICE_URL, "msteams") == claims


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "endorsements,channel,accepted",
    [
        (["msteams"], "msteams", True),
        (["other"], "msteams", False),
        (None, "msteams", True),
        ([], "msteams", True),
        (["other"], None, True),
    ],
)
async def test_endorsements_follow_bot_framework(signing_key, claims, jwks, endorsements, channel, accepted):
    key, _ = jwks
    if endorsements is None:
        key.pop("endorsements")
    else:
        key["endorsements"] = endorsements
    result = await security.validate_bot_framework_jwt(
        f"Bearer {_token(signing_key, claims)}", APP_ID, SERVICE_URL, channel
    )
    assert (result is not None) == accepted


@pytest.mark.asyncio
async def test_unknown_kids_use_client_cooldown(signing_key, claims, jwks):
    key, fetch = jwks
    for kid in ["unknown-1", "unknown-2", "unknown-3"]:
        assert (
            await security.validate_bot_framework_jwt(
                f"Bearer {_token(signing_key, claims, kid)}", APP_ID, SERVICE_URL, "msteams"
            )
            is None
        )
    assert fetch.call_count == 1
    security._fetch_openid_metadata.assert_called_once()


@pytest.mark.asyncio
async def test_concurrent_first_requests_discover_metadata_once(signing_key, claims, jwks):
    metadata = security._fetch_openid_metadata

    def discover():
        assert threading.get_ident() != main_thread
        return {"jwks_uri": "https://example.com/keys"}

    main_thread = threading.get_ident()

    metadata.side_effect = discover
    token = _token(signing_key, claims)
    results = await asyncio.gather(
        *(security.validate_bot_framework_jwt(f"Bearer {token}", APP_ID, SERVICE_URL, "msteams") for _ in range(2))
    )
    assert results == [claims, claims]
    assert metadata.call_count == 1
    jwks[1].assert_called_once()


@pytest.mark.asyncio
async def test_signing_key_lookup_runs_off_loop(signing_key, claims, jwks):
    token = _token(signing_key, claims)
    await security.validate_bot_framework_jwt(f"Bearer {token}", APP_ID, SERVICE_URL, "msteams")
    client = security._jwk_client
    original = client.get_signing_key
    threads = []

    def get_key(kid):
        threads.append(threading.get_ident())
        return original(kid)

    with patch.object(client, "get_signing_key", side_effect=get_key):
        assert await security.validate_bot_framework_jwt(f"Bearer {token}", APP_ID, SERVICE_URL, "msteams") == claims
    assert threads and threads[0] != threading.get_ident()


@pytest.mark.asyncio
async def test_missing_crypto_reports_configuration_error():
    with patch("jwt.algorithms.has_crypto", False):
        with pytest.raises(HTTPException) as exc:
            await security.validate_bot_framework_jwt("Bearer x.y.z", APP_ID, SERVICE_URL)
    assert exc.value.status_code == 500
    assert "pyjwt[crypto]" in exc.value.detail


@pytest.mark.asyncio
async def test_bypass_only_without_app_id():
    with patch.dict("os.environ", {"MICROSOFT_APP_SKIP_JWT_VALIDATION": "True"}, clear=True):
        assert await security.validate_bot_framework_jwt(None, "", SERVICE_URL) == {}
        assert await security.validate_bot_framework_jwt(None, APP_ID, SERVICE_URL) is None
    with patch.dict("os.environ", {}, clear=True):
        with pytest.raises(HTTPException) as exc:
            await security.validate_bot_framework_jwt(None, "", SERVICE_URL)
        assert exc.value.status_code == 500


@pytest.mark.parametrize("body", [[], [1], "text", 12, True, None])
def test_webhook_rejects_non_object_before_auth(body):
    router = APIRouter()
    with patch.dict("os.environ", {"MICROSOFT_APP_SKIP_JWT_VALIDATION": "true"}, clear=True):
        attach_routes(router, agent=SimpleNamespace(id="agent", name="Agent", db=None))
        app = FastAPI()
        app.include_router(router)
        with TestClient(app) as client:
            response = client.post("/messages", content=json.dumps(body), headers={"Content-Type": "application/json"})
    assert response.status_code == 400


def test_webhook_enforces_serviceurl(signing_key, claims, jwks):
    router = APIRouter()
    with patch.dict(
        "os.environ",
        {"MICROSOFT_APP_ID": APP_ID, "MICROSOFT_APP_PASSWORD": "secret", "MICROSOFT_APP_TENANT_ID": "tenant"},
        clear=True,
    ):
        attach_routes(router, agent=SimpleNamespace(id="agent", name="Agent", db=None))
        app = FastAPI()
        app.include_router(router)
        with TestClient(app) as client:
            for url, status in [(SERVICE_URL, 200), ("https://other/", 403), (None, 403)]:
                response = client.post(
                    "/messages",
                    json={"type": "conversationUpdate", "serviceUrl": url, "channelId": "msteams"},
                    headers={"Authorization": f"Bearer {_token(signing_key, claims)}"},
                )
                assert response.status_code == status
