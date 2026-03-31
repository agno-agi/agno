"""Unit tests for the generic FilterExpr -> SQLAlchemy converter.

Tests cover:
- All single-field operators (EQ, NEQ, GT, GTE, LT, LTE, CONTAINS, STARTSWITH)
- IN operator
- Logical operators (AND, OR, NOT)
- Column validation (allowed_columns)
- Error handling (invalid filters, unknown operators, invalid fields)
- Complex nested expressions
- TRACE_COLUMNS constant
"""

import pytest
from sqlalchemy import Column, MetaData, String, Table, create_engine, select
from sqlalchemy.types import DateTime, Integer

from agno.db.filter_converter import TRACE_COLUMNS, filter_expr_to_sqlalchemy


@pytest.fixture
def engine():
    """Create an in-memory SQLite engine for testing."""
    return create_engine("sqlite:///:memory:")


@pytest.fixture
def test_table(engine):
    """Create a test table with columns matching TRACE_COLUMNS."""
    metadata = MetaData()
    table = Table(
        "test_traces",
        metadata,
        Column("trace_id", String),
        Column("name", String),
        Column("status", String),
        Column("start_time", DateTime),
        Column("end_time", DateTime),
        Column("duration_ms", Integer),
        Column("run_id", String),
        Column("session_id", String),
        Column("user_id", String),
        Column("agent_id", String),
        Column("team_id", String),
        Column("workflow_id", String),
        Column("created_at", DateTime),
    )
    metadata.create_all(engine)
    return table


class TestTraceColumns:
    """Test TRACE_COLUMNS constant."""

    def test_trace_columns_is_set(self):
        """Test that TRACE_COLUMNS is a set."""
        assert isinstance(TRACE_COLUMNS, set)

    def test_trace_columns_contains_expected_fields(self):
        """Test that TRACE_COLUMNS contains all expected trace fields."""
        expected = {
            "trace_id",
            "name",
            "status",
            "start_time",
            "end_time",
            "duration_ms",
            "run_id",
            "session_id",
            "user_id",
            "agent_id",
            "team_id",
            "workflow_id",
            "created_at",
        }
        assert TRACE_COLUMNS == expected

    def test_trace_columns_count(self):
        """Test that TRACE_COLUMNS has the expected count."""
        assert len(TRACE_COLUMNS) == 13


class TestEQOperator:
    """Test EQ operator conversion."""

    def test_eq_string(self, test_table):
        """Test EQ with string value generates correct SQL."""
        clause = filter_expr_to_sqlalchemy(
            {"op": "EQ", "key": "status", "value": "OK"},
            test_table,
        )
        compiled = str(clause.compile(compile_kwargs={"literal_binds": True}))
        assert "status" in compiled
        assert "OK" in compiled

    def test_eq_integer(self, test_table):
        """Test EQ with integer value."""
        clause = filter_expr_to_sqlalchemy(
            {"op": "EQ", "key": "duration_ms", "value": 100},
            test_table,
        )
        compiled = str(clause.compile(compile_kwargs={"literal_binds": True}))
        assert "duration_ms" in compiled

    def test_eq_with_allowed_columns(self, test_table):
        """Test EQ with valid column in allowed_columns."""
        clause = filter_expr_to_sqlalchemy(
            {"op": "EQ", "key": "status", "value": "OK"},
            test_table,
            allowed_columns=TRACE_COLUMNS,
        )
        assert clause is not None

    def test_eq_invalid_column(self, test_table):
        """Test EQ with invalid column raises ValueError."""
        with pytest.raises(ValueError, match="Invalid filter field"):
            filter_expr_to_sqlalchemy(
                {"op": "EQ", "key": "nonexistent_column", "value": "OK"},
                test_table,
                allowed_columns=TRACE_COLUMNS,
            )


class TestNEQOperator:
    """Test NEQ operator conversion."""

    def test_neq_string(self, test_table):
        """Test NEQ with string value generates != SQL."""
        clause = filter_expr_to_sqlalchemy(
            {"op": "NEQ", "key": "status", "value": "ERROR"},
            test_table,
        )
        compiled = str(clause.compile(compile_kwargs={"literal_binds": True}))
        assert "status" in compiled
        assert "!=" in compiled or "<>" in compiled

    def test_neq_with_allowed_columns(self, test_table):
        """Test NEQ respects allowed_columns validation."""
        with pytest.raises(ValueError, match="Invalid filter field"):
            filter_expr_to_sqlalchemy(
                {"op": "NEQ", "key": "invalid_field", "value": "x"},
                test_table,
                allowed_columns=TRACE_COLUMNS,
            )


