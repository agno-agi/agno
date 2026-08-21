"""Unit tests for the public auth-lifecycle primitives: poll_once and sign_out.

poll_once is one RFC 8628 poll iteration as a typed outcome (no sleeping, no
loop - the caller owns pacing and deadlines); sign_out is the full local wipe
of the stored session. Both ship with hand-maintained async twins.
"""

import threading
from urllib.parse import parse_qsl

import httpx
import pytest

from agno.exceptions import ModelAuthenticationError
from agno.models.xai import oauth
from agno.models.xai.oauth import (
    XAI_OAUTH_CLIENT_ID,
    DevicePollResult,
    DevicePollStatus,
    XAITokenManager,
)
from agno.utils.encryption import decrypt_dict, is_encrypted

DENIED_MESSAGE = "SuperGrok sign-in was denied in the browser."
EXPIRED_MESSAGE = "The SuperGrok sign-in code expired (30 minutes). Start the login again."


def _manager(handler, **kwargs) -> XAITokenManager:
    return XAITokenManager(http_client=httpx.Client(transport=httpx.MockTransport(handler)), **kwargs)


def _counting(response: httpx.Response):
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return response

    return handler, calls


# ---------------------------------------------------------------------------
# T19: poll_once - one POST, four typed outcomes, unknown still raises
# ---------------------------------------------------------------------------


def test_poll_once_pending_echoes_interval_one_post():
    handler, calls = _counting(httpx.Response(400, json={"error": "authorization_pending"}))

    result = _manager(handler).poll_once("device-code-1", interval=7)

    assert result.status == DevicePollStatus.pending
    assert result.interval == 7  # unchanged: wait this long, poll again
    assert result.token_data is None
    assert len(calls) == 1 and calls[0].method == "POST"  # exactly one POST - no hidden loop
    assert dict(parse_qsl(calls[0].content.decode()))["client_id"] == XAI_OAUTH_CLIENT_ID


def test_poll_once_slow_down_bumps_interval_by_five():
    handler, calls = _counting(httpx.Response(400, json={"error": "slow_down"}))

    result = _manager(handler).poll_once("device-code-1", interval=7)

    assert result.status == DevicePollStatus.pending  # same caller action: wait, poll again
    assert result.interval == 12  # RFC 8628 section 3.5 mandates +5s
    assert len(calls) == 1 and calls[0].method == "POST"


def test_poll_once_success_persists_via_the_real_save_path(sqlite_db, encryption_key, token_response, fake_clock):
    handler, calls = _counting(httpx.Response(200, json=token_response))
    manager = _manager(handler, db=sqlite_db, encryption_key=encryption_key, now_fn=fake_clock)

    result = manager.poll_once("device-code-1", interval=5)

    assert result.status == DevicePollStatus.success
    assert result.interval == 5
    assert result.token_data is not None
    assert result.token_data["access_token"] == "access-token-1"
    assert result.token_data["expires_at"] == int(fake_clock()) + 21600
    assert len(calls) == 1 and calls[0].method == "POST"
    row = sqlite_db.get_auth_token("xai", "", "supergrok")
    assert is_encrypted(row["token_data"])
    # The stored envelope IS the returned one - full equality, not spot fields
    assert decrypt_dict(row["token_data"], key=encryption_key) == result.token_data
    assert oauth._token_cache[manager._cache_key()][0] == "access-token-1"


def test_poll_once_denied_returns_the_drafted_message():
    handler, calls = _counting(httpx.Response(400, json={"error": "access_denied"}))

    result = _manager(handler).poll_once("device-code-1", interval=5)

    assert result.status == DevicePollStatus.denied  # returned, not raised
    assert result.message == DENIED_MESSAGE
    assert len(calls) == 1 and calls[0].method == "POST"


def test_poll_once_expired_returns_the_drafted_message():
    handler, calls = _counting(httpx.Response(400, json={"error": "expired_token"}))

    result = _manager(handler).poll_once("device-code-1", interval=5)

    assert result.status == DevicePollStatus.expired
    assert result.message == EXPIRED_MESSAGE
    assert len(calls) == 1 and calls[0].method == "POST"


def test_poll_once_unknown_error_still_raises_with_raw_body():
    response = httpx.Response(400, json={"error": "pizza_error", "error_description": "the oven is off"})
    handler, calls = _counting(response)

    with pytest.raises(ModelAuthenticationError) as exc_info:
        _manager(handler).poll_once("device-code-1", interval=5)

    assert response.text in exc_info.value.message
    assert len(calls) == 1 and calls[0].method == "POST"


