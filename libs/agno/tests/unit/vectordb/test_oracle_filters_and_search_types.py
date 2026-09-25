"""OracleVector's ticket 18 behaviors: numeric filter comparisons, the
supported FilterExpr operator set, hybrid search's weight boundary
conditions, and the actionable error when Oracle Text is unavailable.

Live-server, skip-clean convention (ADR 0009: no Oracle container in public
CI), matching test_oracle_user_isolation.py's own choice of harness for the
same reason: several of these behaviors (numeric JSON comparison, Oracle Text
error codes) are genuine database behaviors a mocked session cannot reproduce.
"""

import uuid

import pytest
from sqlalchemy import create_engine, text

from agno.filters import AND, EQ, GT, IN, LT, NOT, OR, STARTSWITH
from agno.knowledge.document import Document
from agno.vectordb.oracle.oracle import OracleVector

from .conftest import DeterministicEmbedder

DB_URL = "oracle+oracledb://ai:ai@localhost:1523/?service_name=FREEPDB1"


def _server_reachable() -> bool:
    engine = create_engine(DB_URL)
    try:
        with engine.connect() as conn:
            conn.execute(text("select 1 from dual"))
        return True
    except Exception:
        return False
    finally:
        engine.dispose()


@pytest.fixture(scope="module")
def _oracle_server():
    if not _server_reachable():
        pytest.skip(f"Oracle server not reachable at {DB_URL}")


@pytest.fixture
def db(_oracle_server):
    table_name = f"test_filt_{uuid.uuid4().hex[:8]}"
    database = OracleVector(table_name=table_name, db_url=DB_URL, embedder=DeterministicEmbedder())
    database.create()
    database.insert(
        content_hash="h1",
        documents=[
            Document(name="a", content="alpha document", meta_data={"views": 9}),
            Document(name="b", content="beta document", meta_data={"views": 10}),
            Document(name="c", content="gamma document", meta_data={"views": 100}),
        ],
    )
    yield database
    database.drop()


class TestNumericFilterComparesAsNumber:
    """The specific defect this ticket calls out as a known mistake in an
    existing third-party Oracle vector store: without RETURNING NUMBER,
    JSON_VALUE returns a string and nine sorts above ten lexicographically.
    """

    def test_gt_excludes_lexicographically_larger_but_numerically_smaller(self, db):
        # "10" > "9" numerically is False if compared as strings ("10" < "9" lexically).
        results = db.vector_search("document", limit=10, filters=[GT("views", 9)])
        assert {r.name for r in results} == {"b", "c"}

    def test_lt_includes_only_numerically_smaller_values(self, db):
        results = db.vector_search("document", limit=10, filters=[LT("views", 10)])
        assert {r.name for r in results} == {"a"}

    def test_gt_100_way_boundary(self, db):
        """A lexicographic comparison would put "100" between "10" and "9"'s
        digit-by-digit prefix in confusing ways; a numeric comparison must not.
        """
        results = db.vector_search("document", limit=10, filters=[GT("views", 50)])
        assert {r.name for r in results} == {"c"}


class TestSupportedFilterOperatorSet:
    """Exactly PgVector's own operator set: EQ, IN, GT, LT, NOT, AND, OR.
    NEQ, GTE, LTE, CONTAINS, STARTSWITH are part of the broader FilterExpr
    language but not supported by the reference store, so they raise here too.
    """

    def test_eq_works(self, db):
        assert {r.name for r in db.vector_search("document", limit=10, filters=[EQ("views", 9)])} == {"a"}

    def test_in_works(self, db):
        assert {r.name for r in db.vector_search("document", limit=10, filters=[IN("views", [9, 10])])} == {"a", "b"}

    def test_and_works(self, db):
        results = db.vector_search("document", limit=10, filters=[AND(GT("views", 5), LT("views", 50))])
        assert {r.name for r in results} == {"a", "b"}

    def test_or_works(self, db):
        results = db.vector_search("document", limit=10, filters=[OR(EQ("views", 9), EQ("views", 100))])
        assert {r.name for r in results} == {"a", "c"}

    def test_not_works(self, db):
        results = db.vector_search("document", limit=10, filters=[NOT(EQ("views", 9))])
        assert {r.name for r in results} == {"b", "c"}

    def test_startswith_raises(self, db):
        with pytest.raises(ValueError):
            db.vector_search("document", limit=10, filters=[STARTSWITH("name", "a")])


class TestHybridWeightBoundary:
    def test_full_vector_weight_equals_pure_vector_search(self, db):
        # hybrid_search always needs the CTXSYS.CONTEXT index, even at
        # vector_score_weight=1.0: the text-scoring subquery is part of the
        # query regardless of the weight applied to its result.
        db.optimize()
        db.vector_score_weight = 1.0
        try:
            hybrid = db.hybrid_search("document", limit=3)
            vector = db.vector_search("document", limit=3)
            assert [r.id for r in hybrid] == [r.id for r in vector]
        finally:
            db.vector_score_weight = 0.5

    def test_out_of_range_weight_raises(self, db):
        db.vector_score_weight = 2.0
        try:
            with pytest.raises(ValueError):
                db.hybrid_search("document", limit=3)
        finally:
            db.vector_score_weight = 0.5


class TestTextSearchUnavailableIsActionable:
    def test_keyword_search_without_optimize_raises_actionable_error(self, db):
        """No CTXSYS.CONTEXT index has been created (optimize() was never
        called) -- must fail with a message naming the fix, not a raw
        DRG-*/ORA-29902 driver error.
        """
        with pytest.raises(ValueError, match="optimize"):
            db.keyword_search("document")

    def test_keyword_search_works_after_optimize(self, db):
        db.optimize()
        results = db.keyword_search("alpha")
        assert any(r.name == "a" for r in results)
