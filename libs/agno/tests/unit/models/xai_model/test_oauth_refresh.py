"""Unit tests for SuperGrok token refresh: margin, rotation, single-flight, invalid_grant.

The refresh design is lock-free across processes (the live probe showed a
rotation grace window) with in-process single-flight. Every expiry comparison
runs through the injectable clock, so these tests never sleep on real time.
"""

import asyncio
import gc
import threading
import time as time_module
import weakref
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


def test_async_lock_fetch_does_not_wait_on_the_sync_refresh_lock():
    # The sync slow path holds _cache_lock across a blocking HTTP refresh; the
    # async path must be able to obtain its own per-loop lock without waiting
    # behind it (its registry has a dedicated guard)
    release = threading.Event()

    def hold_sync_lock():
        with oauth._cache_lock:
            release.wait(timeout=5)

    holder = threading.Thread(target=hold_sync_lock)
    holder.start()
    time_module.sleep(0.1)  # let the holder acquire

    async def fetch_lock() -> float:
        start = time_module.monotonic()
        oauth._get_async_cache_lock()
        return time_module.monotonic() - start

    try:
        elapsed = asyncio.run(fetch_lock())
    finally:
        release.set()
        holder.join(timeout=5)
    assert elapsed < 0.5


def test_async_lock_is_stable_per_loop_across_concurrent_loops():
    # Two live loops in separate threads must each keep their own lock; a
    # single global slot would churn loop A's lock when loop B runs,
    # breaking per-loop single-flight
    a_first = threading.Event()
    b_done = threading.Event()
    ids = {}

    def loop_a():
        async def run():
            ids["a1"] = id(oauth._get_async_cache_lock())
            a_first.set()
            await asyncio.to_thread(b_done.wait, 5)
            ids["a2"] = id(oauth._get_async_cache_lock())

        asyncio.run(run())

    def loop_b():
        a_first.wait(5)

        async def run():
            ids["b"] = id(oauth._get_async_cache_lock())

        asyncio.run(run())
        b_done.set()

    thread_a, thread_b = threading.Thread(target=loop_a), threading.Thread(target=loop_b)
    thread_a.start()
    thread_b.start()
    thread_a.join(10)
    thread_b.join(10)

    assert ids["a1"] == ids["a2"]  # loop A's lock survived loop B running
    assert ids["b"] != ids["a1"]  # each loop has its own lock


def test_cache_never_serves_a_token_across_different_stores(
    sqlite_db, tmp_path, encryption_key, token_endpoint, fake_clock
):
    # Two managers on different stores can hold different accounts; the
    # module cache must be scoped to the store, never one shared slot
    from agno.db.sqlite.sqlite import SqliteDb

    other_db = SqliteDb(db_file=str(tmp_path / "other-store.db"))
    manager_a = XAITokenManager(
        db=sqlite_db,
        encryption_key=encryption_key,
        http_client=httpx.Client(transport=httpx.MockTransport(token_endpoint)),
        now_fn=fake_clock,
    )
    manager_b = XAITokenManager(
        db=other_db,
        encryption_key=encryption_key,
        http_client=httpx.Client(transport=httpx.MockTransport(token_endpoint)),
        now_fn=fake_clock,
    )
    manager_a.poll_for_token("device-code-1", interval=5, deadline=fake_clock() + 1800)

    with pytest.raises(ModelAuthenticationError):
        manager_b.get_access_token()


def test_cache_never_serves_a_dead_stores_token_after_id_reuse(tmp_path, encryption_key, fake_clock):
    # A collected store's cache entry must never be served to a NEW store whose
    # object happens to reuse the same id
    from agno.db.sqlite.sqlite import SqliteDb

    db_a = SqliteDb(db_file=str(tmp_path / "a.db"))
    manager_a = XAITokenManager(db=db_a, encryption_key=encryption_key, now_fn=fake_clock)
    # Seed the cache directly: the contract under test is the cache scope, and
    # the full poll path retains enough state to block deterministic id reuse
    manager_a._cache_put({"access_token": "store-a-token", "expires_at": fake_clock() + 21600})
    old_id = id(db_a)
    del manager_a, db_a
    gc.collect()

    reused = None
    for _ in range(10000):
        candidate = SqliteDb(db_file=str(tmp_path / "b.db"))
        if id(candidate) == old_id:
            reused = candidate
            break
        del candidate
    if reused is None:
        pytest.skip("CPython did not reuse the object id in 10000 allocations")

    manager_b = XAITokenManager(db=reused, encryption_key=encryption_key, now_fn=fake_clock)
    with pytest.raises(ModelAuthenticationError):
        manager_b.get_access_token()


def test_lock_registry_releases_contended_dead_loops():
    # A contended lock strongly references its loop (registry -> lock -> loop);
    # the registry must still release the pair once the loop is dead, at the
    # latest on a later fetch
    refs = {}

    async def contended():
        lock = oauth._get_async_cache_lock()

        async def hold():
            async with lock:
                await asyncio.sleep(0.02)

        async def wait_too():
            async with lock:
                pass

        await asyncio.gather(hold(), wait_too())
        refs["loop"] = weakref.ref(asyncio.get_running_loop())

    asyncio.run(contended())

    async def later_fetch():
        oauth._get_async_cache_lock()

    asyncio.run(later_fetch())
    gc.collect()
    assert refs["loop"]() is None


def test_refresh_200_with_error_body_raises_clean(sqlite_db, encryption_key, token_endpoint, fake_clock):
    # An HTTP 200 carrying an error body must surface as a clean auth error,
    # not a KeyError from envelope construction
    manager = _seeded_manager(sqlite_db, encryption_key, token_endpoint, fake_clock)
    token_endpoint.refresh_json = {"error": "server_error"}
    fake_clock.advance(21600 - 100)

    with pytest.raises(ModelAuthenticationError, match="missing access_token"):
        manager.get_access_token()


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