class TestGTOperator:
    """Test GT operator conversion."""

    def test_gt_integer(self, test_table):
        """Test GT with integer value generates > SQL."""
        clause = filter_expr_to_sqlalchemy(
            {"op": "GT", "key": "duration_ms", "value": 1000},
            test_table,
        )
        compiled = str(clause.compile(compile_kwargs={"literal_binds": True}))
        assert "duration_ms" in compiled
        assert ">" in compiled


class TestGTEOperator:
    """Test GTE operator conversion."""

    def test_gte_integer(self, test_table):
        """Test GTE with integer value generates >= SQL."""
        clause = filter_expr_to_sqlalchemy(
            {"op": "GTE", "key": "duration_ms", "value": 100},
            test_table,
        )
        compiled = str(clause.compile(compile_kwargs={"literal_binds": True}))
        assert "duration_ms" in compiled
        assert ">=" in compiled


class TestLTOperator:
    """Test LT operator conversion."""

    def test_lt_integer(self, test_table):
        """Test LT with integer value generates < SQL."""
        clause = filter_expr_to_sqlalchemy(
            {"op": "LT", "key": "duration_ms", "value": 5000},
            test_table,
        )
        compiled = str(clause.compile(compile_kwargs={"literal_binds": True}))
        assert "duration_ms" in compiled
        assert "<" in compiled


class TestLTEOperator:
    """Test LTE operator conversion."""

    def test_lte_integer(self, test_table):
        """Test LTE with integer value generates <= SQL."""
        clause = filter_expr_to_sqlalchemy(
            {"op": "LTE", "key": "duration_ms", "value": 5000},
            test_table,
        )
        compiled = str(clause.compile(compile_kwargs={"literal_binds": True}))
        assert "duration_ms" in compiled
        assert "<=" in compiled


class TestINOperator:
    """Test IN operator conversion."""

    def test_in_strings(self, test_table):
        """Test IN with list of strings generates IN clause."""
        clause = filter_expr_to_sqlalchemy(
            {"op": "IN", "key": "status", "values": ["OK", "ERROR"]},
            test_table,
        )
        compiled = str(clause.compile(compile_kwargs={"literal_binds": True}))
        assert "status" in compiled
        assert "IN" in compiled

    def test_in_with_single_value(self, test_table):
        """Test IN with single value."""
        clause = filter_expr_to_sqlalchemy(
            {"op": "IN", "key": "agent_id", "values": ["stock_agent"]},
            test_table,
        )
        compiled = str(clause.compile(compile_kwargs={"literal_binds": True}))
        assert "agent_id" in compiled

    def test_in_invalid_column(self, test_table):
        """Test IN with invalid column raises ValueError."""
        with pytest.raises(ValueError, match="Invalid filter field"):
            filter_expr_to_sqlalchemy(
                {"op": "IN", "key": "bad_column", "values": ["a", "b"]},
                test_table,
                allowed_columns=TRACE_COLUMNS,
            )

    def test_in_missing_values(self, test_table):
        """Test IN without values raises ValueError."""
        with pytest.raises(ValueError, match="IN filter requires"):
            filter_expr_to_sqlalchemy(
                {"op": "IN", "key": "status"},
                test_table,
            )

    def test_in_missing_key(self, test_table):
        """Test IN without key raises ValueError."""
        with pytest.raises(ValueError, match="IN filter requires"):
            filter_expr_to_sqlalchemy(
                {"op": "IN", "values": ["OK"]},
                test_table,
            )


class TestCONTAINSOperator:
    """Test CONTAINS operator conversion (case-insensitive substring)."""

    def test_contains_string(self, test_table):
        """Test CONTAINS generates case-insensitive LIKE clause."""
        clause = filter_expr_to_sqlalchemy(
            {"op": "CONTAINS", "key": "user_id", "value": "admin"},
            test_table,
        )
        compiled = str(clause.compile(compile_kwargs={"literal_binds": True}))
        assert "user_id" in compiled.lower()
        # Should use lower() for case-insensitive matching
        assert "lower" in compiled.lower()

    def test_contains_with_allowed_columns(self, test_table):
        """Test CONTAINS with valid column passes validation."""
        clause = filter_expr_to_sqlalchemy(
            {"op": "CONTAINS", "key": "name", "value": "agent"},
            test_table,
            allowed_columns=TRACE_COLUMNS,
        )
        assert clause is not None

    def test_contains_invalid_column(self, test_table):
        """Test CONTAINS with invalid column raises ValueError."""
        with pytest.raises(ValueError, match="Invalid filter field"):
            filter_expr_to_sqlalchemy(
                {"op": "CONTAINS", "key": "invalid_col", "value": "test"},
                test_table,
                allowed_columns=TRACE_COLUMNS,
            )


