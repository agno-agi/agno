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
from agno.tools.google.auth import google_authenticate, load_token
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
    """

    def __init__(self):
        super().__init__(name="mock_gmail")
        self.scopes = ["https://www.googleapis.com/auth/gmail.readonly"]
        self.creds: Optional[Credentials] = None
        self.service: Optional[Any] = None
        # Opt into DB-backed tokens so get_token_db resolves agent.db at call time.
        self.store_token_in_db = True
        self._db: Optional[Any] = None

    def _auth(self, user_id: Optional[str] = None, agent: Optional[Any] = None) -> None:
        ok = load_token(self, scopes=self.scopes, user_id=user_id, agent=agent)
        if not ok:
            raise RuntimeError(f"load_token failed for user {user_id!r}")

    def _build_service(self) -> Any:
        return MagicMock()

    @google_authenticate("gmail")
    def bearer_header(self) -> str:
        # Materialize the Authorization header exactly the way
        # google-api-python-client does before issuing a request.
        headers: dict = {}
        assert self.creds is not None
        self.creds.apply(headers)
        return headers["authorization"]

    @google_authenticate("gmail")
    def bearer_header_with_yield(self) -> str:
        # Same as above, but sleeps briefly between auth and apply to force
        # interleaving on thread-pool executors. Amplifies any race window.
        time.sleep(0.01)
        headers: dict = {}
        assert self.creds is not None
        self.creds.apply(headers)
        return headers["authorization"]


@pytest.fixture
def temp_db(tmp_path):
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


def test_shared_toolkit_leaks_bearer_token(temp_db):
    """Shared toolkit: Bob's outbound bearer is Alice's token. Deterministic leak."""
    for uid in USERS:
        _seed_user(temp_db, uid)
    agent = _MockAgent(db=temp_db)
    shared = _MockGmailToolkit()

    first = shared.bearer_header(run_context=_FakeRunContext(user_id="alice"), agent=agent)
    second = shared.bearer_header(run_context=_FakeRunContext(user_id="bob"), agent=agent)

    assert first == _expected_bearer("alice")
    # Canary: flips to Bearer TOKEN::bob if per-call isolation lands (e.g. PR #7404).
    assert second == _expected_bearer("alice"), (
        "Shared-toolkit bearer leak is expected on this branch. "
        f"Got {second!r} — if this is {_expected_bearer('bob')!r}, isolation is "
        "now automatic and the factory-pattern requirement should be revisited."
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


def test_real_thread_concurrency_shared_leaks(temp_db):
    """Real threads on a shared toolkit leak under forced interleaving.

    16 threads × 48 calls share one toolkit instance. With the 10ms sleep
    between auth and apply, threads will see each other's creds. We don't
    assert an exact count (timing-dependent), but we do assert at least one
    mismatch occurred — proving the shared-instance anti-pattern is unsafe
    under real concurrency, not just in theory.
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
    assert mismatches, (
        "Expected at least one bearer mismatch on shared-toolkit under forced "
        "thread interleaving. None observed — this may mean the scheduler happened "
        "to run every call serially, or isolation is now automatic. Re-run; if "
        "still clean, investigate whether per-call isolation has silently landed."
    )
