from unittest.mock import MagicMock, patch

import pytest

try:
    import sqlalchemy  # noqa: F401

    HAS_SQLALCHEMY = True
except ImportError:
    HAS_SQLALCHEMY = False

pytestmark = pytest.mark.skipif(not HAS_SQLALCHEMY, reason="sqlalchemy is required for openGauss adapter tests")

if HAS_SQLALCHEMY:
    from agno.vectordb.opengauss import OpenGaussVectorDb, parse_opengauss_version
    from agno.vectordb.opengauss.index import HNSW, Ivfflat
else:

    class OpenGaussVectorDb:  # pragma: no cover
        def get_table(self):
            return None

    class HNSW:  # pragma: no cover
        def __init__(self, **kwargs):
            self.ef_search = kwargs.get("ef_search", 5)

    class Ivfflat:  # pragma: no cover
        def __init__(self, **kwargs):
            self.probes = kwargs.get("probes", 10)

    def parse_opengauss_version(_version_string):  # pragma: no cover
        return None


@patch("agno.vectordb.opengauss.opengauss.scoped_session")
@patch("agno.vectordb.opengauss.opengauss.Vector")
@patch.object(OpenGaussVectorDb, "get_table")
def _build_db(mock_get_table, _mock_vector, _mock_scoped_session, mock_embedder):
    mock_get_table.return_value = MagicMock()
    engine = MagicMock()
    return OpenGaussVectorDb(table_name="test_table", schema="ai", db_engine=engine, embedder=mock_embedder)


def test_set_query_index_runtime_parameters_ivfflat(mock_embedder):
    db = _build_db(mock_embedder=mock_embedder)
    db.vector_index = Ivfflat(probes=11)

    sess = MagicMock()
    db._set_query_index_runtime_parameters(sess)

    assert sess.execute.call_count == 1
    sql_text = str(sess.execute.call_args[0][0])
    assert "SET LOCAL ivfflat_probes = 11" in sql_text


def test_set_query_index_runtime_parameters_hnsw(mock_embedder):
    db = _build_db(mock_embedder=mock_embedder)
    db.vector_index = HNSW(ef_search=55)

    sess = MagicMock()
    db._set_query_index_runtime_parameters(sess)

    assert sess.execute.call_count == 1
    sql_text = str(sess.execute.call_args[0][0])
    assert "SET LOCAL hnsw_ef_search = 55" in sql_text


def test_validate_setting_key_accepts_safe_key():
    assert OpenGaussVectorDb._validate_setting_key("maintenance_work_mem") == "maintenance_work_mem"


def test_validate_setting_key_rejects_unsafe_key():
    with pytest.raises(ValueError):
        OpenGaussVectorDb._validate_setting_key("maintenance_work_mem;drop table x")


def test_sql_setting_value_escapes_string():
    assert OpenGaussVectorDb._sql_setting_value("a'b") == "'a''b'"


def test_sql_setting_value_formats_primitives():
    assert OpenGaussVectorDb._sql_setting_value(10) == "10"
    assert OpenGaussVectorDb._sql_setting_value(True) == "on"


def test_create_ivfflat_index_uses_literal_set_statement(mock_embedder):
    db = _build_db(mock_embedder=mock_embedder)
    db.vector_index = Ivfflat(name="idx_test", lists=32, probes=11, dynamic_lists=False)

    sess = MagicMock()
    db._create_ivfflat_index(sess, "ai.test_table", "vector_cosine_ops")

    assert sess.execute.call_count == 2
    set_sql = str(sess.execute.call_args_list[0][0][0])
    assert "SET ivfflat_probes = 11" in set_sql


@pytest.mark.parametrize(
    "version_string, expected",
    [
        ("(openGauss 1.0.0 build abc) compiled at 2020-06-30", (1, 0, 0)),
        ("openGauss 2.1.0 (Preview)", (2, 1, 0)),
        ("openGauss 3.0.6 (LTS)", (3, 0, 6)),
        ("openGauss 5.1.0 (Preview)", (5, 1, 0)),
        ("openGauss 6.0.0-RC1 build 12345", (6, 0, 0)),
        ("(openGauss-lite 7.0.0-RC3 build deadbeef) compiled at 2026-03-01", (7, 0, 0)),
        ("PostgreSQL 14.9 on x86_64-pc-linux-gnu", None),
    ],
)
def test_parse_opengauss_version(version_string, expected):
    assert parse_opengauss_version(version_string) == expected
