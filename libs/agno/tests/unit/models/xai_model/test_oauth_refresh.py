"""Unit tests for SuperGrok token refresh: margin, rotation, single-flight, invalid_grant.

The refresh design is lock-free across processes (the live probe showed a
rotation grace window) with in-process single-flight. Every expiry comparison
runs through the injectable clock, so these tests never sleep on real time.
"""

import asyncio
from concurrent.futures import ThreadPoolExecutor

import httpx
import pytest

from agno.exceptions import ModelAuthenticationError
from agno.models.xai import oauth
from agno.models.xai.oauth import XAI_OAUTH_CLIENT_ID, XAITokenManager
from agno.utils.encryption import decrypt_dict

INVALID_GRANT_MESSAGE = (
    "SuperGrok session expired or was revoked. Sign in again (run the device login), "
    "or set XAI_API_KEY to use pay-per-token access."
)


def _seeded_manager(sqlite_db, encryption_key, token_endpoint, fake_clock) -> XAITokenManager:
    """A manager whose store holds a fresh token obtained through the device flow at t0."""
    manager = XAITokenManager(
        db=sqlite_db,
        encryption_key=encryption_key,
        http_client=httpx.Client(transport=httpx.MockTransport(token_endpoint)),
        now_fn=fake_clock,
    )
    manager.poll_for_token("device-code-1", interval=5, deadline=fake_clock() + 1800)
    return manager


# ---------------------------------------------------------------------------
# T4: proactive refresh fires inside the 300s margin, not outside
# ---------------------------------------------------------------------------


def test_no_refresh_outside_margin(sqlite_db, encryption_key, token_endpoint, fake_clock):
    manager = _seeded_manager(sqlite_db, encryption_key, token_endpoint, fake_clock)

    fake_clock.advance(21600 - 301)  # 301 seconds of lifetime left: outside the margin

    assert manager.get_access_token() == "access-token-1"
    assert token_endpoint.refresh_requests == []


def test_refresh_fires_inside_margin(sqlite_db, encryption_key, token_endpoint, fake_clock):
    manager = _seeded_manager(sqlite_db, encryption_key, token_endpoint, fake_clock)

    fake_clock.advance(21600 - 299)  # 299 seconds left: inside the 300s margin

    assert manager.get_access_token() == "access-token-2"
    assert len(token_endpoint.refresh_requests) == 1
    # Public-client refresh POST: exactly grant_type, refresh_token, client_id
    assert token_endpoint.refresh_requests[0] == {
        "grant_type": "refresh_token",
        "refresh_token": "refresh-token-1",
        "client_id": XAI_OAUTH_CLIENT_ID,
    }


# ---------------------------------------------------------------------------
# T5: rotation-tolerant persist; refresh response must not wipe id_token
# ---------------------------------------------------------------------------


def test_rotation_persists_new_refresh_token(sqlite_db, encryption_key, token_endpoint, fake_clock):
    manager = _seeded_manager(sqlite_db, encryption_key, token_endpoint, fake_clock)
    fake_clock.advance(21600 - 100)

    manager.get_access_token()

    row = sqlite_db.get_auth_token("xai", "", "supergrok")
    data = decrypt_dict(row["token_data"], key=encryption_key)
    assert data["access_token"] == "access-token-2"
    assert data["refresh_token"] == "refresh-token-2"
    # The refresh response has no id_token (live observation): keep the last seen one
    assert data["id_token"] == "id-token-1"


def test_refresh_without_rotation_keeps_old_refresh_token(
    sqlite_db, encryption_key, token_endpoint, fake_clock, refresh_response
):
    token_endpoint.refresh_json = {k: v for k, v in refresh_response.items() if k != "refresh_token"}
    manager = _seeded_manager(sqlite_db, encryption_key, token_endpoint, fake_clock)
    fake_clock.advance(21600 - 100)

    manager.get_access_token()

    row = sqlite_db.get_auth_token("xai", "", "supergrok")
    data = decrypt_dict(row["token_data"], key=encryption_key)
    assert data["access_token"] == "access-token-2"
    assert data["refresh_token"] == "refresh-token-1"


