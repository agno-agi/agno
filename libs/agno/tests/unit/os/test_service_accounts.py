"""Unit tests for service account token utils and the ServiceAccountVerifier."""

import time
from typing import Any, Dict, Optional
from unittest.mock import MagicMock

import pytest

from agno.db.base import AsyncBaseDb, BaseDb
from agno.db.schemas.service_accounts import ServiceAccount
from agno.os.service_accounts import (
    DEFAULT_SERVICE_ACCOUNT_SCOPES,
    TOKEN_DISPLAY_PREFIX_LENGTH,
    TOKEN_PREFIX,
    ServiceAccountVerifier,
    VerificationStatus,
    _VerificationCache,
    generate_token,
    get_invalid_scopes,
    get_principal,
    get_privileged_scopes,
    hash_token,
    is_valid_service_account_name,
)


def _make_mock_db_class(base_class):
    abstract_methods = {}
    for name in dir(base_class):
        attr = getattr(base_class, name, None)
        if getattr(attr, "__isabstractmethod__", False):
            abstract_methods[name] = MagicMock()
    return type("MockDb", (base_class,), abstract_methods)


def _account_row(
    name: str = "claude-code",
    token_hash: str = "hash",
    expires_at: Optional[int] = None,
    revoked_at: Optional[int] = None,
) -> Dict[str, Any]:
    return {
        "id": "sa-id-1",
        "name": name,
        "user_id": "admin-user",
        "token_hash": token_hash,
        "token_prefix": "agno_pat_abc1234",
        "scopes": list(DEFAULT_SERVICE_ACCOUNT_SCOPES),
        "created_at": int(time.time()) - 100,
        "expires_at": expires_at,
        "last_used_at": None,
        "revoked_at": revoked_at,
        "created_by": "admin-user",
    }


class TestTokenGeneration:
    def test_token_format(self):
        plaintext, token_hash, token_prefix = generate_token()
        assert plaintext.startswith(TOKEN_PREFIX)
        assert len(token_prefix) == TOKEN_DISPLAY_PREFIX_LENGTH
        assert plaintext.startswith(token_prefix)
        assert token_hash == hash_token(plaintext)

    def test_token_random_part_is_base62(self):
        plaintext, _, _ = generate_token()
        random_part = plaintext[len(TOKEN_PREFIX) :]
        assert len(random_part) >= 40
        assert all(c.isalnum() for c in random_part)

    def test_tokens_are_unique(self):
        tokens = {generate_token()[0] for _ in range(50)}
        assert len(tokens) == 50

    def test_hash_is_sha256_hex(self):
        token_hash = hash_token("agno_pat_test")
        assert len(token_hash) == 64
        assert int(token_hash, 16) is not None


class TestNameValidation:
    def test_valid_names(self):
        for name in ["claude-code", "cursor", "github-actions", "a", "ci_bot-2"]:
            assert is_valid_service_account_name(name), name

    def test_invalid_names(self):
        for name in [
            "",
            "Claude-Code",  # uppercase
            "__scheduler__",  # leading underscore
            "sa:claude-code",  # colon (principal namespace)
            "user@example.com",  # email shape
            "-leading-dash",
            "a" * 64,  # too long
            "github-actions\n",  # trailing newline must not sneak past the anchor
            "claude\ncode",  # embedded newline
        ]:
            assert not is_valid_service_account_name(name), repr(name)


class TestPrincipal:
    def test_principal_is_namespaced(self):
        assert get_principal("claude-code") == "sa:claude-code"

    def test_dataclass_principal_matches(self):
        account = ServiceAccount.from_dict(_account_row(name="cursor"))
        assert account.principal == "sa:cursor"


class TestScopeHelpers:
    def test_invalid_scopes_detected(self):
        assert get_invalid_scopes(["agents:run", "bogus"]) == ["bogus"]
        assert get_invalid_scopes(["a:b:c:d"]) == ["a:b:c:d"]
        assert get_invalid_scopes(DEFAULT_SERVICE_ACCOUNT_SCOPES) == []

    def test_privileged_scopes_two_part(self):
        assert get_privileged_scopes(["sessions:write"]) == ["sessions:write"]
        assert get_privileged_scopes(["memories:delete"]) == ["memories:delete"]
        assert get_privileged_scopes(["agents:run", "sessions:read"]) == []

    def test_privileged_scopes_three_part(self):
        assert get_privileged_scopes(["sessions:*:delete"]) == ["sessions:*:delete"]
        assert get_privileged_scopes(["agents:my-agent:run"]) == []

    def test_admin_scope_is_privileged(self):
        assert get_privileged_scopes(["agent_os:admin"]) == ["agent_os:admin"]

    def test_custom_admin_scope_is_privileged(self):
        assert get_privileged_scopes(["custom:admin:scope"], admin_scope="custom:admin:scope") == ["custom:admin:scope"]

    def test_service_accounts_scopes_are_privileged(self):
        assert get_privileged_scopes(["service_accounts:read"]) == ["service_accounts:read"]
        assert get_privileged_scopes(["service_accounts:write"]) == ["service_accounts:write"]


