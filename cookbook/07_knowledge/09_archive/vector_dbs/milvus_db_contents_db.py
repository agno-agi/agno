"""
Milvus + Contents DB
====================

End-to-end validation for the Milvus adapter when paired with a contents_db.
"""

import asyncio
import json

from agno.db.sqlite import SqliteDb
from agno.knowledge.embedder.openai import OpenAIEmbedder
from agno.knowledge.knowledge import Knowledge
from agno.vectordb.milvus import Milvus
from agno.vectordb.search import SearchType


# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------

vector_db = Milvus(
    collection="contents_db_demo",
    uri="/tmp/milvus_contents_db.db",
    search_type=SearchType.hybrid,
    embedder=OpenAIEmbedder(id="text-embedding-3-small"),
)

contents_db = SqliteDb(db_file="tmp/milvus_contents_db.db")

knowledge = Knowledge(
    name="Milvus Contents DB Demo",
    description="Validates Milvus + contents_db end-to-end.",
    vector_db=vector_db,
    contents_db=contents_db,
)

LARGE_TEXT = (
    "Tom Kha Gai is a classic Thai coconut soup. " * 200
)

def _ensure_loaded() -> None:
    vector_db.create()
    vector_db.client.load_collection(vector_db.collection)


def run_sync() -> None:
    _ensure_loaded()

    print("[1/4] Inserting a large document")
    knowledge.insert(
        name="ThaiSoup",
        text_content=LARGE_TEXT,
        metadata={"cuisine": "Thai", "type": "soup"},
    )

    print("[2/4] Updating metadata")
    contents, _total = contents_db.get_knowledge_contents()
    target = next(c for c in contents if c.name == "ThaiSoup")
    vector_db.update_metadata(
        content_id=target.id,
        metadata={"reviewed": True, "spice_level": "mild"},
    )

    print("[3/4] Reading back from Milvus")
    rows = vector_db.client.query(
        collection_name=vector_db.collection,
        filter=f'content_id == "{target.id}"',
        output_fields=["name", "content_id", "meta_data", "usage"],
        limit=2,
    )
    for i, row in enumerate(rows, start=1):
        meta_data = row["meta_data"]
        if isinstance(meta_data, str):
            meta_data = json.loads(meta_data)
        print(f"  Row {i}:")
        print(f"    name      : {row.get('name')}")
        print(f"    content_id: {row.get('content_id')}")
        print(f"    meta_data : {meta_data}")
        print(f"    usage     : {row.get('usage')}")


async def run_async() -> None:
    print("\n[async] Re-running the same flow through the async API ...")
    _ensure_loaded()
    await knowledge.aremove_all_content()
    await knowledge.ainsert(
        name="ThaiSoupAsync",
        text_content=LARGE_TEXT,
        metadata={"cuisine": "Thai", "type": "soup"},
    )
    results = await vector_db.async_search("Thai coconut soup", limit=1)
    print(f"[async] hits: {len(results)}")
    if results:
        print(f"[async] first hit meta_data: {results[0].meta_data}")


if __name__ == "__main__":
    run_sync()
    asyncio.run(run_async())
