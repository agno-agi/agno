"""Unit tests for the shared service-account schema helpers."""

import pytest

from agno.db.schemas.service_accounts import (
    SERVICE_ACCOUNT_MUTABLE_COLUMNS,
    resolve_service_account_sort_column,
    validate_service_account_update,
)


class TestValidateServiceAccountUpdate:
    def test_mutable_columns_pass(self):
        validate_service_account_update({"last_used_at": 1751000000})
        validate_service_account_update({"revoked_at": 1751000000})
        validate_service_account_update({"last_used_at": 1751000000, "revoked_at": 1751000000})

    def test_empty_update_rejected(self):
        with pytest.raises(ValueError, match="at least one column"):
            validate_service_account_update({})

    @pytest.mark.parametrize(
        "column", ["id", "name", "user_id", "token_hash", "token_prefix", "scopes", "created_at", "created_by"]
    )
    def test_immutable_columns_rejected(self, column):
        with pytest.raises(ValueError, match="cannot modify"):
            validate_service_account_update({column: "new-value"})

    def test_immutable_column_rejected_even_alongside_mutable_one(self):
        with pytest.raises(ValueError, match="cannot modify"):
            validate_service_account_update({"last_used_at": 1751000000, "token_hash": "attacker-hash"})

    def test_unknown_column_rejected(self):
        with pytest.raises(ValueError, match="cannot modify"):
            validate_service_account_update({"no_such_column": 1})

    def test_unrevoke_rejected(self):
        with pytest.raises(ValueError, match="one-way"):
            validate_service_account_update({"revoked_at": None})

    def test_mutable_whitelist_is_minimal(self):
        # The whitelist should only ever grow deliberately: it is exactly what
        # the routers and the token verifier need today.
        assert SERVICE_ACCOUNT_MUTABLE_COLUMNS == frozenset({"last_used_at", "revoked_at"})


class TestResolveServiceAccountSortColumn:
    def test_known_column_passes_through(self):
        assert resolve_service_account_sort_column("name") == "name"

    def test_unknown_column_clamped_to_default(self):
        assert resolve_service_account_sort_column("token_hash") == "created_at"
