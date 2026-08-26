"""Shared fixtures for the SuperGrok OAuth unit suite.

Fixture values mirror the live-run observations: device grant expires_in 1800,
poll interval 5, token lifetime 21600 seconds, the scope echoed verbatim, and
the refresh response carrying no id_token.
"""

import os
import tempfile
import time
from typing import Any, Dict, List
from urllib.parse import parse_qsl

import httpx
import pytest

XAI_SCOPE = "openid profile email offline_access grok-cli:access api:access"

DEVICE_CODE_URL = "https://auth.x.ai/oauth2/device/code"
TOKEN_URL = "https://auth.x.ai/oauth2/token"


@pytest.fixture(autouse=True)
def _reset_oauth_cache():
    """Reset the module-level token cache so no test depends on execution order."""
    from agno.models.xai import oauth

    oauth._reset_cache_for_tests()
    yield
    oauth._reset_cache_for_tests()


class FakeClock:
    """Injectable clock: call it for the current time, advance() to move it forward."""

    def __init__(self, start: float = 1_000_000.0):
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


@pytest.fixture
def fake_clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def encryption_key() -> str:
    from agno.utils.encryption import generate_encryption_key

    return generate_encryption_key()


@pytest.fixture
def device_response() -> Dict[str, Any]:
    return {
        "device_code": "device-code-1",
        "user_code": "ABCD-1234",
        "verification_uri": "https://auth.x.ai/activate",
        "verification_uri_complete": "https://auth.x.ai/activate?user_code=ABCD-1234",
        "expires_in": 1800,
        "interval": 5,
    }


@pytest.fixture
def token_response() -> Dict[str, Any]:
    return {
        "access_token": "access-token-1",
        "refresh_token": "refresh-token-1",
        "id_token": "id-token-1",
        "token_type": "Bearer",
        "scope": XAI_SCOPE,
        "expires_in": 21600,
    }


@pytest.fixture
def refresh_response() -> Dict[str, Any]:
    # The live refresh response carries no id_token; the stored one must survive.
    return {
        "access_token": "access-token-2",
        "refresh_token": "refresh-token-2",
        "token_type": "Bearer",
        "scope": XAI_SCOPE,
        "expires_in": 21600,
    }


class TokenEndpoint:
    """MockTransport handler for auth.x.ai: serves device grants, polls, and refreshes."""

    def __init__(self, device_json: Dict[str, Any], token_json: Dict[str, Any], refresh_json: Dict[str, Any]):
        self.device_json = device_json
        self.token_json = token_json
        self.refresh_json = refresh_json
        self.refresh_status = 200
        self.refresh_delay = 0.0
        self.device_requests: List[Dict[str, str]] = []
        self.poll_requests: List[Dict[str, str]] = []
        self.refresh_requests: List[Dict[str, str]] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        fields = dict(parse_qsl(request.content.decode()))
        if str(request.url) == DEVICE_CODE_URL:
            self.device_requests.append(fields)
            return httpx.Response(200, json=self.device_json)
        if fields.get("grant_type") == "refresh_token":
            self.refresh_requests.append(fields)
            if self.refresh_delay:
                time.sleep(self.refresh_delay)
            return httpx.Response(self.refresh_status, json=self.refresh_json)
        self.poll_requests.append(fields)
        return httpx.Response(200, json=self.token_json)


@pytest.fixture
def token_endpoint(device_response, token_response, refresh_response) -> TokenEndpoint:
    return TokenEndpoint(device_response, token_response, refresh_response)


@pytest.fixture
def sqlite_db():
    from agno.db.sqlite.sqlite import SqliteDb

    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    db = SqliteDb(db_file=path)
    yield db
    try:
        os.unlink(path)
    except OSError:
        pass


@pytest.fixture
def async_sqlite_db():
    from agno.db.sqlite.async_sqlite import AsyncSqliteDb

    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    db = AsyncSqliteDb(db_file=path)
    yield db
    try:
        os.unlink(path)
    except OSError:
        pass
