"""Recency reranking: decay-weighted scoring over document timestamps."""

import inspect
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import pytest

from agno.knowledge.document import Document
from agno.knowledge.reranker.recency import RecencyReranker, _as_timestamp

NOW = datetime.now(timezone.utc)
OLD = NOW - timedelta(days=300)


def _document(doc_id: str, *, score: float, age_days: Optional[float], key: str = "updated_at") -> Document:
    meta: dict = {"similarity_score": score}
    if age_days is not None:
        meta[key] = (NOW - timedelta(days=age_days)).timestamp()
    return Document(id=doc_id, content=doc_id, meta_data=meta)


def test_a_fresher_document_outranks_a_slightly_more_relevant_stale_one():
    documents = [
        _document("stale", score=0.9, age_days=90),
        _document("fresh", score=0.7, age_days=1),
    ]

    results = RecencyReranker().rerank("q", documents)

    assert [doc.id for doc in results] == ["fresh", "stale"]


def test_a_clearly_more_relevant_old_document_still_wins():
    # Recency is a tilt, not a sort by date.
    documents = [
        _document("stale", score=1.0, age_days=365),
        _document("fresh", score=0.05, age_days=0),
    ]

    results = RecencyReranker(weight=0.2).rerank("q", documents)

    assert [doc.id for doc in results] == ["stale", "fresh"]


def test_weight_zero_is_plain_relevance_order():
    documents = [
        _document("stale", score=0.9, age_days=365),
        _document("fresh", score=0.7, age_days=0),
    ]

    results = RecencyReranker(weight=0.0).rerank("q", documents)

    assert [doc.id for doc in results] == ["stale", "fresh"]


def test_weight_one_sorts_by_age_alone():
    documents = [
        _document("stale", score=1.0, age_days=365),
        _document("fresh", score=0.0, age_days=0),
    ]

    results = RecencyReranker(weight=1.0).rerank("q", documents)

    assert [doc.id for doc in results] == ["fresh", "stale"]


def test_a_shorter_half_life_favours_freshness_more_sharply():
    documents = [
        _document("stale", score=0.9, age_days=60),
        _document("fresh", score=0.8, age_days=1),
    ]

    patient = RecencyReranker(half_life_days=365).rerank("q", documents)
    impatient = RecencyReranker(half_life_days=7).rerank("q", documents)

    assert [doc.id for doc in patient] == ["stale", "fresh"]
    assert [doc.id for doc in impatient] == ["fresh", "stale"]


def test_undated_documents_keep_their_relevance_rather_than_sorting_last():
    documents = [
        _document("dated_low", score=0.2, age_days=0),
        _document("undated_high", score=0.95, age_days=None),
    ]

    results = RecencyReranker().rerank("q", documents)

    assert [doc.id for doc in results] == ["undated_high", "dated_low"]


def test_a_custom_timestamp_key_is_read():
    documents = [
        _document("stale", score=0.9, age_days=90, key="published"),
        _document("fresh", score=0.7, age_days=1, key="published"),
    ]

    results = RecencyReranker(timestamp_key="published").rerank("q", documents)

    assert [doc.id for doc in results] == ["fresh", "stale"]


def test_an_existing_reranking_score_is_used_as_relevance():
    # Chained after another reranker, recency tilts that reranker's scores.
    documents = [Document(id="a", content="a", meta_data={"updated_at": NOW.timestamp()})]
    documents[0].reranking_score = 0.8

    results = RecencyReranker(weight=0.0).rerank("q", documents)

    assert results[0].reranking_score == pytest.approx(0.8)


def test_limit_trims_the_result():
    documents = [_document(str(i), score=0.5, age_days=i) for i in range(10)]

    results = RecencyReranker().rerank("q", documents, limit=3)

    assert len(results) == 3


def test_empty_input_returns_empty():
    assert RecencyReranker().rerank("q", []) == []