class TestSTARTSWITHOperator:
    """Test STARTSWITH operator conversion."""

    def test_startswith_string(self, test_table):
        """Test STARTSWITH generates prefix match clause."""
        clause = filter_expr_to_sqlalchemy(
            {"op": "STARTSWITH", "key": "name", "value": "Agent"},
            test_table,
        )
        compiled = str(clause.compile(compile_kwargs={"literal_binds": True}))
        assert "name" in compiled

    def test_startswith_with_allowed_columns(self, test_table):
        """Test STARTSWITH with valid column passes validation."""
        clause = filter_expr_to_sqlalchemy(
            {"op": "STARTSWITH", "key": "agent_id", "value": "stock_"},
            test_table,
            allowed_columns=TRACE_COLUMNS,
        )
        assert clause is not None


class TestANDOperator:
    """Test AND logical operator conversion."""

    def test_and_two_conditions(self, test_table):
        """Test AND with two conditions generates AND SQL."""
        clause = filter_expr_to_sqlalchemy(
            {
                "op": "AND",
                "conditions": [
                    {"op": "EQ", "key": "status", "value": "OK"},
                    {"op": "GT", "key": "duration_ms", "value": 100},
                ],
            },
            test_table,
        )
        compiled = str(clause.compile(compile_kwargs={"literal_binds": True}))
        assert "AND" in compiled
        assert "status" in compiled
        assert "duration_ms" in compiled

    def test_and_multiple_conditions(self, test_table):
        """Test AND with three conditions."""
        clause = filter_expr_to_sqlalchemy(
            {
                "op": "AND",
                "conditions": [
                    {"op": "EQ", "key": "status", "value": "OK"},
                    {"op": "GTE", "key": "duration_ms", "value": 100},
                    {"op": "LTE", "key": "duration_ms", "value": 5000},
                ],
            },
            test_table,
            allowed_columns=TRACE_COLUMNS,
        )
        compiled = str(clause.compile(compile_kwargs={"literal_binds": True}))
        assert "AND" in compiled

    def test_and_missing_conditions(self, test_table):
        """Test AND without conditions raises ValueError."""
        with pytest.raises(ValueError, match="AND filter requires"):
            filter_expr_to_sqlalchemy(
                {"op": "AND"},
                test_table,
            )

    def test_and_empty_conditions(self, test_table):
        """Test AND with empty conditions list raises ValueError."""
        with pytest.raises(ValueError, match="AND filter requires"):
            filter_expr_to_sqlalchemy(
                {"op": "AND", "conditions": []},
                test_table,
            )


class TestOROperator:
    """Test OR logical operator conversion."""

    def test_or_two_conditions(self, test_table):
        """Test OR with two conditions generates OR SQL."""
        clause = filter_expr_to_sqlalchemy(
            {
                "op": "OR",
                "conditions": [
                    {"op": "EQ", "key": "status", "value": "OK"},
                    {"op": "EQ", "key": "status", "value": "ERROR"},
                ],
            },
            test_table,
        )
        compiled = str(clause.compile(compile_kwargs={"literal_binds": True}))
        assert "OR" in compiled

    def test_or_missing_conditions(self, test_table):
        """Test OR without conditions raises ValueError."""
        with pytest.raises(ValueError, match="OR filter requires"):
            filter_expr_to_sqlalchemy(
                {"op": "OR"},
                test_table,
            )


