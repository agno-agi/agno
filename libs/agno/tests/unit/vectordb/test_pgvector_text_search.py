"""SQL shape of PgVector's full-text and hybrid search.

Hybrid search must reach rows through the vector and GIN indexes instead of scoring
the whole table, and every to_tsvector must be the expression the GIN index is built on.
"""

from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy.dialects import postgresql
from sqlalchemy.engine import URL, Engine

from agno.vectordb.pgvector import HNSW, PgVector
from agno.vectordb.search import SearchType


@pytest.fixture
def mock_engine():
    engine = MagicMock(spec=Engine)
    engine.url = URL.create(drivername="postgresql+psycopg", username="u", password="p", host="localhost", database="d")
    return engine


@pytest.fixture
def mock_embedder():
    embedder = MagicMock()
    embedder.dimensions = 3
    embedder.get_embedding.return_value = [0.1, 0.2, 0.3]
    return embedder


def _build(mock_engine, mock_embedder, **kwargs) -> PgVector:
    with patch("agno.vectordb.pgvector.pgvector.inspect") as mock_inspect:
        mock_inspect.return_value.has_table.return_value = False
        db = PgVector(table_name="kb", schema="ai", db_engine=mock_engine, embedder=mock_embedder, **kwargs)
    # Owner-column detection hits the database; these searches never scope by user
    db._owner_column_exists = False
    return db


def _capture_session(db: PgVector) -> MagicMock:
    session = MagicMock()
    session.execute.return_value.fetchall.return_value = []
    db.Session = MagicMock()
    db.Session.return_value.__enter__.return_value = session
    return session


def _executed_sql(session: MagicMock) -> list:
    return [
        str(call.args[0].compile(dialect=postgresql.dialect()))
        if hasattr(call.args[0], "compile")
        else str(call.args[0])
        for call in session.execute.call_args_list
    ]


def test_invalid_content_language_rejected(mock_engine, mock_embedder):
    with pytest.raises(ValueError, match="content_language"):
        _build(mock_engine, mock_embedder, content_language="portuguese'); DROP TABLE ai.kb; --")


def test_gin_index_quotes_the_language(mock_engine, mock_embedder):
    db = _build(mock_engine, mock_embedder, content_language="portuguese")
    session = _capture_session(db)

    with patch.object(db, "_index_exists", return_value=False):
        db._create_gin_index()

    (sql,) = _executed_sql(session)
    assert "USING GIN (to_tsvector('portuguese'::regconfig, content))" in sql


def test_hybrid_search_scores_only_index_backed_candidates(mock_engine, mock_embedder):
    db = _build(mock_engine, mock_embedder, search_type=SearchType.hybrid, content_language="portuguese")
    session = _capture_session(db)

    db.hybrid_search("dipirona para dor", limit=5)

    search_sql = _executed_sql(session)[-1]
    assert "WITH vector_candidates AS" in search_sql
    assert "text_candidates AS" in search_sql
    assert "UNION" in search_sql
    # Keyword candidates come from a match the GIN index can serve
    assert "@@" in search_sql
    # Language as a literal, so to_tsvector matches the GIN index expression
    assert "to_tsvector('portuguese'::regconfig, ai.kb.content)" in search_sql
    assert "to_tsvector(%(" not in search_sql


def test_hybrid_search_raises_ef_search_to_cover_the_candidates(mock_engine, mock_embedder):
    db = _build(mock_engine, mock_embedder, search_type=SearchType.hybrid, vector_index=HNSW(ef_search=5))
    session = _capture_session(db)

    db.hybrid_search("dipirona", limit=5)

    assert "SET LOCAL hnsw.ef_search = 20" in _executed_sql(session)


def test_keyword_search_filters_with_the_match_operator(mock_engine, mock_embedder):
    db = _build(mock_engine, mock_embedder, search_type=SearchType.keyword, content_language="portuguese")
    session = _capture_session(db)

    db.keyword_search("dipirona", limit=5)

    search_sql = _executed_sql(session)[-1]
    assert "@@" in search_sql
    assert "to_tsvector('portuguese'::regconfig, ai.kb.content)" in search_sql
