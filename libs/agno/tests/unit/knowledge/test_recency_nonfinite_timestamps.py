from datetime import datetime, timezone
from math import isfinite

import pytest

from agno.knowledge.document import Document
from agno.knowledge.reranker.recency import RecencyReranker, _as_timestamp
from agno.knowledge.utils import STORE_RECENCY_METADATA_KEY


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_nonfinite_timestamps_are_unusable(value):
    assert _as_timestamp(value) is None


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_invalid_document_time_uses_valid_store_time(value):
    now = datetime.now(timezone.utc).timestamp()
    document = Document(content="test", meta_data={"updated_at": value, STORE_RECENCY_METADATA_KEY: now})

    assert RecencyReranker()._recency(document, now) == pytest.approx(1.0)


@pytest.mark.asyncio
@pytest.mark.parametrize("async_mode", [False, True])
async def test_missing_numeric_date_does_not_poison_ranking(async_mode):
    now = datetime.now(timezone.utc).timestamp()
    documents = [
        Document(content="missing", id="missing", meta_data={"updated_at": float("nan"), "similarity_score": 0.1}),
        Document(content="fresh", id="fresh", meta_data={"updated_at": now, "similarity_score": 0.9}),
    ]
    reranker = RecencyReranker()

    results = await reranker.arerank("q", documents) if async_mode else reranker.rerank("q", documents)

    assert [document.id for document in results] == ["fresh", "missing"]
    assert all(isfinite(document.reranking_score) for document in results)
    assert all(document.reranking_score is None for document in documents)