class TestNOTOperator:
    """Test NOT logical operator conversion."""

    def test_not_eq(self, test_table):
        """Test NOT with EQ condition generates negated SQL."""
        clause = filter_expr_to_sqlalchemy(
            {
                "op": "NOT",
                "condition": {"op": "EQ", "key": "status", "value": "ERROR"},
            },
            test_table,
        )
        compiled = str(clause.compile(compile_kwargs={"literal_binds": True}))
        # SQLAlchemy may optimize NOT(x = y) to x != y
        assert "status" in compiled
        assert "NOT" in compiled or "!=" in compiled or "<>" in compiled

    def test_not_in(self, test_table):
        """Test NOT with IN condition."""
        clause = filter_expr_to_sqlalchemy(
            {
                "op": "NOT",
                "condition": {"op": "IN", "key": "status", "values": ["ERROR"]},
            },
            test_table,
        )
        compiled = str(clause.compile(compile_kwargs={"literal_binds": True}))
        assert "NOT" in compiled

    def test_not_missing_condition(self, test_table):
        """Test NOT without condition raises ValueError."""
        with pytest.raises(ValueError, match="NOT filter requires"):
            filter_expr_to_sqlalchemy(
                {"op": "NOT"},
                test_table,
            )


class TestComplexExpressions:
    """Test complex nested filter expressions."""

    def test_and_or_nested(self, test_table):
        """Test nested AND(OR(...), EQ(...)) expression."""
        clause = filter_expr_to_sqlalchemy(
            {
                "op": "AND",
                "conditions": [
                    {
                        "op": "OR",
                        "conditions": [
                            {"op": "EQ", "key": "agent_id", "value": "stock_agent"},
                            {"op": "EQ", "key": "agent_id", "value": "weather_agent"},
                        ],
                    },
                    {"op": "EQ", "key": "status", "value": "OK"},
                ],
            },
            test_table,
            allowed_columns=TRACE_COLUMNS,
        )
        compiled = str(clause.compile(compile_kwargs={"literal_binds": True}))
        assert "AND" in compiled
        assert "OR" in compiled

    def test_complex_trace_search(self, test_table):
        """Test complex trace search expression matching FE filter bar."""
        clause = filter_expr_to_sqlalchemy(
            {
                "op": "AND",
                "conditions": [
                    {"op": "EQ", "key": "status", "value": "OK"},
                    {"op": "CONTAINS", "key": "user_id", "value": "admin"},
                    {"op": "GTE", "key": "duration_ms", "value": 100},
                    {"op": "LTE", "key": "duration_ms", "value": 5000},
                ],
            },
            test_table,
            allowed_columns=TRACE_COLUMNS,
        )
        assert clause is not None

    def test_deeply_nested_not(self, test_table):
        """Test deeply nested NOT expression."""
        clause = filter_expr_to_sqlalchemy(
            {
                "op": "AND",
                "conditions": [
                    {"op": "EQ", "key": "status", "value": "OK"},
                    {
                        "op": "NOT",
                        "condition": {
                            "op": "OR",
                            "conditions": [
                                {"op": "EQ", "key": "agent_id", "value": "test_agent"},
                                {"op": "CONTAINS", "key": "name", "value": "debug"},
                            ],
                        },
                    },
                ],
            },
            test_table,
            allowed_columns=TRACE_COLUMNS,
        )
        compiled = str(clause.compile(compile_kwargs={"literal_binds": True}))
        assert "AND" in compiled
        assert "NOT" in compiled

    def test_or_of_ands(self, test_table):
        """Test OR of two AND conditions (common FE pattern)."""
        clause = filter_expr_to_sqlalchemy(
            {
                "op": "OR",
                "conditions": [
                    {
                        "op": "AND",
                        "conditions": [
                            {"op": "EQ", "key": "status", "value": "OK"},
                            {"op": "STARTSWITH", "key": "agent_id", "value": "stock"},
                        ],
                    },
                    {
                        "op": "AND",
                        "conditions": [
                            {"op": "EQ", "key": "status", "value": "ERROR"},
                            {"op": "GT", "key": "duration_ms", "value": 5000},
                        ],
                    },
                ],
            },
            test_table,
            allowed_columns=TRACE_COLUMNS,
        )
        compiled = str(clause.compile(compile_kwargs={"literal_binds": True}))
        assert "OR" in compiled