def test_poll_once_200_without_token_still_raises():
    handler, calls = _counting(httpx.Response(200, json={"error": "server_error"}))

    with pytest.raises(ModelAuthenticationError, match="missing access_token"):
        _manager(handler).poll_once("device-code-1", interval=5)

    assert len(calls) == 1 and calls[0].method == "POST"


# ---------------------------------------------------------------------------
# T20: apoll_once - full async twin mirror
# ---------------------------------------------------------------------------


async def test_apoll_once_pending_and_slow_down():
    responses = [
        httpx.Response(400, json={"error": "authorization_pending"}),
        httpx.Response(400, json={"error": "slow_down"}),
    ]
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return responses[min(len(calls), len(responses)) - 1]

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        manager = XAITokenManager(async_http_client=client)
        pending = await manager.apoll_once("device-code-1", interval=7)
        slowed = await manager.apoll_once("device-code-1", interval=7)

    assert pending.status == DevicePollStatus.pending
    assert pending.interval == 7
    assert slowed.status == DevicePollStatus.pending
    assert slowed.interval == 12
    assert len(calls) == 2 and all(call.method == "POST" for call in calls)  # one POST per call


async def test_apoll_once_success_persists(async_sqlite_db, encryption_key, token_response, fake_clock):
    handler, calls = _counting(httpx.Response(200, json=token_response))
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        manager = XAITokenManager(
            db=async_sqlite_db, encryption_key=encryption_key, async_http_client=client, now_fn=fake_clock
        )

        result = await manager.apoll_once("device-code-1", interval=5)

        assert result.status == DevicePollStatus.success
        assert result.interval == 5
        assert result.token_data is not None
        assert len(calls) == 1 and calls[0].method == "POST"
        row = await async_sqlite_db.get_auth_token("xai", "", "supergrok")
        assert is_encrypted(row["token_data"])
        assert decrypt_dict(row["token_data"], key=encryption_key) == result.token_data
        assert oauth._token_cache[manager._cache_key()][0] == "access-token-1"


async def test_apoll_once_terminal_and_unknown_outcomes():
    handler, calls = _counting(httpx.Response(400, json={"error": "access_denied"}))
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        denied = await XAITokenManager(async_http_client=client).apoll_once("device-code-1", interval=5)
    assert denied.status == DevicePollStatus.denied
    assert denied.message == DENIED_MESSAGE
    assert len(calls) == 1 and calls[0].method == "POST"

    handler, calls = _counting(httpx.Response(400, json={"error": "expired_token"}))
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        expired = await XAITokenManager(async_http_client=client).apoll_once("device-code-1", interval=5)
    assert expired.status == DevicePollStatus.expired
    assert expired.message == EXPIRED_MESSAGE
    assert len(calls) == 1 and calls[0].method == "POST"

    handler, calls = _counting(httpx.Response(500, text="upstream exploded"))
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(ModelAuthenticationError, match="upstream exploded"):
            await XAITokenManager(async_http_client=client).apoll_once("device-code-1", interval=5)
    assert len(calls) == 1 and calls[0].method == "POST"


async def test_apoll_once_200_without_token_still_raises():
    handler, calls = _counting(httpx.Response(200, json={"error": "server_error"}))

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(ModelAuthenticationError, match="missing access_token"):
            await XAITokenManager(async_http_client=client).apoll_once("device-code-1", interval=5)

    assert len(calls) == 1 and calls[0].method == "POST"


# ---------------------------------------------------------------------------
# T21: sign_out - wipes row + cache entry + memory, idempotent, fresh manager
# sees nothing
# ---------------------------------------------------------------------------


def test_sign_out_wipes_db_row_cache_and_memory(sqlite_db, encryption_key, token_endpoint, fake_clock):
    manager = _manager(token_endpoint, db=sqlite_db, encryption_key=encryption_key, now_fn=fake_clock)
    manager.poll_for_token("device-code-1", interval=5, deadline=fake_clock() + 1800)
    assert sqlite_db.get_auth_token("xai", "", "supergrok") is not None

    manager.sign_out()

    assert sqlite_db.get_auth_token("xai", "", "supergrok") is None
    assert manager._cache_key() not in oauth._token_cache
    assert manager._memory_rows.get("") is None
    with pytest.raises(ModelAuthenticationError):
        manager.get_access_token()

    manager.sign_out()  # idempotent second call: no raise

    # A fresh manager on the same store sees no token
    fresh = _manager(token_endpoint, db=sqlite_db, encryption_key=encryption_key, now_fn=fake_clock)
    with pytest.raises(ModelAuthenticationError):
        fresh.get_access_token()


