"""Boolean values in the FilterExpr DSL must compile to JSON's lowercase booleans.

Postgres renders a jsonb boolean with `->>` as lowercase `true`/`false`, but
 `_dsl_to_sqlalchemy` stringified the criterion with str(), so `EQ("urgent", True)`
compiled to `(meta_data ->> 'urgent') = 'True'` — a comparison against the stored
value that can never hold. The same applied to every value inside IN().

The DSL itself keeps native Python values (`agno.filters.EQ("urgent", True)` is the
documented example), and other backends render it correctly — Milvus lowercases the
same value — so the mismatch is in this compiler.

String and number criteria are covered as controls: they must be byte-identical
before and after the fix.
"""

import uuid
from unittest.mock import MagicMock

import pytest
from sqlalchemy.dialects import postgresql
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.engine import URL, Engine

from agno.filters import AND, EQ, IN, NOT, OR
from agno.vectordb.pgvector import PgVector

TEST_TABLE = f"test_vectors_filter_types_{uuid.uuid4().hex[:8]}"
TEST_SCHEMA = "test_schema"


@pytest.fixture
def pgvector(mock_embedder):
    """Real PgVector with a mocked engine, keeping the real SQLAlchemy table.

    The table has to stay real: this suite compiles expressions to SQL text, which
    is what the Postgres server would actually receive.
    """
    engine = MagicMock(spec=Engine)
    url = MagicMock(spec=URL)
    url.get_backend_name.return_value = "postgresql"
    engine.url = url
    engine.inspect = MagicMock(return_value=MagicMock())
    return PgVector(table_name=TEST_TABLE, schema=TEST_SCHEMA, db_engine=engine, embedder=mock_embedder)


def compile_sql(db, filter_expr) -> str:
    expr = db._dsl_to_sqlalchemy(filter_expr.to_dict(), db.table)
    return str(expr.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))


def test_eq_true_compiles_to_json_true(pgvector):
    """Documented example: EQ("urgent", True) must compare against 'true'."""
    sql = compile_sql(pgvector, EQ("urgent", True))
    assert "= 'true'" in sql, f"expected the jsonb rendering of true, got: {sql}"
    assert "'True'" not in sql, f"str(True) leaked into the comparison: {sql}"


def test_eq_false_compiles_to_json_false(pgvector):
    sql = compile_sql(pgvector, EQ("archived", False))
    assert "= 'false'" in sql, f"expected the jsonb rendering of false, got: {sql}"
    assert "'False'" not in sql


def test_in_compiles_each_boolean(pgvector):
    sql = compile_sql(pgvector, IN("flag", [True, False]))
    assert "'true'" in sql, f"missing true literal: {sql}"
    assert "'false'" in sql, f"missing false literal: {sql}"
    assert "'True'" not in sql and "'False'" not in sql, f"str() leaked in: {sql}"


def test_boolean_inside_logical_operators(pgvector):
    expr = AND(EQ("category", "news"), OR(EQ("urgent", True), NOT(EQ("archived", False))))
    sql = compile_sql(pgvector, expr)
    assert "'True'" not in sql and "'False'" not in sql, f"str() leaked into nested condition: {sql}"
    assert "'true'" in sql and "'false'" in sql


def test_string_criterion_is_unchanged(pgvector):
    """Control: strings must compile exactly as they did before the fix."""
    sql = compile_sql(pgvector, EQ("cuisine", "Thai"))
    assert "= 'Thai'" in sql, f"string handling regressed: {sql}"


def test_number_criterion_is_unchanged(pgvector):
    """Control: numbers are still stringified, because ->> yields text."""
    sql = compile_sql(pgvector, EQ("views", 1000))
    assert "= '1000'" in sql, f"number handling regressed: {sql}"


def test_none_criterion_is_unchanged(pgvector):
    """Control: None keeps the pre-existing rendering (out of scope for this fix)."""
    sql = compile_sql(pgvector, EQ("section", None))
    assert "= 'None'" in sql, f"None handling changed unexpectedly: {sql}"


def test_stored_jsonb_writes_booleans_in_lowercase():
    """Why the comparison must be lowercase: the bytes sent for the metadata
    column carry `true`, and `->>` hands back that same text.
    """
    payload = JSONB().bind_processor(postgresql.dialect())({"urgent": True, "archived": False})
    text = payload if isinstance(payload, str) else payload.decode("utf-8")
    assert '"urgent": true' in text, f"expected jsonb text with lowercase true, got: {text}"
    assert '"archived": false' in text, f"expected jsonb text with lowercase false, got: {text}"