class TestErrorHandling:
    """Test error handling for invalid inputs."""

    def test_non_dict_input(self, test_table):
        """Test that non-dict input raises ValueError."""
        with pytest.raises(ValueError, match="Invalid filter"):
            filter_expr_to_sqlalchemy("not a dict", test_table)

    def test_missing_op_key(self, test_table):
        """Test that missing 'op' key raises ValueError."""
        with pytest.raises(ValueError, match="Invalid filter"):
            filter_expr_to_sqlalchemy({"key": "status", "value": "OK"}, test_table)

    def test_unknown_operator(self, test_table):
        """Test that unknown operator raises ValueError."""
        with pytest.raises(ValueError, match="Unknown filter operator"):
            filter_expr_to_sqlalchemy(
                {"op": "BETWEEN", "key": "age", "value": 10},
                test_table,
            )

    def test_eq_missing_key(self, test_table):
        """Test EQ without key raises ValueError."""
        with pytest.raises(ValueError, match="requires 'key' and 'value'"):
            filter_expr_to_sqlalchemy(
                {"op": "EQ", "value": "OK"},
                test_table,
            )

    def test_eq_missing_value(self, test_table):
        """Test EQ without value raises ValueError."""
        with pytest.raises(ValueError, match="requires 'key' and 'value'"):
            filter_expr_to_sqlalchemy(
                {"op": "EQ", "key": "status"},
                test_table,
            )

    def test_list_input(self, test_table):
        """Test that list input raises ValueError."""
        with pytest.raises(ValueError, match="Invalid filter"):
            filter_expr_to_sqlalchemy([{"op": "EQ"}], test_table)

    def test_none_input(self, test_table):
        """Test that None input raises ValueError."""
        with pytest.raises(ValueError, match="Invalid filter"):
            filter_expr_to_sqlalchemy(None, test_table)

    def test_invalid_column_in_nested(self, test_table):
        """Test invalid column inside nested expression raises ValueError."""
        with pytest.raises(ValueError, match="Invalid filter field"):
            filter_expr_to_sqlalchemy(
                {
                    "op": "AND",
                    "conditions": [
                        {"op": "EQ", "key": "status", "value": "OK"},
                        {"op": "EQ", "key": "invalid_field", "value": "bad"},
                    ],
                },
                test_table,
                allowed_columns=TRACE_COLUMNS,
            )


class TestColumnValidation:
    """Test column validation behavior."""

    def test_no_validation_when_allowed_columns_none(self, test_table):
        """Test that any column is accepted when allowed_columns is None."""
        # This should not raise even though 'anything' is not a real column
        # (it would fail at query execution, not at filter building)
        # Note: SQLAlchemy will raise KeyError if column doesn't exist on table
        # So we test with a column that exists on the table
        clause = filter_expr_to_sqlalchemy(
            {"op": "EQ", "key": "status", "value": "OK"},
            test_table,
            allowed_columns=None,
        )
        assert clause is not None

    def test_validation_with_empty_allowed_columns(self, test_table):
        """Test behavior with empty allowed_columns set (no validation since empty set is falsy)."""
        clause = filter_expr_to_sqlalchemy(
            {"op": "EQ", "key": "status", "value": "OK"},
            test_table,
            allowed_columns=set(),
        )
        assert clause is not None

    def test_all_trace_columns_pass_validation(self, test_table):
        """Test that all TRACE_COLUMNS pass validation."""
        for col in TRACE_COLUMNS:
            clause = filter_expr_to_sqlalchemy(
                {"op": "EQ", "key": col, "value": "test"},
                test_table,
                allowed_columns=TRACE_COLUMNS,
            )
            assert clause is not None, f"Column '{col}' should pass validation"


