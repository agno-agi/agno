import pytest

from agno.knowledge.document import Document
from agno.knowledge.embedder import Embedder
from agno.vectordb.distance import Distance
from agno.vectordb.lancedb import LanceDb
from agno.vectordb.search import SearchType


class QueryEmbedder(Embedder):
    def get_embedding(self, text: str):
        return [1.0, 0.0]


@pytest.fixture(
    params=[
        (Distance.cosine, "cosine_match"),
        (Distance.l2, "l2_match"),
        (Distance.max_inner_product, "dot_match"),
    ],
    ids=["cosine", "l2", "dot"],
)
def distance_db(tmp_path, request):
    distance, expected = request.param
    db = LanceDb(uri=str(tmp_path), table_name="distances", embedder=QueryEmbedder(dimensions=2), distance=distance)
    # Each metric has a different best match for the query vector [1, 0].
    # No document matches "query", so hybrid ranking isolates the vector metric.
    db.insert(
        content_hash="distances",
        documents=[
            Document(name="cosine_match", content="recipe cosine_match", embedding=[10.0, 0.0]),
            Document(name="l2_match", content="recipe l2_match", embedding=[1.0, 1.0]),
            Document(name="dot_match", content="recipe dot_match", embedding=[20.0, 20.0]),
        ],
    )
    return db, expected


@pytest.mark.parametrize("search_type", [SearchType.vector, SearchType.hybrid])
def test_search_uses_configured_distance(distance_db, search_type):
    db, expected = distance_db
    db.search_type = search_type

    results = db.search("query", limit=3)

    assert len(results) == 3
    assert results[0].name == expected


@pytest.mark.asyncio
@pytest.mark.parametrize("search_type", [SearchType.vector, SearchType.hybrid])
async def test_async_search_uses_configured_distance(distance_db, search_type):
    db, expected = distance_db
    db.search_type = search_type

    results = await db.async_search("query", limit=3)

    assert len(results) == 3
    assert results[0].name == expected
