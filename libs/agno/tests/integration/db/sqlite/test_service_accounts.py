"""Integration tests for the service_accounts table in SqliteDb."""

import time

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from agno.db.schemas.service_accounts import ServiceAccount


def _account(account_id: str, name: str, token_hash: str, **overrides):
    account = ServiceAccount(
        id=account_id,
        name=name,
        token_hash=token_hash,
        token_prefix="agno_pat_test123",
        scopes=["agents:run", "sessions:read"],
        **overrides,
    )
    return account.to_dict()


class TestServiceAccountsTable:
    def test_create_table_with_partial_unique_index(self, sqlite_db_real):
        sqlite_db_real._create_table(sqlite_db_real.service_accounts_table_name, "service_accounts")
        with sqlite_db_real.Session() as sess:
            result = sess.execute(
                text("SELECT name FROM sqlite_master WHERE type='table' AND name = :table"),
                {"table": sqlite_db_real.service_accounts_table_name},
            )
            assert result.fetchone() is not None
            result = sess.execute(
                text("SELECT name, sql FROM sqlite_master WHERE type='index' AND tbl_name = :table"),
                {"table": sqlite_db_real.service_accounts_table_name},
            )
            indexes = {row[0]: row[1] for row in result.fetchall()}
        partial_index_name = f"{sqlite_db_real.service_accounts_table_name}_uq_active_name"
        assert partial_index_name in indexes
        assert "revoked_at IS NULL" in indexes[partial_index_name]

    def test_crud_roundtrip(self, sqlite_db_real):
        created = sqlite_db_real.create_service_account(_account("sa-1", "claude-code", "hash-1", user_id="alice"))
        assert created["name"] == "claude-code"

        fetched = sqlite_db_real.get_service_account("sa-1")
        assert fetched is not None
        assert fetched["scopes"] == ["agents:run", "sessions:read"]
        assert fetched["user_id"] == "alice"

        by_hash = sqlite_db_real.get_service_account_by_token_hash("hash-1")
        assert by_hash is not None and by_hash["id"] == "sa-1"

        by_name = sqlite_db_real.get_service_account_by_name("claude-code")
        assert by_name is not None and by_name["id"] == "sa-1"

        updated = sqlite_db_real.update_service_account("sa-1", last_used_at=int(time.time()))
        assert updated is not None and updated["last_used_at"] is not None

        assert sqlite_db_real.delete_service_account("sa-1") is True
        assert sqlite_db_real.get_service_account("sa-1") is None

    def test_unknown_token_hash_returns_none(self, sqlite_db_real):
        sqlite_db_real.create_service_account(_account("sa-1", "claude-code", "hash-1"))
        assert sqlite_db_real.get_service_account_by_token_hash("no-such-hash") is None

    def test_token_hash_lookup_reraises_on_db_error(self, sqlite_db_real):
        # A dead connection must raise, not return None - the verifier maps a raise to
        # UNAVAILABLE (503) rather than misreading it as an unknown token (401).
        sqlite_db_real.create_service_account(_account("sa-1", "claude-code", "hash-1"))
        sqlite_db_real.db_engine.dispose()
        sqlite_db_real.db_url = "sqlite:////nonexistent/path/definitely_missing.db"
        from sqlalchemy import create_engine

        sqlite_db_real.db_engine = create_engine(sqlite_db_real.db_url)
        with pytest.raises(Exception):
            sqlite_db_real.get_service_account_by_token_hash("hash-1")

    def test_duplicate_active_name_rejected_but_reusable_after_revocation(self, sqlite_db_real):
        sqlite_db_real.create_service_account(_account("sa-1", "claude-code", "hash-1"))

        with pytest.raises(IntegrityError):
            sqlite_db_real.create_service_account(_account("sa-2", "claude-code", "hash-2"))

        sqlite_db_real.update_service_account("sa-1", revoked_at=int(time.time()))
        created = sqlite_db_real.create_service_account(_account("sa-3", "claude-code", "hash-3"))
        assert created["id"] == "sa-3"

        # Active lookup resolves to the new account
        active = sqlite_db_real.get_service_account_by_name("claude-code")
        assert active is not None and active["id"] == "sa-3"

    def test_list_pagination_and_revoked_filter(self, sqlite_db_real):
        now = int(time.time())
        for i in range(3):
            sqlite_db_real.create_service_account(_account(f"sa-{i}", f"account-{i}", f"hash-{i}", created_at=now - i))
        sqlite_db_real.update_service_account("sa-2", revoked_at=now)

        accounts, total = sqlite_db_real.get_service_accounts()
        assert total == 3

        accounts, total = sqlite_db_real.get_service_accounts(include_revoked=False)
        assert total == 2
        assert all(account["revoked_at"] is None for account in accounts)

        accounts, total = sqlite_db_real.get_service_accounts(limit=2, page=1)
        assert len(accounts) == 2 and total == 3

        accounts, _ = sqlite_db_real.get_service_accounts(sort_by="name", sort_order="asc")
        assert [account["name"] for account in accounts] == ["account-0", "account-1", "account-2"]

    def test_update_guardrails(self, sqlite_db_real):
        sqlite_db_real.create_service_account(_account("sa-1", "claude-code", "hash-1"))

        # Immutable columns are rejected before reaching the database
        with pytest.raises(ValueError, match="cannot modify"):
            sqlite_db_real.update_service_account("sa-1", token_hash="attacker-hash")
        with pytest.raises(ValueError, match="cannot modify"):
            sqlite_db_real.update_service_account("sa-1", name="other", last_used_at=int(time.time()))

        # Empty updates are rejected
        with pytest.raises(ValueError, match="at least one column"):
            sqlite_db_real.update_service_account("sa-1")

        # Revocation is one-way
        sqlite_db_real.update_service_account("sa-1", revoked_at=int(time.time()))
        with pytest.raises(ValueError, match="one-way"):
            sqlite_db_real.update_service_account("sa-1", revoked_at=None)

        # The record survived every rejected update untouched
        account = sqlite_db_real.get_service_account("sa-1")
        assert account is not None
        assert account["token_hash"] == "hash-1"
        assert account["name"] == "claude-code"
        assert account["revoked_at"] is not None
