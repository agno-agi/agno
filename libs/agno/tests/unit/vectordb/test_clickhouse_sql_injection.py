"""
Unit tests for ClickHouseVectorDb.delete_by_metadata SQL injection fix.

Tests verify that user-controlled metadata keys/values are passed as
ClickHouse named parameters, not interpolated directly into SQL strings.

Fixes: https://github.com/agno-agi/agno/issues/7866
"""
from unittest.mock import MagicMock, patch


def _make_db():
    """Build a ClickHouseVectorDb instance with a mocked client."""
    with patch("clickhouse_connect.get_client"):
        from agno.vectordb.clickhouse.clickhousedb import ClickHouseDb

        db = ClickHouseDb(
            table="test_table",
            host="localhost",
            database="test_db",
        )
    db.client = MagicMock()
    db.client.command.return_value = None
    return db


class TestDeleteByMetadataSqlInjection:
    """delete_by_metadata must use parameterised queries, not f-string SQL."""

    def test_string_value_uses_parameter_not_interpolation(self):
        """String values must appear in the parameters dict, not in the SQL."""
        db = _make_db()
        injection = "'; DROP TABLE test_table; --"
        db.delete_by_metadata({"category": injection})

        db.client.command.assert_called_once()
        call_kwargs = db.client.command.call_args

        query = call_kwargs[0][0] if call_kwargs[0] else call_kwargs[1]["query"]
        params = call_kwargs[1].get("parameters", {}) or (
            call_kwargs[0][1] if len(call_kwargs[0]) > 1 else {}
        )

        # The injection string must NOT appear anywhere in the SQL text
        assert injection not in query, (
            f"Injection string leaked into SQL: {query!r}"
        )
        # It must be in the parameters dict instead
        assert injection in params.values(), (
            f"Injection string not found in parameters: {params}"
        )

    def test_key_uses_parameter_not_interpolation(self):
        """Metadata keys must also be parameterised — they are user-controlled."""
        db = _make_db()
        malicious_key = "x') = 1 OR (JSONExtractString(toString(filters), 'y"
        db.delete_by_metadata({malicious_key: "safe_value"})

        db.client.command.assert_called_once()
        call_kwargs = db.client.command.call_args
        query = call_kwargs[0][0] if call_kwargs[0] else call_kwargs[1]["query"]
        params = call_kwargs[1].get("parameters", {}) or (
            call_kwargs[0][1] if len(call_kwargs[0]) > 1 else {}
        )

        assert malicious_key not in query, (
            f"Malicious key leaked into SQL: {query!r}"
        )
        assert malicious_key in params.values(), (
            f"Malicious key not found in parameters: {params}"
        )

    def test_numeric_value_uses_parameter(self):
        """Numeric values are passed as Float64 parameters."""
        db = _make_db()
        db.delete_by_metadata({"score": 3.14})

        call_kwargs = db.client.command.call_args
        query = call_kwargs[0][0] if call_kwargs[0] else call_kwargs[1]["query"]
        params = call_kwargs[1].get("parameters", {}) or (
            call_kwargs[0][1] if len(call_kwargs[0]) > 1 else {}
        )

        assert "3.14" not in query
        assert 3.14 in params.values()

    def test_bool_value_uses_parameter(self):
        """Boolean values are passed as Bool parameters."""
        db = _make_db()
        db.delete_by_metadata({"active": True})

        call_kwargs = db.client.command.call_args
        query = call_kwargs[0][0] if call_kwargs[0] else call_kwargs[1]["query"]
        params = call_kwargs[1].get("parameters", {}) or (
            call_kwargs[0][1] if len(call_kwargs[0]) > 1 else {}
        )

        # "true" / "True" must not be raw-interpolated
        assert "= true" not in query.lower() or "{" in query  # placeholder is in the SQL
        assert True in params.values()

    def test_multiple_conditions_all_parameterised(self):
        """All conditions in a multi-key dict use separate named parameters."""
        db = _make_db()
        db.delete_by_metadata({"env": "prod", "region": "us-east-1"})

        call_kwargs = db.client.command.call_args
        query = call_kwargs[0][0] if call_kwargs[0] else call_kwargs[1]["query"]
        params = call_kwargs[1].get("parameters", {}) or (
            call_kwargs[0][1] if len(call_kwargs[0]) > 1 else {}
        )

        # Raw strings must NOT appear in SQL
        assert "prod" not in query
        assert "us-east-1" not in query
        assert "env" not in query
        assert "region" not in query

        # Both values must be in parameters
        assert "prod" in params.values()
        assert "us-east-1" in params.values()

    def test_empty_metadata_returns_false(self):
        """Empty metadata dict returns False without calling client.command."""
        db = _make_db()
        result = db.delete_by_metadata({})
        assert result is False
        db.client.command.assert_not_called()