def test_input_documents_are_not_scored_in_place():
    documents = [_document("a", score=0.5, age_days=1)]

    RecencyReranker().rerank("q", documents)

    assert documents[0].reranking_score is None


def test_equal_scores_keep_the_vector_db_order():
    documents = [_document("first", score=0.5, age_days=5), _document("second", score=0.5, age_days=5)]

    results = RecencyReranker().rerank("q", documents)

    assert [doc.id for doc in results] == ["first", "second"]


def test_a_future_timestamp_does_not_score_above_one():
    documents = [_document("future", score=0.0, age_days=-30), _document("now", score=0.0, age_days=0)]

    results = RecencyReranker(weight=1.0).rerank("q", documents)

    assert all(doc.reranking_score <= 1.0 for doc in results)


@pytest.mark.asyncio
async def test_arerank_matches_sync():
    documents = [
        _document("stale", score=0.9, age_days=90),
        _document("fresh", score=0.7, age_days=1),
    ]

    results = await RecencyReranker().arerank("q", documents)

    assert [doc.id for doc in results] == ["fresh", "stale"]


@pytest.mark.parametrize(
    "value",
    [
        NOW.isoformat(),
        NOW.isoformat().replace("+00:00", "Z"),
        NOW.timestamp(),
        int(NOW.timestamp() * 1000),
        NOW,
        NOW.replace(tzinfo=None),
    ],
)
def test_supported_timestamp_formats_parse(value: Any):
    parsed = _as_timestamp(value)

    assert parsed is not None
    assert abs(parsed - NOW.timestamp()) < 2


@pytest.mark.parametrize("value", [None, "", "not a date", True, False, [], {}])
def test_unusable_timestamps_are_ignored(value: Any):
    assert _as_timestamp(value) is None


@pytest.mark.parametrize("kwargs", [{"half_life_days": 0}, {"half_life_days": -1}, {"weight": -0.1}, {"weight": 1.1}])
def test_invalid_configuration_is_rejected(kwargs):
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        RecencyReranker(**kwargs)


@pytest.mark.parametrize("kwargs", [{"half_life_days": True}, {"weight": True}])
def test_booleans_are_rejected_as_numeric_config(kwargs):
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        RecencyReranker(**kwargs)


def test_a_row_without_a_timestamp_adds_no_key():
    pgvector = pytest.importorskip("agno.vectordb.pgvector")

    class Row:
        meta_data = {"team": "ops"}

    store = pgvector.PgVector.__new__(pgvector.PgVector)
    store.report_row_timestamp = True

    assert pgvector.PgVector._with_recency(store, {"team": "ops"}, Row()) == {"team": "ops"}


def test_a_table_without_timestamp_columns_is_still_searchable():
    # Tables created before these columns existed must not break search.
    pytest.importorskip("sqlalchemy")
    pgvector = pytest.importorskip("agno.vectordb.pgvector")

    from sqlalchemy import Column, MetaData, String, Table

    legacy = Table("legacy", MetaData(), Column("id", String, primary_key=True))
    store = pgvector.PgVector.__new__(pgvector.PgVector)
    store.table = legacy

    # Compiles to a NULL literal rather than raising on the missing column.
    assert store._recency_column() is not None


def test_half_life_days_is_a_real_half_life():
    # At one half-life the recency term must be 0.5, not exp(-1). Ages are measured from
    # call time, so the documents are built here rather than from the module-level NOW.
    reranker = RecencyReranker(half_life_days=30.0, weight=1.0)
    now = datetime.now(timezone.utc)

    def scored(age_days: float) -> float:
        document = Document(
            id=str(age_days),
            content="c",
            meta_data={"updated_at": (now - timedelta(days=age_days)).timestamp()},
        )
        return reranker.rerank("q", [document])[0].reranking_score

    # A loose tolerance: a few seconds of clock drift during the run is not a failure.
    assert scored(0) == pytest.approx(1.0, abs=1e-3)
    assert scored(30) == pytest.approx(0.5, abs=1e-3)
    assert scored(60) == pytest.approx(0.25, abs=1e-3)


