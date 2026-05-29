"""Client-isolation tests for Google auth on v2.6.0 + PR #7376.

Uses REAL ``google.oauth2.credentials.Credentials`` (not stand-ins), seeded
with distinct per-user tokens via an opt-in DB. Every test asserts the
property that matters for client isolation in production: *the bearer token
that would be attached to an outbound Google API call matches the user_id
who originated the request*.

Suites:

1. ``test_factory_pattern_bearer_matches_user`` — 30 concurrent requests via
   ``asyncio.gather``, each with a different ``user_id``. Each request
   constructs a fresh toolkit via a factory callable, authenticates from DB,
   and calls ``Credentials.apply({})`` to materialize the ``Authorization``
   header exactly as the google-api-python-client would. Assertion: every
   request's bearer equals ``Bearer TOKEN::<originating user>``.

2. ``test_shared_toolkit_leaks_bearer_token`` — anti-pattern canary. Alice's
   call populates ``self.creds``; Bob's sequential call short-circuits at
   ``auth.py:42`` (``if not self.creds or not self.creds.valid``) and Bob's
   outbound header carries Alice's bearer. Deterministic — no race needed.

3. ``test_framework_factory_invocation_isolates_bearer`` — same as (1) via
   the real ``agno.utils.callables.ainvoke_callable_factory`` path that
   ``agent.arun`` uses internally.

4. ``test_real_thread_concurrency_factory_isolates`` — uses
   ``ThreadPoolExecutor`` with 16 threads and a forced ``time.sleep`` between
   ``_auth`` and the creds read. Real preemptive concurrency proves the
   factory pattern holds even when calls interleave at arbitrary points.

5. ``test_real_thread_concurrency_shared_leaks`` — same forced interleaving
   against a shared toolkit. Proves the leak is not a test artifact.

Not covered (documented so the reader knows what's *not* being claimed):

* Real OAuth redirect/code-exchange flow (covered by ``test_google_auth_state.py``).
* Real Google API responses (no HTTP transport is exercised).
* Token refresh under concurrent expiry (would need a clock-skew harness).
* Real Google accounts. Would need secrets + sandbox setup.
"""

from __future__ import annotations

import asyncio
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from typing import Any, List, Optional
from unittest.mock import MagicMock

import pytest
from google.oauth2.credentials import Credentials

from agno.db.sqlite import SqliteDb
from agno.tools.google.auth import get_current_creds, get_token_db, google_authenticate
from agno.tools.toolkit import Toolkit
from agno.utils.callables import ainvoke_callable_factory


class _FakeRunContext:
    def __init__(self, user_id: str):
        self.user_id = user_id
        self.session_state: Optional[dict] = None


class _MockAgent:
    def __init__(self, db):
        self.db = db


class _MockGmailToolkit(Toolkit):
    """Minimal Google-style toolkit whose tool method returns the bearer
    header that would be attached to an outbound Google API call.

    Mirrors the real ``@google_authenticate``-decorated methods but skips
    actual HTTP. What we assert — ``creds.apply(headers)['authorization']`` —
    is literally what google-api-python-client computes internally before
    sending the request, so a correct value here proves outbound isolation.

    Updated for stateless pattern: credentials resolved per-call via
    _resolve_creds() and accessed via get_current_creds() contextvar.
    """

    def __init__(self):
        super().__init__(name="mock_gmail")
        self.scopes = ["https://www.googleapis.com/auth/gmail.readonly"]
        # Opt into DB-backed tokens so get_token_db resolves agent.db at call time.
        self.store_token_in_db = True
        self._db: Optional[Any] = None

    def _resolve_creds(self, run_context: Optional[Any] = None, agent: Optional[Any] = None) -> Credentials:
        user_id = getattr(run_context, "user_id", None) if run_context else None
        db = get_token_db(self, agent=agent)
        if db is None:
            raise RuntimeError(f"No DB available for user {user_id!r}")
        row = db.get_auth_token("google", user_id, "google")
        if not row:
            raise RuntimeError(f"No token found for user {user_id!r}")
        effective_scopes = row.get("granted_scopes") or self.scopes
        creds = Credentials.from_authorized_user_info(row["token_data"], effective_scopes)
        return creds

    def _build_service(self, creds: Credentials) -> Any:
        return MagicMock()

    @google_authenticate("gmail")
    def bearer_header(self, agent: Any, run_context: Any) -> str:
        # Materialize the Authorization header exactly the way
        # google-api-python-client does before issuing a request.
        # Stateless: access creds via contextvar, not self.creds
        headers: dict = {}
        creds = get_current_creds()
        assert creds is not None
        creds.apply(headers)
        return headers["authorization"]

    @google_authenticate("gmail")
    def bearer_header_with_yield(self, agent: Any, run_context: Any) -> str:
        # Same as above, but sleeps briefly between auth and apply to force
        # interleaving on thread-pool executors. Amplifies any race window.
        time.sleep(0.01)
        headers: dict = {}
        creds = get_current_creds()
        assert creds is not None
        creds.apply(headers)
        return headers["authorization"]


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    # Encryption key required for upsert_auth_token - use a test key
    from cryptography.fernet import Fernet

    monkeypatch.setenv("AGNO_ENCRYPTION_KEY", Fernet.generate_key().decode())
    return SqliteDb(db_file=str(tmp_path / "auth.db"))