def test_sign_out_wipes_file_store(tmp_path, encryption_key, token_endpoint, fake_clock):
    token_file = tmp_path / "xai_token.json"
    manager = _manager(token_endpoint, token_path=str(token_file), encryption_key=encryption_key, now_fn=fake_clock)
    manager.poll_for_token("device-code-1", interval=5, deadline=fake_clock() + 1800)
    assert token_file.exists()

    manager.sign_out()

    assert not token_file.exists()
    assert manager._cache_key() not in oauth._token_cache
    assert manager._memory_rows.get("") is None
    manager.sign_out()  # idempotent with nothing stored


# ---------------------------------------------------------------------------
# T22: asign_out - full async twin mirror
# ---------------------------------------------------------------------------


async def test_asign_out_wipes_db_row_cache_and_memory(async_sqlite_db, encryption_key, token_endpoint, fake_clock):
    async with httpx.AsyncClient(transport=httpx.MockTransport(token_endpoint)) as client:
        manager = XAITokenManager(
            db=async_sqlite_db, encryption_key=encryption_key, async_http_client=client, now_fn=fake_clock
        )
        await manager.apoll_for_token("device-code-1", interval=5, deadline=fake_clock() + 1800)
        assert await async_sqlite_db.get_auth_token("xai", "", "supergrok") is not None

        await manager.asign_out()

        assert await async_sqlite_db.get_auth_token("xai", "", "supergrok") is None
        assert manager._cache_key() not in oauth._token_cache
        assert manager._memory_rows.get("") is None
        with pytest.raises(ModelAuthenticationError):
            await manager.aget_access_token()

        await manager.asign_out()  # idempotent second call

        # A fresh manager on the same store sees no token
        fresh = XAITokenManager(
            db=async_sqlite_db, encryption_key=encryption_key, async_http_client=client, now_fn=fake_clock
        )
        with pytest.raises(ModelAuthenticationError):
            await fresh.aget_access_token()


async def test_asign_out_wipes_file_store(tmp_path, encryption_key, token_endpoint, fake_clock):
    token_file = tmp_path / "xai_token.json"
    async with httpx.AsyncClient(transport=httpx.MockTransport(token_endpoint)) as client:
        manager = XAITokenManager(
            token_path=str(token_file), encryption_key=encryption_key, async_http_client=client, now_fn=fake_clock
        )
        await manager.apoll_for_token("device-code-1", interval=5, deadline=fake_clock() + 1800)
        assert token_file.exists()

        await manager.asign_out()

        assert not token_file.exists()
        assert manager._cache_key() not in oauth._token_cache
        assert manager._memory_rows.get("") is None
        await manager.asign_out()  # idempotent with nothing stored


def test_evict_scope_survives_concurrent_cache_mutation():
    # A finalizer evicting a dead store's entries must tolerate concurrent
    # sign_out pops and cache puts; unguarded, the eviction's iteration raced
    # a mutation and stranded every dead-scope entry. Deterministic at this
    # scale; the rounds cost a few seconds - the price of a
    # credential-stranding regression.
    for _ in range(3):
        oauth._reset_cache_for_tests()
        for i in range(2_000_000):
            oauth._token_cache[("dead", f"p{i}", "", "s")] = ("tok", 9e9)

        barrier = threading.Barrier(2)
        stop = threading.Event()
        errors = []

        def evict():
            barrier.wait()
            try:
                oauth._evict_scope("dead")
            except RuntimeError as exc:
                errors.append(exc)
            finally:
                stop.set()

        def putter():
            barrier.wait()
            i = 0
            while not stop.is_set() and i < 20_000_000:
                oauth._token_cache[("live", f"x{i}", "", "s")] = ("t", 9e9)
                i += 1

        threads = [threading.Thread(target=putter), threading.Thread(target=evict)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(120)

        assert not errors, f"eviction raced a concurrent mutation: {errors[0]!r}"
        assert not any(key[0] == "dead" for key in list(oauth._token_cache))


def test_poll_result_shape():
    # The carrier is a plain dataclass with the four-status str enum
    result = DevicePollResult(status=DevicePollStatus.pending, interval=5)
    assert result.token_data is None
    assert result.message is None
    assert DevicePollStatus.success == "SUCCESS"
    assert {s.value for s in DevicePollStatus} == {"PENDING", "SUCCESS", "DENIED", "EXPIRED"}
