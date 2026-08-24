"""Live SuperGrok OAuth integration suite. Not executed by CI.

Runs only when XAI_OAUTH_REFRESH_TOKEN holds a valid SuperGrok refresh token
(obtain one by running the device-login cookbook). Covers a real refresh with
rotation persist, one real /v1/responses call, and a catalog fetch.
"""

import os
import tempfile

import httpx
import pytest

from agno.models.xai.oauth import XAI_TOKEN_URL, XAITokenManager
from agno.models.xai.responses import xAIResponses

pytestmark = pytest.mark.skipif(
    not os.getenv("XAI_OAUTH_REFRESH_TOKEN"),
    reason="XAI_OAUTH_REFRESH_TOKEN not set - the live SuperGrok OAuth suite is opt-in",
)


@pytest.fixture
def live_manager():
    """A manager seeded with the env refresh token and a stale access token, forcing a real refresh."""
    from agno.db.sqlite.sqlite import SqliteDb

    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    db = SqliteDb(db_file=path)

    encryption_key = os.getenv("XAI_TOKEN_ENCRYPTION_KEY")
    manager = XAITokenManager(db=db, encryption_key=encryption_key, encrypt_tokens=bool(encryption_key))

    token_data = {
        "access_token": "stale",
        "refresh_token": os.environ["XAI_OAUTH_REFRESH_TOKEN"],
        "token_type": "Bearer",
        "expires_at": 0,
        "token_endpoint": XAI_TOKEN_URL,
    }
    if encryption_key:
        from agno.utils.encryption import encrypt_dict

        token_data = encrypt_dict(token_data, key=encryption_key)
    db.upsert_auth_token(
        {"provider": "xai", "user_id": "", "service": "supergrok", "token_data": token_data, "granted_scopes": []}
    )

    yield manager, db, encryption_key
    try:
        os.unlink(path)
    except OSError:
        pass


def test_live_refresh_rotates_and_persists(live_manager):
    manager, db, encryption_key = live_manager

    access_token = manager.get_access_token()

    assert access_token
    assert access_token != "stale"
    row = db.get_auth_token("xai", "", "supergrok")
    token_data = row["token_data"]
    if encryption_key:
        from agno.utils.encryption import decrypt_dict

        token_data = decrypt_dict(token_data, key=encryption_key)
    assert token_data["access_token"] == access_token
    assert token_data["refresh_token"]  # the newest rotated refresh token is persisted


def test_live_responses_call(live_manager):
    from agno.models.message import Message

    manager, _db, _key = live_manager
    model = xAIResponses(token_manager=manager, id="grok-4.3")

    response = model.invoke(
        messages=[Message(role="user", content="Reply with the word ok.")], assistant_message=Message(role="assistant")
    )

    assert response.content


def test_live_catalog_fetch(live_manager):
    manager, _db, _key = live_manager

    response = httpx.get(
        "https://api.x.ai/v1/models", headers={"Authorization": "Bearer " + manager.get_access_token()}, timeout=30.0
    )

    assert response.status_code == 200
    assert response.json().get("data")