class TestSQLExecution:
    """Test that generated SQL can be executed against a real SQLite database."""

    def test_eq_execution(self, engine, test_table):
        """Test EQ filter can be compiled into an executable SELECT statement."""
        clause = filter_expr_to_sqlalchemy(
            {"op": "EQ", "key": "status", "value": "OK"},
            test_table,
        )
        stmt = select(test_table).where(clause)
        with engine.connect() as conn:
            result = conn.execute(stmt)
            rows = result.fetchall()
            assert isinstance(rows, list)

    def test_neq_execution(self, engine, test_table):
        """Test NEQ filter can be executed."""
        clause = filter_expr_to_sqlalchemy(
            {"op": "NEQ", "key": "status", "value": "ERROR"},
            test_table,
        )
        stmt = select(test_table).where(clause)
        with engine.connect() as conn:
            result = conn.execute(stmt)
            assert result is not None

    def test_contains_execution(self, engine, test_table):
        """Test CONTAINS filter can be executed (case-insensitive)."""
        clause = filter_expr_to_sqlalchemy(
            {"op": "CONTAINS", "key": "user_id", "value": "admin"},
            test_table,
        )
        stmt = select(test_table).where(clause)
        with engine.connect() as conn:
            result = conn.execute(stmt)
            assert result is not None

    def test_startswith_execution(self, engine, test_table):
        """Test STARTSWITH filter can be executed."""
        clause = filter_expr_to_sqlalchemy(
            {"op": "STARTSWITH", "key": "name", "value": "Agent"},
            test_table,
        )
        stmt = select(test_table).where(clause)
        with engine.connect() as conn:
            result = conn.execute(stmt)
            assert result is not None

    def test_complex_filter_execution(self, engine, test_table):
        """Test complex filter can be compiled and executed."""
        clause = filter_expr_to_sqlalchemy(
            {
                "op": "AND",
                "conditions": [
                    {"op": "EQ", "key": "status", "value": "OK"},
                    {"op": "CONTAINS", "key": "user_id", "value": "user"},
                    {"op": "GTE", "key": "duration_ms", "value": 100},
                    {"op": "LTE", "key": "duration_ms", "value": 5000},
                ],
            },
            test_table,
            allowed_columns=TRACE_COLUMNS,
        )
        stmt = select(test_table).where(clause)
        with engine.connect() as conn:
            result = conn.execute(stmt)
            rows = result.fetchall()
            assert isinstance(rows, list)

    def test_in_execution(self, engine, test_table):
        """Test IN filter can be executed."""
        clause = filter_expr_to_sqlalchemy(
            {"op": "IN", "key": "status", "values": ["OK", "ERROR"]},
            test_table,
        )
        stmt = select(test_table).where(clause)
        with engine.connect() as conn:
            result = conn.execute(stmt)
            assert result is not None

    def test_not_execution(self, engine, test_table):
        """Test NOT filter can be executed."""
        clause = filter_expr_to_sqlalchemy(
            {
                "op": "NOT",
                "condition": {"op": "EQ", "key": "status", "value": "ERROR"},
            },
            test_table,
        )
        stmt = select(test_table).where(clause)
        with engine.connect() as conn:
            result = conn.execute(stmt)
            assert result is not None

    def test_or_execution(self, engine, test_table):
        """Test OR filter can be executed."""
        clause = filter_expr_to_sqlalchemy(
            {
                "op": "OR",
                "conditions": [
                    {"op": "EQ", "key": "status", "value": "OK"},
                    {"op": "EQ", "key": "status", "value": "ERROR"},
                ],
            },
            test_table,
        )
        stmt = select(test_table).where(clause)
        with engine.connect() as conn:
            result = conn.execute(stmt)
            assert result is not None