def test_an_undated_document_does_not_outrank_a_more_relevant_dated_one():
    # Both sides must be scaled the same way, or undated documents get a free boost.
    documents = [
        _document("dated_perfect", score=1.0, age_days=3650),
        _document("undated_worse", score=0.8, age_days=None),
    ]

    results = RecencyReranker(weight=0.3).rerank("q", documents)

    assert [doc.id for doc in results] == ["dated_perfect", "undated_worse"]


def test_a_corpus_with_no_timestamps_keeps_relevance_order():
    documents = [
        _document("high", score=0.9, age_days=None),
        _document("low", score=0.4, age_days=None),
    ]

    results = RecencyReranker().rerank("q", documents)

    assert [doc.id for doc in results] == ["high", "low"]


def test_pgvector_keyword_search_reports_a_relevance_score():
    # Without this the reranker sees relevance 0 for every row and ranks on age alone.
    pgvector = pytest.importorskip("agno.vectordb.pgvector")

    from agno.knowledge.utils import STORE_RECENCY_METADATA_KEY

    class Row:
        meta_data = {}
        similarity_score = 0.42

    setattr(Row, STORE_RECENCY_METADATA_KEY, NOW)

    store = pgvector.PgVector.__new__(pgvector.PgVector)
    store.report_row_timestamp = True
    merged = pgvector.PgVector._with_scores(store, {}, Row())

    assert merged["similarity_score"] == pytest.approx(0.42)
    assert STORE_RECENCY_METADATA_KEY in merged


def test_a_store_that_reports_no_score_ranks_by_position_not_by_date_alone():
    # Most vector dbs attach no score. Treating that as relevance 0 would turn the blend
    # into a pure sort by date and invert the store's own ordering.
    documents = [
        Document(id="top_hit_old", content="a", meta_data={"updated_at": (NOW - timedelta(days=300)).timestamp()}),
        Document(id="last_hit_new", content="b", meta_data={"updated_at": NOW.timestamp()}),
    ]

    results = RecencyReranker().rerank("q", documents)

    assert [doc.id for doc in results] == ["top_hit_old", "last_hit_new"]


def test_a_high_weight_still_promotes_the_newer_document_without_scores():
    documents = [
        Document(id="top_hit_old", content="a", meta_data={"updated_at": (NOW - timedelta(days=300)).timestamp()}),
        Document(id="last_hit_new", content="b", meta_data={"updated_at": NOW.timestamp()}),
    ]

    results = RecencyReranker(weight=0.9).rerank("q", documents)

    assert [doc.id for doc in results] == ["last_hit_new", "top_hit_old"]


def test_reported_scores_are_preferred_over_rank():
    documents = [
        _document("weak_first", score=0.1, age_days=0),
        _document("strong_second", score=0.9, age_days=0),
    ]

    results = RecencyReranker(weight=0.0).rerank("q", documents)

    assert [doc.id for doc in results] == ["strong_second", "weak_first"]


def test_recency_widens_the_candidate_pool():
    # A fresh document below the cutoff can only be promoted if it was retrieved.
    assert RecencyReranker().candidate_multiplier > 1
    assert RecencyReranker().search_limit(5) > 5


def test_a_wider_pool_promotes_a_fresh_document_from_below_the_cutoff():
    documents = [_document(f"rank{i}", score=1.0 - i * 0.05, age_days=400 if i < 3 else 0) for i in range(9)]

    from_wide_pool = RecencyReranker(weight=0.5).rerank("q", documents, limit=3)
    from_narrow_pool = RecencyReranker(weight=0.5).rerank("q", documents[:3], limit=3)

    assert [doc.id for doc in from_wide_pool] == ["rank3", "rank4", "rank5"]
    assert [doc.id for doc in from_narrow_pool] == ["rank0", "rank1", "rank2"]