class TestVerificationCache:
    def _account(self, name="claude-code", expires_at=None):
        return ServiceAccount.from_dict(_account_row(name=name, expires_at=expires_at))

    def test_put_then_get_hits(self):
        cache = _VerificationCache(ttl_seconds=30)
        cache.put("h1", self._account())
        assert cache.get("h1") is not None

    def test_ttl_zero_never_stores_or_serves(self):
        cache = _VerificationCache(ttl_seconds=0)
        assert cache.enabled is False
        cache.put("h1", self._account())
        assert cache.get("h1") is None

    def test_ttl_expiry_evicts(self):
        cache = _VerificationCache(ttl_seconds=30)
        # Force the cached-at timestamp into the past beyond the TTL.
        cache._entries["h1"] = (self._account(), time.monotonic() - 100)
        assert cache.get("h1") is None
        assert "h1" not in cache._entries

    def test_expired_account_not_served_within_ttl(self):
        cache = _VerificationCache(ttl_seconds=30)
        # Fresh cache entry (within TTL) but the account itself has expired.
        cache._entries["h1"] = (self._account(expires_at=int(time.time()) - 10), time.monotonic())
        assert cache.get("h1") is None
        assert "h1" not in cache._entries

    def test_lru_eviction(self):
        cache = _VerificationCache(ttl_seconds=30, max_entries=2)
        cache.put("h1", self._account("a"))
        cache.put("h2", self._account("b"))
        cache.get("h1")  # h1 becomes most-recently-used
        cache.put("h3", self._account("c"))  # evicts the LRU entry (h2)
        assert cache.get("h1") is not None
        assert cache.get("h2") is None
        assert cache.get("h3") is not None

    def test_invalidate_removes_entry(self):
        cache = _VerificationCache(ttl_seconds=30)
        cache.put("h1", self._account())
        cache.invalidate("h1")
        assert cache.get("h1") is None
        # Idempotent
        cache.invalidate("h1")