# ---------------------------------------------------------------------------
# T6: run twice - a second manager adopts the persisted state, no second POST
# ---------------------------------------------------------------------------


def test_second_manager_uses_persisted_state(sqlite_db, encryption_key, token_endpoint, fake_clock):
    _seeded_manager(sqlite_db, encryption_key, token_endpoint, fake_clock)

    oauth._reset_cache_for_tests()  # simulate a process restart: cache gone, store intact

    second = XAITokenManager(
        db=sqlite_db,
        encryption_key=encryption_key,
        http_client=httpx.Client(transport=httpx.MockTransport(token_endpoint)),
        now_fn=fake_clock,
    )
    assert second.get_access_token() == "access-token-1"
    assert token_endpoint.refresh_requests == []
    assert len(token_endpoint.poll_requests) == 1


# ---------------------------------------------------------------------------
# T7: in-process single-flight - N concurrent calls, exactly one refresh POST
# ---------------------------------------------------------------------------


def test_concurrent_calls_trigger_single_refresh(sqlite_db, encryption_key, token_endpoint, fake_clock):
    manager = _seeded_manager(sqlite_db, encryption_key, token_endpoint, fake_clock)
    fake_clock.advance(21600 - 100)
    token_endpoint.refresh_delay = 0.05  # widen the race window

    with ThreadPoolExecutor(max_workers=8) as pool:
        tokens = set(pool.map(lambda _: manager.get_access_token(), range(8)))

    assert tokens == {"access-token-2"}
    assert len(token_endpoint.refresh_requests) == 1


def test_contended_refresh_across_two_event_loops(sqlite_db, encryption_key, token_endpoint, fake_clock):
    # An asyncio.Lock binds to the event loop that first sees contention on it,
    # and sync callers wrapping arun in asyncio.run() give one process many
    # loops over its lifetime - a fresh loop must get a fresh lock
    async def slow_handler(request: httpx.Request) -> httpx.Response:
        await asyncio.sleep(0.01)  # real suspension so the second task contends
        return token_endpoint(request)

    manager = XAITokenManager(
        db=sqlite_db,
        encryption_key=encryption_key,
        http_client=httpx.Client(transport=httpx.MockTransport(token_endpoint)),
        async_http_client=httpx.AsyncClient(transport=httpx.MockTransport(slow_handler)),
        now_fn=fake_clock,
    )
    manager.poll_for_token("device-code-1", interval=5, deadline=fake_clock() + 1800)

    async def contended_refresh():
        await asyncio.gather(manager.aforce_refresh(), manager.aforce_refresh())

    asyncio.run(contended_refresh())  # loop 1: contention binds the lock
    asyncio.run(contended_refresh())  # loop 2: must not raise "bound to a different event loop"

    # force_refresh always refreshes: two POSTs per contended pair
    assert len(token_endpoint.refresh_requests) == 4
    assert manager.get_access_token() == "access-token-2"


# ---------------------------------------------------------------------------
# T8: invalid_grant wipes the store, raises, and never blind-retries
# ---------------------------------------------------------------------------


def test_invalid_grant_wipes_store_and_raises(sqlite_db, encryption_key, token_endpoint, fake_clock):
    manager = _seeded_manager(sqlite_db, encryption_key, token_endpoint, fake_clock)
    fake_clock.advance(21600 - 100)
    token_endpoint.refresh_status = 400
    token_endpoint.refresh_json = {"error": "invalid_grant"}

    with pytest.raises(ModelAuthenticationError) as exc_info:
        manager.get_access_token()

    assert exc_info.value.message == INVALID_GRANT_MESSAGE
    assert sqlite_db.get_auth_token("xai", "", "supergrok") is None
    assert len(token_endpoint.refresh_requests) == 1  # no blind retry of a refresh POST

    # The next call finds no stored token: a fresh sign-in is required
    with pytest.raises(ModelAuthenticationError):
        manager.get_access_token()
    assert len(token_endpoint.refresh_requests) == 1
