"""Integration tests for the service_accounts table in PostgresDb.

Requires a local postgres at localhost:5532 (ai:ai/ai), same as the other
postgres integration tests. Not run in CI.
"""

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
    def test_create_table_with_partial_unique_index(self, postgres_db_real):
        postgres_db_real._create_table(postgres_db_real.service_accounts_table_name, "service_accounts")
        with postgres_db_real.Session() as sess:
            result = sess.execute(
                text(
                    "SELECT table_name FROM information_schema.tables WHERE table_schema = :schema AND table_name = :table"
                ),
                {"schema": postgres_db_real.db_schema, "table": postgres_db_real.service_accounts_table_name},
            )
            assert result.fetchone() is not None

            result = sess.execute(
                text("SELECT indexname, indexdef FROM pg_indexes WHERE schemaname = :schema AND tablename = :table"),
                {"schema": postgres_db_real.db_schema, "table": postgres_db_real.service_accounts_table_name},
            )
            indexes = {row[0]: row[1] for row in result.fetchall()}
        partial_index_name = f"{postgres_db_real.service_accounts_table_name}_uq_active_name"
        assert partial_index_name in indexes
        assert "revoked_at IS NULL" in indexes[partial_index_name]

    def test_crud_roundtrip(self, postgres_db_real):
        created = postgres_db_real.create_service_account(_account("sa-1", "claude-code", "hash-1", user_id="alice"))
        assert created["name"] == "claude-code"

        fetched = postgres_db_real.get_service_account("sa-1")
        assert fetched is not None
        assert fetched["scopes"] == ["agents:run", "sessions:read"]
        assert fetched["user_id"] == "alice"

        by_hash = postgres_db_real.get_service_account_by_token_hash("hash-1")
        assert by_hash is not None and by_hash["id"] == "sa-1"

        by_name = postgres_db_real.get_service_account_by_name("claude-code")
        assert by_name is not None and by_name["id"] == "sa-1"

        updated = postgres_db_real.update_service_account("sa-1", last_used_at=int(time.time()))
        assert updated is not None and updated["last_used_at"] is not None

        assert postgres_db_real.delete_service_account("sa-1") is True
        assert postgres_db_real.get_service_account("sa-1") is None

    def test_duplicate_active_name_rejected_but_reusable_after_revocation(self, postgres_db_real):
        postgres_db_real.create_service_account(_account("sa-1", "claude-code", "hash-1"))

        with pytest.raises(IntegrityError):
            postgres_db_real.create_service_account(_account("sa-2", "claude-code", "hash-2"))

        postgres_db_real.update_service_account("sa-1", revoked_at=int(time.time()))
        created = postgres_db_real.create_service_account(_account("sa-3", "claude-code", "hash-3"))
        assert created["id"] == "sa-3"

        active = postgres_db_real.get_service_account_by_name("claude-code")
        assert active is not None and active["id"] == "sa-3"

    def test_list_pagination_and_revoked_filter(self, postgres_db_real):
        now = int(time.time())
        for i in range(3):
            postgres_db_real.create_service_account(
                _account(f"sa-{i}", f"account-{i}", f"hash-{i}", created_at=now - i)
            )
        postgres_db_real.update_service_account("sa-2", revoked_at=now)

        accounts, total = postgres_db_real.get_service_accounts()
        assert total == 3

        accounts, total = postgres_db_real.get_service_accounts(include_revoked=False)
        assert total == 2
        assert all(account["revoked_at"] is None for account in accounts)

        accounts, _ = postgres_db_real.get_service_accounts(sort_by="name", sort_order="asc")
        assert [account["name"] for account in accounts] == ["account-0", "account-1", "account-2"]

    def test_update_guardrails(self, postgres_db_real):
        postgres_db_real.create_service_account(_account("sa-1", "claude-code", "hash-1"))

        # Immutable columns are rejected before reaching the database
        with pytest.raises(ValueError, match="cannot modify"):
            postgres_db_real.update_service_account("sa-1", token_hash="attacker-hash")
        with pytest.raises(ValueError, match="cannot modify"):
            postgres_db_real.update_service_account("sa-1", name="other", last_used_at=int(time.time()))

        # Empty updates are rejected
        with pytest.raises(ValueError, match="at least one column"):
            postgres_db_real.update_service_account("sa-1")

        # Revocation is one-way
        postgres_db_real.update_service_account("sa-1", revoked_at=int(time.time()))
        with pytest.raises(ValueError, match="one-way"):
            postgres_db_real.update_service_account("sa-1", revoked_at=None)

        # The record survived every rejected update untouched
        account = postgres_db_real.get_service_account("sa-1")
        assert account is not None
        assert account["token_hash"] == "hash-1"
        assert account["name"] == "claude-code"
        assert account["revoked_at"] is not None