class TestVerifier:
    @pytest.fixture
    def sync_db(self):
        MockDbClass = _make_mock_db_class(BaseDb)
        db = MockDbClass()
        db.get_service_account_by_token_hash = MagicMock(return_value=None)
        db.update_service_account = MagicMock(return_value=None)
        return db

    @pytest.mark.asyncio
    async def test_unknown_token_is_invalid(self, sync_db):
        verifier = ServiceAccountVerifier(db=sync_db)
        result = await verifier.verify("agno_pat_unknown", client_key="1.2.3.4")
        assert result.status == VerificationStatus.INVALID
        assert result.account is None

    @pytest.mark.asyncio
    async def test_valid_token_ok_and_touches_last_used(self, sync_db):
        plaintext, token_hash, _ = generate_token()
        sync_db.get_service_account_by_token_hash.return_value = _account_row(token_hash=token_hash)
        verifier = ServiceAccountVerifier(db=sync_db)
        result = await verifier.verify(plaintext, client_key="1.2.3.4")
        assert result.ok
        assert result.account is not None
        assert result.account.principal == "sa:claude-code"
        sync_db.get_service_account_by_token_hash.assert_called_once_with(token_hash)
        sync_db.update_service_account.assert_called_once()

    @pytest.mark.asyncio
    async def test_last_used_write_is_throttled(self, sync_db):
        plaintext, token_hash, _ = generate_token()
        sync_db.get_service_account_by_token_hash.return_value = _account_row(token_hash=token_hash)
        verifier = ServiceAccountVerifier(db=sync_db)
        await verifier.verify(plaintext)
        await verifier.verify(plaintext)
        assert sync_db.update_service_account.call_count == 1

    @pytest.mark.asyncio
    async def test_revoked_token_is_invalid(self, sync_db):
        plaintext, token_hash, _ = generate_token()
        sync_db.get_service_account_by_token_hash.return_value = _account_row(
            token_hash=token_hash, revoked_at=int(time.time())
        )
        verifier = ServiceAccountVerifier(db=sync_db)
        result = await verifier.verify(plaintext)
        assert result.status == VerificationStatus.INVALID

    @pytest.mark.asyncio
    async def test_expired_token_is_invalid(self, sync_db):
        plaintext, token_hash, _ = generate_token()
        sync_db.get_service_account_by_token_hash.return_value = _account_row(
            token_hash=token_hash, expires_at=int(time.time()) - 10
        )
        verifier = ServiceAccountVerifier(db=sync_db)
        result = await verifier.verify(plaintext)
        assert result.status == VerificationStatus.INVALID

    @pytest.mark.asyncio
    async def test_db_error_is_unavailable_and_not_counted(self, sync_db):
        sync_db.get_service_account_by_token_hash.side_effect = RuntimeError("connection refused")
        verifier = ServiceAccountVerifier(db=sync_db)
        verifier._limiter.max_failures = 2
        for _ in range(5):
            result = await verifier.verify("agno_pat_whatever", client_key="1.2.3.4")
            assert result.status == VerificationStatus.UNAVAILABLE

    @pytest.mark.asyncio
    async def test_not_implemented_is_unavailable(self, sync_db):
        sync_db.get_service_account_by_token_hash.side_effect = NotImplementedError
        verifier = ServiceAccountVerifier(db=sync_db)
        result = await verifier.verify("agno_pat_whatever")
        assert result.status == VerificationStatus.UNAVAILABLE

    @pytest.mark.asyncio
    async def test_failed_lookups_are_rate_limited(self, sync_db):
        verifier = ServiceAccountVerifier(db=sync_db)
        verifier._limiter.max_failures = 3
        for _ in range(3):
            result = await verifier.verify("agno_pat_bad", client_key="1.2.3.4")
            assert result.status == VerificationStatus.INVALID
        result = await verifier.verify("agno_pat_bad", client_key="1.2.3.4")
        assert result.status == VerificationStatus.THROTTLED
        # A different client is unaffected
        result = await verifier.verify("agno_pat_bad", client_key="5.6.7.8")
        assert result.status == VerificationStatus.INVALID

    @pytest.mark.asyncio
    async def test_valid_token_never_blocked_by_limiter(self, sync_db):
        # A flood of bad tokens must not deny service to a valid token from the same key.
        plaintext, token_hash, _ = generate_token()
        verifier = ServiceAccountVerifier(db=sync_db)
        verifier._limiter.max_failures = 3
        for _ in range(10):
            result = await verifier.verify("agno_pat_bad", client_key="1.2.3.4")
            assert result.status in (VerificationStatus.INVALID, VerificationStatus.THROTTLED)
        # The valid token still authenticates despite the throttled bucket.
        sync_db.get_service_account_by_token_hash.return_value = _account_row(token_hash=token_hash)
        result = await verifier.verify(plaintext, client_key="1.2.3.4")
        assert result.ok

    @pytest.mark.asyncio
    async def test_cache_hit_avoids_second_db_lookup(self, sync_db):
        plaintext, token_hash, _ = generate_token()
        sync_db.get_service_account_by_token_hash.return_value = _account_row(token_hash=token_hash)
        verifier = ServiceAccountVerifier(db=sync_db, cache_ttl_seconds=30)
        first = await verifier.verify(plaintext)
        second = await verifier.verify(plaintext)
        assert first.ok and second.ok
        # The DB is consulted only once; the second verify is served from cache.
        sync_db.get_service_account_by_token_hash.assert_called_once()

    @pytest.mark.asyncio
    async def test_ttl_zero_disables_cache(self, sync_db):
        plaintext, token_hash, _ = generate_token()
        sync_db.get_service_account_by_token_hash.return_value = _account_row(token_hash=token_hash)
        verifier = ServiceAccountVerifier(db=sync_db, cache_ttl_seconds=0)
        await verifier.verify(plaintext)
        await verifier.verify(plaintext)
        assert sync_db.get_service_account_by_token_hash.call_count == 2

    @pytest.mark.asyncio
    async def test_invalidate_forces_next_verify_to_hit_db(self, sync_db):
        plaintext, token_hash, _ = generate_token()
        sync_db.get_service_account_by_token_hash.return_value = _account_row(token_hash=token_hash)
        verifier = ServiceAccountVerifier(db=sync_db, cache_ttl_seconds=30)
        await verifier.verify(plaintext)
        verifier.invalidate(token_hash)
        await verifier.verify(plaintext)
        assert sync_db.get_service_account_by_token_hash.call_count == 2

    @pytest.mark.asyncio
    async def test_revoked_after_cache_served_until_invalidated(self, sync_db):
        # Convergence semantics: a token cached as valid keeps authenticating within the
        # TTL until the local cache is evicted; once evicted it reflects the revocation.
        plaintext, token_hash, _ = generate_token()
        sync_db.get_service_account_by_token_hash.return_value = _account_row(token_hash=token_hash)
        verifier = ServiceAccountVerifier(db=sync_db, cache_ttl_seconds=30)
        assert (await verifier.verify(plaintext)).ok

        # Account is revoked in the DB, but the cached entry still authenticates.
        sync_db.get_service_account_by_token_hash.return_value = _account_row(
            token_hash=token_hash, revoked_at=int(time.time())
        )
        assert (await verifier.verify(plaintext)).ok

        # After eviction, the next verify reflects the revocation.
        verifier.invalidate(token_hash)
        assert (await verifier.verify(plaintext)).status == VerificationStatus.INVALID

    @pytest.mark.asyncio
    async def test_async_db_lookup_is_awaited(self):
        MockDbClass = _make_mock_db_class(AsyncBaseDb)
        db = MockDbClass()
        plaintext, token_hash, _ = generate_token()
        row = _account_row(token_hash=token_hash)

        async def _get_by_hash(t):
            assert t == token_hash
            return row

        async def _update(account_id, **kwargs):
            assert kwargs.get("last_used_at") is not None
            return row

        db.get_service_account_by_token_hash = _get_by_hash
        db.update_service_account = _update
        verifier = ServiceAccountVerifier(db=db)
        result = await verifier.verify(plaintext)
        assert result.ok