def test_a_non_datetime_timestamp_column_does_not_raise():
    pgvector = pytest.importorskip("agno.vectordb.pgvector")

    from agno.knowledge.utils import STORE_RECENCY_METADATA_KEY

    class Row:
        meta_data = {"team": "ops"}

    setattr(Row, STORE_RECENCY_METADATA_KEY, "not-a-datetime")

    store = pgvector.PgVector.__new__(pgvector.PgVector)
    store.report_row_timestamp = True

    assert pgvector.PgVector._with_recency(store, {"team": "ops"}, Row()) == {"team": "ops"}


def test_keyword_relevance_is_reported_on_the_same_scale_as_other_search_types():
    # ts_rank_cd returns small unbounded values. Unnormalised, relevance would barely
    # register against a recency term that reaches 1.0, and weight would not mean what
    # it documents.
    pytest.importorskip("sqlalchemy")
    pgvector = pytest.importorskip("agno.vectordb.pgvector")

    source = inspect.getsource(pgvector.PgVector.keyword_search)

    # Shared with the hybrid path, so both report on one scale.
    assert '_normalized_rank(text_rank).label("similarity_score")' in source


def test_rank_relevance_does_not_depend_on_pool_width():
    # The same store position must be worth the same whatever max_results was, or
    # reranking_score is not comparable between searches.
    assert RecencyReranker._relevance_from_rank(1) == pytest.approx(0.5)
    assert RecencyReranker._relevance_from_rank(5) == pytest.approx(1 / 6)
    # And it never reaches zero, so a fresh tail document can still be promoted.
    assert RecencyReranker._relevance_from_rank(99) > 0.0


def test_a_fresh_tail_document_is_promoted_on_a_scoreless_store():
    documents = [
        Document(
            id=f"r{i}",
            content="c",
            meta_data={"updated_at": (NOW - timedelta(days=400 if i < 3 else 0)).timestamp()},
        )
        for i in range(9)
    ]

    results = RecencyReranker().rerank("q", documents, limit=3)

    assert [doc.id for doc in results][1:] == ["r3", "r4"]


def test_unbounded_adapter_scores_are_rescaled_so_weight_keeps_its_meaning():
    # OpenSearch passes raw BM25 through, which can be far above 1.0.
    documents = [
        Document(id="bm25_high", content="a", meta_data={"search_score": 42.7, "updated_at": OLD.timestamp()}),
        Document(id="bm25_low", content="b", meta_data={"search_score": 3.1, "updated_at": NOW.timestamp()}),
    ]

    results = RecencyReranker(weight=0.3).rerank("q", documents)

    # 0.7 relevance + 0.3 recency, not a score dominated by the raw magnitude.
    assert results[0].id == "bm25_high"
    assert results[0].reranking_score == pytest.approx(0.7, abs=0.01)


def test_identical_scores_do_not_collapse_ordering():
    documents = [
        Document(id="first", content="a", meta_data={"search_score": 5.0, "updated_at": NOW.timestamp()}),
        Document(id="second", content="b", meta_data={"search_score": 5.0, "updated_at": NOW.timestamp()}),
    ]

    results = RecencyReranker().rerank("q", documents)

    assert [doc.id for doc in results] == ["first", "second"]


def test_the_user_timestamp_wins_over_the_store_row_timestamp():
    # The store's row timestamp records when it was written, which is not the same as
    # when the document was, so a date the user set has to take precedence.
    from agno.knowledge.utils import STORE_RECENCY_METADATA_KEY

    documents = [
        Document(
            id="user_dated_old",
            content="a",
            meta_data={
                "similarity_score": 0.5,
                "updated_at": (NOW - timedelta(days=3650)).isoformat(),
                STORE_RECENCY_METADATA_KEY: NOW.isoformat(),
            },
        ),
        Document(
            id="store_dated_fresh",
            content="b",
            meta_data={"similarity_score": 0.5, STORE_RECENCY_METADATA_KEY: (NOW - timedelta(days=1)).isoformat()},
        ),
    ]

    results = RecencyReranker(weight=1.0).rerank("q", documents)

    assert [doc.id for doc in results] == ["store_dated_fresh", "user_dated_old"]