class TestSQLWithData:
    """Test filter execution against SQLite with actual inserted data."""

    @pytest.fixture
    def populated_table(self, engine, test_table):
        """Insert test data and return (engine, table)."""
        from datetime import datetime, timezone

        with engine.connect() as conn:
            conn.execute(
                test_table.insert(),
                [
                    {
                        "trace_id": "t1",
                        "name": "Agent.run",
                        "status": "OK",
                        "start_time": datetime(2025, 1, 1, tzinfo=timezone.utc),
                        "end_time": datetime(2025, 1, 1, 0, 0, 1, tzinfo=timezone.utc),
                        "duration_ms": 1000,
                        "run_id": "r1",
                        "session_id": "s1",
                        "user_id": "admin_user",
                        "agent_id": "stock_agent",
                        "team_id": None,
                        "workflow_id": None,
                        "created_at": datetime(2025, 1, 1, tzinfo=timezone.utc),
                    },
                    {
                        "trace_id": "t2",
                        "name": "Team.run",
                        "status": "ERROR",
                        "start_time": datetime(2025, 1, 2, tzinfo=timezone.utc),
                        "end_time": datetime(2025, 1, 2, 0, 0, 5, tzinfo=timezone.utc),
                        "duration_ms": 5000,
                        "run_id": "r2",
                        "session_id": "s1",
                        "user_id": "regular_user",
                        "agent_id": "weather_agent",
                        "team_id": "team1",
                        "workflow_id": None,
                        "created_at": datetime(2025, 1, 2, tzinfo=timezone.utc),
                    },
                    {
                        "trace_id": "t3",
                        "name": "Agent.run",
                        "status": "OK",
                        "start_time": datetime(2025, 1, 3, tzinfo=timezone.utc),
                        "end_time": datetime(2025, 1, 3, 0, 0, 2, tzinfo=timezone.utc),
                        "duration_ms": 200,
                        "run_id": "r3",
                        "session_id": "s2",
                        "user_id": "admin_user2",
                        "agent_id": "stock_agent",
                        "team_id": None,
                        "workflow_id": "wf1",
                        "created_at": datetime(2025, 1, 3, tzinfo=timezone.utc),
                    },
                ],
            )
            conn.commit()
        return engine, test_table

    def test_eq_filters_correctly(self, populated_table):
        """Test EQ returns only matching rows."""
        engine, table = populated_table
        clause = filter_expr_to_sqlalchemy(
            {"op": "EQ", "key": "status", "value": "OK"},
            table,
        )
        with engine.connect() as conn:
            rows = conn.execute(select(table).where(clause)).fetchall()
            assert len(rows) == 2
            assert all(row.status == "OK" for row in rows)

    def test_neq_filters_correctly(self, populated_table):
        """Test NEQ excludes matching rows."""
        engine, table = populated_table
        clause = filter_expr_to_sqlalchemy(
            {"op": "NEQ", "key": "status", "value": "ERROR"},
            table,
        )
        with engine.connect() as conn:
            rows = conn.execute(select(table).where(clause)).fetchall()
            assert len(rows) == 2
            assert all(row.status != "ERROR" for row in rows)

    def test_gt_filters_correctly(self, populated_table):
        """Test GT returns rows with value > threshold."""
        engine, table = populated_table
        clause = filter_expr_to_sqlalchemy(
            {"op": "GT", "key": "duration_ms", "value": 1000},
            table,
        )
        with engine.connect() as conn:
            rows = conn.execute(select(table).where(clause)).fetchall()
            assert len(rows) == 1
            assert rows[0].duration_ms == 5000

    def test_gte_filters_correctly(self, populated_table):
        """Test GTE returns rows with value >= threshold."""
        engine, table = populated_table
        clause = filter_expr_to_sqlalchemy(
            {"op": "GTE", "key": "duration_ms", "value": 1000},
            table,
        )
        with engine.connect() as conn:
            rows = conn.execute(select(table).where(clause)).fetchall()
            assert len(rows) == 2

    def test_lt_filters_correctly(self, populated_table):
        """Test LT returns rows with value < threshold."""
        engine, table = populated_table
        clause = filter_expr_to_sqlalchemy(
            {"op": "LT", "key": "duration_ms", "value": 1000},
            table,
        )
        with engine.connect() as conn:
            rows = conn.execute(select(table).where(clause)).fetchall()
            assert len(rows) == 1
            assert rows[0].duration_ms == 200

    def test_lte_filters_correctly(self, populated_table):
        """Test LTE returns rows with value <= threshold."""
        engine, table = populated_table
        clause = filter_expr_to_sqlalchemy(
            {"op": "LTE", "key": "duration_ms", "value": 1000},
            table,
        )
        with engine.connect() as conn:
            rows = conn.execute(select(table).where(clause)).fetchall()
            assert len(rows) == 2

    def test_in_filters_correctly(self, populated_table):
        """Test IN returns matching rows."""
        engine, table = populated_table
        clause = filter_expr_to_sqlalchemy(
            {"op": "IN", "key": "agent_id", "values": ["stock_agent"]},
            table,
        )
        with engine.connect() as conn:
            rows = conn.execute(select(table).where(clause)).fetchall()
            assert len(rows) == 2
            assert all(row.agent_id == "stock_agent" for row in rows)

    def test_contains_filters_correctly(self, populated_table):
        """Test CONTAINS returns rows with matching substring (case-insensitive)."""
        engine, table = populated_table
        clause = filter_expr_to_sqlalchemy(
            {"op": "CONTAINS", "key": "user_id", "value": "admin"},
            table,
        )
        with engine.connect() as conn:
            rows = conn.execute(select(table).where(clause)).fetchall()
            assert len(rows) == 2
            assert all("admin" in row.user_id.lower() for row in rows)

    def test_contains_case_insensitive(self, populated_table):
        """Test CONTAINS is case-insensitive."""
        engine, table = populated_table
        clause = filter_expr_to_sqlalchemy(
            {"op": "CONTAINS", "key": "user_id", "value": "ADMIN"},
            table,
        )
        with engine.connect() as conn:
            rows = conn.execute(select(table).where(clause)).fetchall()
            assert len(rows) == 2

    def test_startswith_filters_correctly(self, populated_table):
        """Test STARTSWITH returns rows with matching prefix."""
        engine, table = populated_table
        clause = filter_expr_to_sqlalchemy(
            {"op": "STARTSWITH", "key": "name", "value": "Agent"},
            table,
        )
        with engine.connect() as conn:
            rows = conn.execute(select(table).where(clause)).fetchall()
            assert len(rows) == 2
            assert all(row.name.startswith("Agent") for row in rows)

    def test_and_compound_filter(self, populated_table):
        """Test AND compound filter matches expected rows."""
        engine, table = populated_table
        clause = filter_expr_to_sqlalchemy(
            {
                "op": "AND",
                "conditions": [
                    {"op": "EQ", "key": "status", "value": "OK"},
                    {"op": "CONTAINS", "key": "user_id", "value": "admin"},
                ],
            },
            table,
        )
        with engine.connect() as conn:
            rows = conn.execute(select(table).where(clause)).fetchall()
            assert len(rows) == 2
            for row in rows:
                assert row.status == "OK"
                assert "admin" in row.user_id.lower()

    def test_or_compound_filter(self, populated_table):
        """Test OR compound filter matches expected rows."""
        engine, table = populated_table
        clause = filter_expr_to_sqlalchemy(
            {
                "op": "OR",
                "conditions": [
                    {"op": "EQ", "key": "status", "value": "ERROR"},
                    {"op": "EQ", "key": "agent_id", "value": "stock_agent"},
                ],
            },
            table,
        )
        with engine.connect() as conn:
            rows = conn.execute(select(table).where(clause)).fetchall()
            assert len(rows) == 3  # t1 (stock_agent), t2 (ERROR), t3 (stock_agent)

    def test_not_filter(self, populated_table):
        """Test NOT filter excludes matching rows."""
        engine, table = populated_table
        clause = filter_expr_to_sqlalchemy(
            {
                "op": "NOT",
                "condition": {"op": "EQ", "key": "status", "value": "ERROR"},
            },
            table,
        )
        with engine.connect() as conn:
            rows = conn.execute(select(table).where(clause)).fetchall()
            assert len(rows) == 2
            assert all(row.status != "ERROR" for row in rows)

    def test_complex_search_query(self, populated_table):
        """Test complex search query matching FE advanced filter bar."""
        engine, table = populated_table
        # (status=OK AND agent_id=stock_agent) OR (status=ERROR AND duration_ms>1000)
        clause = filter_expr_to_sqlalchemy(
            {
                "op": "OR",
                "conditions": [
                    {
                        "op": "AND",
                        "conditions": [
                            {"op": "EQ", "key": "status", "value": "OK"},
                            {"op": "EQ", "key": "agent_id", "value": "stock_agent"},
                        ],
                    },
                    {
                        "op": "AND",
                        "conditions": [
                            {"op": "EQ", "key": "status", "value": "ERROR"},
                            {"op": "GT", "key": "duration_ms", "value": 1000},
                        ],
                    },
                ],
            },
            table,
            allowed_columns=TRACE_COLUMNS,
        )
        with engine.connect() as conn:
            rows = conn.execute(select(table).where(clause)).fetchall()
            assert len(rows) == 3  # t1 (OK, stock_agent), t2 (ERROR, 5000ms), t3 (OK, stock_agent)

    def test_range_query(self, populated_table):
        """Test range query with GTE and LTE."""
        engine, table = populated_table
        clause = filter_expr_to_sqlalchemy(
            {
                "op": "AND",
                "conditions": [
                    {"op": "GTE", "key": "duration_ms", "value": 200},
                    {"op": "LTE", "key": "duration_ms", "value": 1000},
                ],
            },
            table,
        )
        with engine.connect() as conn:
            rows = conn.execute(select(table).where(clause)).fetchall()
            assert len(rows) == 2  # t1 (1000ms), t3 (200ms)

    def test_not_in_filter(self, populated_table):
        """Test NOT(IN(...)) filter."""
        engine, table = populated_table
        clause = filter_expr_to_sqlalchemy(
            {
                "op": "NOT",
                "condition": {
                    "op": "IN",
                    "key": "agent_id",
                    "values": ["stock_agent"],
                },
            },
            table,
        )
        with engine.connect() as conn:
            rows = conn.execute(select(table).where(clause)).fetchall()
            assert len(rows) == 1
            assert rows[0].agent_id == "weather_agent"
