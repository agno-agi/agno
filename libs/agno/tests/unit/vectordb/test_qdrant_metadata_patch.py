from copy import deepcopy
from unittest.mock import Mock

import pytest
from qdrant_client import QdrantClient, models

from agno.knowledge.embedder.base import Embedder
from agno.vectordb.qdrant import Qdrant


class LocalEmbedder(Embedder):
    def get_embedding(self, text):
        return [1.0, 0.0]


def test_metadata_patch_changes_search_filters_and_preserves_payload():
    client = QdrantClient(":memory:")
    db = Qdrant(collection="documents", embedder=LocalEmbedder(dimensions=2))
    db._client = client
    client.create_collection("documents", vectors_config=models.VectorParams(size=2, distance=models.Distance.COSINE))
    payload = {
        "content_id": "content",
        "content": "sample document",
        "name": "sample",
        "meta_data": {"active": True, "rank": 1, "keep": "yes"},
        "filters": {"legacy": "untouched"},
    }
    client.upsert("documents", [models.PointStruct(id=1, vector=[1.0, 0.0], payload=deepcopy(payload))])
    client.upsert(
        "documents", [models.PointStruct(id=2, vector=[1.0, 0.0], payload={**payload, "content_id": "other"})]
    )
    patch = {"active": False, "rank": 0, "content_id": "metadata-only"}
    try:
        db.update_metadata("content", patch)
        updated = client.retrieve("documents", [1])[0].payload
        assert updated == {**payload, "meta_data": {**payload["meta_data"], **patch}}
        assert client.retrieve("documents", [2])[0].payload["meta_data"] == payload["meta_data"]
        assert [document.content for document in db.search("sample", filters={"active": False})] == ["sample document"]
        assert len(db.search("sample", filters={"active": True})) == 1
        assert patch == {"active": False, "rank": 0, "content_id": "metadata-only"}
    finally:
        client.close()


def test_metadata_patch_follows_all_scroll_pages():
    client = Mock()
    first_page = [models.Record(id=index) for index in range(1, 10001)]
    client.scroll.side_effect = [(first_page, 0), ([], 10001), ([models.Record(id=10001)], None)]
    db = Qdrant(collection="documents", embedder=LocalEmbedder(dimensions=2))
    db._client = client

    db.update_metadata("content", {"active": False})

    assert [call.kwargs.get("offset") for call in client.scroll.call_args_list] == [None, 0, 10001]
    updated_ids = []
    for call in client.set_payload.call_args_list:
        assert call.kwargs["key"] == "meta_data"
        assert call.kwargs["payload"] == {"active": False}
        assert call.kwargs["wait"] is True
        updated_ids.extend(call.kwargs["points"])
    assert updated_ids == list(range(1, 10002))


def test_metadata_patch_without_matches_does_not_write():
    client = Mock()
    client.scroll.return_value = ([], None)
    db = Qdrant(collection="documents", embedder=LocalEmbedder(dimensions=2))
    db._client = client
    db.update_metadata("missing", {"active": False})
    client.set_payload.assert_not_called()


@pytest.mark.parametrize("operation", ["scroll", "set_payload"])
def test_metadata_patch_propagates_client_errors(operation):
    client = Mock()
    client.scroll.return_value = ([models.Record(id=1)], None)
    getattr(client, operation).side_effect = RuntimeError("write unavailable")
    db = Qdrant(collection="documents", embedder=LocalEmbedder(dimensions=2))
    db._client = client
    with pytest.raises(RuntimeError, match="write unavailable"):
        db.update_metadata("content", {"active": False})