def test_the_store_row_timestamp_is_used_when_the_user_set_none():
    from agno.knowledge.utils import STORE_RECENCY_METADATA_KEY

    documents = [
        Document(
            id="stale",
            content="a",
            meta_data={"similarity_score": 0.9, STORE_RECENCY_METADATA_KEY: (NOW - timedelta(days=300)).isoformat()},
        ),
        Document(
            id="fresh",
            content="b",
            meta_data={"similarity_score": 0.7, STORE_RECENCY_METADATA_KEY: NOW.isoformat()},
        ),
    ]

    results = RecencyReranker().rerank("q", documents)

    assert [doc.id for doc in results] == ["fresh", "stale"]


def test_pgvector_does_not_report_the_row_timestamp_unless_asked():
    # It travels in meta_data, which reaches the model's prompt, so users who never
    # configured recency should see no change in their search results.
    pgvector = pytest.importorskip("agno.vectordb.pgvector")
    from agno.knowledge.utils import STORE_RECENCY_METADATA_KEY

    class Row:
        meta_data = {"team": "ops"}

    setattr(Row, STORE_RECENCY_METADATA_KEY, NOW)

    store = pgvector.PgVector.__new__(pgvector.PgVector)
    store.report_row_timestamp = False
    assert pgvector.PgVector._with_recency(store, {"team": "ops"}, Row()) == {"team": "ops"}

    store.report_row_timestamp = True
    reported = pgvector.PgVector._with_recency(store, {"team": "ops"}, Row())
    assert reported[STORE_RECENCY_METADATA_KEY].startswith(NOW.isoformat()[:19])


def test_the_reported_key_cannot_mask_a_user_timestamp():
    pgvector = pytest.importorskip("agno.vectordb.pgvector")
    from agno.knowledge.utils import STORE_RECENCY_METADATA_KEY

    class Row:
        meta_data = {"updated_at": "2019-01-01T00:00:00+00:00"}

    setattr(Row, STORE_RECENCY_METADATA_KEY, NOW)

    store = pgvector.PgVector.__new__(pgvector.PgVector)
    store.report_row_timestamp = True

    merged = pgvector.PgVector._with_recency(store, {"updated_at": "2019-01-01T00:00:00+00:00"}, Row())

    assert merged["updated_at"] == "2019-01-01T00:00:00+00:00"
    assert STORE_RECENCY_METADATA_KEY in merged


def test_recency_refuses_a_store_that_cannot_report_row_timestamps():
    # Only PgVector reports when its rows were written. Elsewhere the reranker would rank
    # on relevance alone while looking like recency had run.
    class Qdrant:
        pass

    with pytest.raises(NotImplementedError, match="not implemented for Qdrant yet"):
        RecencyReranker().validate_vector_db(Qdrant())


def test_recency_accepts_pgvector():
    pgvector = pytest.importorskip("agno.vectordb.pgvector")

    store = pgvector.PgVector.__new__(pgvector.PgVector)

    assert RecencyReranker().validate_vector_db(store) is None


def test_other_rerankers_accept_any_store():
    # The base hook is permissive: only a reranker with a store requirement overrides it.
    from agno.knowledge.reranker.mmr import MMRReranker

    class Qdrant:
        pass

    assert MMRReranker().validate_vector_db(Qdrant()) is None


def test_knowledge_refuses_the_pairing_at_construction():
    # Setup is where this should fail, not part way through a search.
    from agno.knowledge.knowledge import Knowledge

    class Qdrant:
        reranker = None

        def exists(self) -> bool:
            return True

    with pytest.raises(NotImplementedError, match="not implemented for Qdrant yet"):
        Knowledge(vector_db=Qdrant(), reranker=RecencyReranker())