def _seed_user(db: SqliteDb, uid: str) -> None:
    # Seed with a future expiry so load_token doesn't trigger Credentials.refresh
    # (which would try to hit Google's real token endpoint).
    expiry = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    db.upsert_auth_token(
        {
            "provider": "google",
            "user_id": uid,
            "service": "google",
            "token_data": {
                "token": f"TOKEN::{uid}",
                "refresh_token": f"refresh_{uid}",
                "client_id": "test",
                "client_secret": "secret",
                "scopes": ["https://www.googleapis.com/auth/gmail.readonly"],
                "expiry": expiry,
            },
            "granted_scopes": ["https://www.googleapis.com/auth/gmail.readonly"],
        }
    )


USERS = ["alice", "bob", "charlie"]
N_REQUESTS = 30


def _expected_bearer(uid: str) -> str:
    return f"Bearer TOKEN::{uid}"


@pytest.mark.asyncio
async def test_factory_pattern_bearer_matches_user(temp_db):
    """30 concurrent arun-style calls. Each call's outbound bearer matches origin user."""
    for uid in USERS:
        _seed_user(temp_db, uid)
    agent = _MockAgent(db=temp_db)

    def toolkit_factory(run_context) -> List[_MockGmailToolkit]:
        return [_MockGmailToolkit()]

    async def one_call(uid: str) -> str:
        rc = _FakeRunContext(user_id=uid)
        toolkits = toolkit_factory(rc)
        return toolkits[0].bearer_header(run_context=rc, agent=agent)

    plan = [USERS[i % len(USERS)] for i in range(N_REQUESTS)]
    results = await asyncio.gather(*(one_call(u) for u in plan))

    expected = [_expected_bearer(u) for u in plan]
    assert results == expected, (
        "Outbound bearer mismatch — client isolation broken.\n"
        f"plan     = {plan}\n"
        f"expected = {expected}\n"
        f"got      = {results}"
    )


def test_shared_toolkit_isolates_bearer_token(temp_db):
    """Shared toolkit with contextvars: each call gets correct user's token."""
    for uid in USERS:
        _seed_user(temp_db, uid)
    agent = _MockAgent(db=temp_db)
    shared = _MockGmailToolkit()

    first = shared.bearer_header(run_context=_FakeRunContext(user_id="alice"), agent=agent)
    second = shared.bearer_header(run_context=_FakeRunContext(user_id="bob"), agent=agent)

    assert first == _expected_bearer("alice")
    # With contextvars, each call resolves creds per-call — no leak
    assert second == _expected_bearer("bob"), (
        "Per-call isolation via contextvars should give Bob his own token. "
        f"Got {second!r} — expected {_expected_bearer('bob')!r}."
    )


@pytest.mark.asyncio
async def test_framework_factory_invocation_isolates_bearer(temp_db):
    """Same guarantee via the real framework code path."""
    for uid in USERS:
        _seed_user(temp_db, uid)
    agent = _MockAgent(db=temp_db)

    def toolkit_factory(run_context) -> List[_MockGmailToolkit]:
        return [_MockGmailToolkit()]

    async def one_call(uid: str) -> str:
        rc = _FakeRunContext(user_id=uid)
        toolkits = await ainvoke_callable_factory(toolkit_factory, entity=agent, run_context=rc)
        return toolkits[0].bearer_header(run_context=rc, agent=agent)

    plan = [USERS[i % len(USERS)] for i in range(N_REQUESTS)]
    results = await asyncio.gather(*(one_call(u) for u in plan))
    assert results == [_expected_bearer(u) for u in plan]


def test_real_thread_concurrency_factory_isolates(temp_db):
    """Real threads with forced interleaving. Factory pattern holds under preemption.

    The ``bearer_header_with_yield`` tool sleeps 10ms between ``_auth`` and
    ``creds.apply()``, creating a wide race window. 16 worker threads, 48
    calls mixed across 3 users. Assertion: every request's bearer matches
    the user that initiated the request — isolation holds under real
    preemptive concurrency.
    """
    for uid in USERS:
        _seed_user(temp_db, uid)
    agent = _MockAgent(db=temp_db)

    def one_call(uid: str) -> str:
        rc = _FakeRunContext(user_id=uid)
        toolkit = _MockGmailToolkit()  # fresh instance per call — factory pattern
        return toolkit.bearer_header_with_yield(run_context=rc, agent=agent)

    plan = [USERS[i % len(USERS)] for i in range(48)]
    with ThreadPoolExecutor(max_workers=16) as pool:
        # Preserve ordering by using map
        results = list(pool.map(one_call, plan))

    assert results == [_expected_bearer(u) for u in plan], (
        "Factory pattern failed under real thread concurrency.\n"
        f"mismatches: {[(p, r) for p, r in zip(plan, results) if r != _expected_bearer(p)]}"
    )


def test_real_thread_concurrency_shared_isolates(temp_db):
    """Real threads on a shared toolkit with contextvars: isolation holds.

    16 threads × 48 calls share one toolkit instance. With the 10ms sleep
    between auth and apply, threads interleave — but contextvars ensure
    each thread sees its own credentials. No mismatches should occur.
    """
    for uid in USERS:
        _seed_user(temp_db, uid)
    agent = _MockAgent(db=temp_db)
    shared = _MockGmailToolkit()

    def one_call(uid: str) -> str:
        rc = _FakeRunContext(user_id=uid)
        return shared.bearer_header_with_yield(run_context=rc, agent=agent)

    plan = [USERS[i % len(USERS)] for i in range(48)]
    with ThreadPoolExecutor(max_workers=16) as pool:
        futures = {pool.submit(one_call, u): u for u in plan}
        results = [(futures[f], f.result()) for f in as_completed(futures)]

    mismatches = [(u, bearer) for u, bearer in results if bearer != _expected_bearer(u)]
    assert not mismatches, (
        "Per-call isolation via contextvars should prevent credential leaks. "
        f"Got {len(mismatches)} mismatches: {mismatches[:5]}"
    )
