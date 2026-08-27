"""
Unit tests for Clickhouse.delete_by_metadata SQL injection fix.

Tests verify that user-controlled metadata keys/values are passed as
ClickHouse named parameters, not interpolated directly into SQL strings.

Fixes: https://github.com/agno-agi/agno/issues/7866
"""

from unittest.mock import MagicMock, patch

import pytest

from agno.vectordb.clickhouse.clickhousedb import Clickhouse


def _make_db():
    """Build a Clickhouse instance backed by a mocked client."""
    mock_client = MagicMock()
    mock_client.command.return_value = None

    # Supplied explicitly so the constructor does not build a real OpenAIEmbedder.
    mock_embedder = MagicMock()
    mock_embedder.dimensions = 1024

    with patch("clickhouse_connect.get_client", return_value=mock_client):
        return Clickhouse(
            table_name="test_table",
            host="localhost",
            database_name="test_db",
            embedder=mock_embedder,
            client=mock_client,
        )


def _captured_call(db):
    """Return (sql_text, parameters) from the single client.command call."""
    db.client.command.assert_called_once()
    args, kwargs = db.client.command.call_args
    sql_text = args[0] if args else kwargs["query"]
    parameters = kwargs.get("parameters", {})
    return sql_text, parameters


class TestDeleteByMetadataSqlInjection:
    """delete_by_metadata must use parameterised queries, not f-string SQL."""

    def test_string_value_uses_parameter_not_interpolation(self):
        """String values must appear in the parameters dict, not in the SQL."""
        db = _make_db()
        injection = "'; DROP TABLE test_table; --"
        db.delete_by_metadata({"category": injection})

        sql_text, params = _captured_call(db)

        assert injection not in sql_text, f"Injection string leaked into SQL: {sql_text!r}"
        assert injection in params.values(), f"Injection string not found in parameters: {params}"

    def test_tautology_value_is_parameterised(self):
        """The CVE payload must never reach the SQL text."""
        db = _make_db()
        injection = "' OR '1'='1"
        db.delete_by_metadata({"source": injection})

        sql_text, params = _captured_call(db)

        assert injection not in sql_text, f"Tautology payload leaked into SQL: {sql_text!r}"
        assert injection in params.values()
        # The predicate must stay a single bound comparison, not an OR chain.
        assert " OR " not in sql_text.upper()

    def test_key_uses_parameter_not_interpolation(self):
        """Metadata keys must also be parameterised - they are user-controlled."""
        db = _make_db()
        malicious_key = "x') = 1 OR (JSONExtractString(toString(filters), 'y"
        db.delete_by_metadata({malicious_key: "safe_value"})

        sql_text, params = _captured_call(db)

        assert malicious_key not in sql_text, f"Malicious key leaked into SQL: {sql_text!r}"
        assert malicious_key in params.values(), f"Malicious key not found in parameters: {params}"

    def test_numeric_value_uses_parameter(self):
        """Numeric values are passed as Float64 parameters."""
        db = _make_db()
        db.delete_by_metadata({"score": 3.14})

        sql_text, params = _captured_call(db)

        assert "3.14" not in sql_text
        assert 3.14 in params.values()
        assert "Float64" in sql_text

    def test_bool_value_uses_parameter(self):
        """Boolean values are passed as Bool parameters, not inlined literals."""
        db = _make_db()
        db.delete_by_metadata({"active": True})

        sql_text, params = _captured_call(db)

        assert "= true" not in sql_text.lower()
        assert "Bool" in sql_text
        assert True in params.values()

    def test_bool_dispatch_precedes_int(self):
        """bool subclasses int, so it must hit the Bool branch, not Float64."""
        db = _make_db()
        db.delete_by_metadata({"active": False})

        sql_text, params = _captured_call(db)

        assert "JSONExtractBool" in sql_text
        assert "JSONExtractFloat" not in sql_text
        assert False in params.values()

    def test_multiple_conditions_all_parameterised(self):
        """All conditions in a multi-key dict use separate named parameters."""
        db = _make_db()
        db.delete_by_metadata({"env": "prod", "region": "us-east-1"})

        sql_text, params = _captured_call(db)

        # Raw keys and values must NOT appear in SQL.
        for raw in ("prod", "us-east-1", "env", "region"):
            assert raw not in sql_text, f"{raw!r} leaked into SQL: {sql_text!r}"

        values = list(params.values())
        for expected in ("prod", "us-east-1", "env", "region"):
            assert expected in values, f"{expected!r} not found in parameters: {params}"

        assert sql_text.count("JSONExtractString") == 2
        assert " AND " in sql_text

    def test_empty_metadata_returns_false(self):
        """Empty metadata dict returns False without calling client.command."""
        db = _make_db()
        result = db.delete_by_metadata({})
        assert result is False
        db.client.command.assert_not_called()

    @pytest.mark.parametrize(
        "payload",
        [
            "' OR '1'='1",
            "'; DROP TABLE test_table; --",
            "x') = '1' OR ('1",
            "a\\' OR 1=1 --",
            "' UNION SELECT 1 --",
        ],
    )
    def test_injection_payloads_never_reach_sql(self, payload):
        """No known injection payload may appear in the emitted SQL text."""
        db = _make_db()
        db.delete_by_metadata({"source": payload})

        sql_text, params = _captured_call(db)

        assert payload not in sql_text
        assert payload in params.values()
