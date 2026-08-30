"""Multi-page URL reads land one contents-db row per page, owned by a site row.

Each page row's id equals the ``content_id`` its vectors carry, an unchanged page
refreshes its row without re-embedding, a changed page re-embeds alone, a page that
left the site is deleted, a failed page gets a FAILED row and is retried next run,
and deleting the site row cascades to its page rows and their vectors.
"""

import asyncio
import time
from typing import Dict, List, Optional, Tuple
from unittest import mock

from agno.db.sqlite import SqliteDb
from agno.knowledge.content import Content
from agno.knowledge.document import Document
from agno.knowledge.knowledge import Knowledge
from agno.knowledge.reader.base import Reader
from agno.knowledge.types import ContentType
from agno.knowledge.utils import get_agno_metadata
from agno.utils.string import generate_id

SITE_URL = "https://docs.x.com/sitemap.xml"
PAGE_ONE = "https://docs.x.com/guide"
PAGE_TWO = "https://docs.x.com/api"
PAGE_THREE = "https://docs.x.com/faq"

PAGE_ERROR = "HTTP 500"


class FakePagesReader(Reader):
    """Multi-page reader stub: one document per entry in ``pages``, no network.

    A ``None`` page text marks an error page: empty content plus
    ``meta_data['error']``, the shape multi-page readers use for a fetch failure.
    """

    def __init__(self, pages: Dict[str, Optional[str]], **kwargs) -> None:
        super().__init__(**kwargs)
        self.pages = dict(pages)

    @classmethod
    def get_supported_content_types(cls) -> List[ContentType]:
        return [ContentType.URL]

    def read(self, obj, name: Optional[str] = None, password: Optional[str] = None) -> List[Document]:
        documents = []
        for url, text in self.pages.items():
            meta = {"url": url, "title": "Title", "extractor": "fake", "source": "sitemap"}
            if text is None:
                meta["error"] = PAGE_ERROR
                text = ""
            documents.append(Document(name=name, meta_data=meta, content=text))
        return documents

    async def async_read(self, obj, name: Optional[str] = None, password: Optional[str] = None) -> List[Document]:
        return self.read(obj, name=name, password=password)


class LightRag:
    """Stands in for the real LightRag adapter, which Knowledge matches by class name."""

    def __init__(self) -> None:
        self.inserted_texts: List[Tuple[str, str]] = []

    def exists(self) -> bool:
        return True

    def create(self) -> None:
        pass

    def content_hash_exists(self, content_hash: str, user_id: Optional[str] = None) -> bool:
        return False

    def update_metadata(self, content_id: str, metadata: Dict) -> None:
        pass

    async def insert_text(self, file_source: str, text: str) -> str:
        self.inserted_texts.append((file_source, text))
        return "ext-1"


def _kb(tmp_path, vector_db, filename: str = "contents.db") -> Knowledge:
    return Knowledge(name="t", vector_db=vector_db, contents_db=SqliteDb(db_file=str(tmp_path / filename)))


def _rows(kb: Knowledge):
    rows, _ = kb.contents_db.get_knowledge_contents()
    return rows


def _site_row(rows):
    sites = [row for row in rows if get_agno_metadata(row.metadata, "children") is not None]
    assert len(sites) == 1, f"expected exactly one site row, got {len(sites)}"
    return sites[0]


def _child_rows(rows):
    return {row.id: row for row in rows if get_agno_metadata(row.metadata, "parent_id") is not None}


def _child_by_url(rows, url: str):
    children = [row for row in _child_rows(rows).values() if get_agno_metadata(row.metadata, "source_url") == url]
    assert len(children) == 1, f"expected exactly one child row for {url}, got {len(children)}"
    return children[0]


def _record_deletes(vector_db) -> List[Tuple[str, Optional[str]]]:
    """Shadow ``delete_by_content_id`` with a recording twin that still declares user_id."""
    deleted: List[Tuple[str, Optional[str]]] = []

    def delete_by_content_id(content_id: str, user_id: Optional[str] = None) -> bool:
        deleted.append((content_id, user_id))
        return True

    vector_db.delete_by_content_id = delete_by_content_id
    return deleted


def _clear_writes(vector_db) -> None:
    vector_db.writes.clear()
    vector_db.inserted_documents.clear()
    vector_db.upserted_documents.clear()


def _assert_site_and_children_shape(vector_db, rows) -> None:
    assert len(rows) == 3
    site = _site_row(rows)
    assert site.name == "docs.x.com"
    assert site.status == "completed"
    assert site.status_message == "2 of 2 pages loaded"
    assert get_agno_metadata(site.metadata, "extractor_counts") == {"fake": 2}

    children = _child_rows(rows)
    child_ids = get_agno_metadata(site.metadata, "children")
    assert sorted(child_ids) == sorted(children.keys())

    # Each page row's id equals the content_id its vectors carry
    assert len(vector_db.writes) == 2
    content_id_by_url = {doc.meta_data["url"]: doc.content_id for doc in vector_db.inserted_documents}
    for child in children.values():
        source_url = get_agno_metadata(child.metadata, "source_url")
        assert source_url in (PAGE_ONE, PAGE_TWO)
        assert content_id_by_url[source_url] == child.id
        assert child.status == "completed"
        assert child.metadata["team"] == "docs"
        assert get_agno_metadata(child.metadata, "parent_id") == site.id
        assert get_agno_metadata(child.metadata, "content_digest")
        assert get_agno_metadata(child.metadata, "extractor") == "fake"


async def test_multi_page_ainsert_lands_site_row_and_page_rows(vector_db, tmp_path):
    kb = _kb(tmp_path, vector_db)
    reader = FakePagesReader({PAGE_ONE: "guide text", PAGE_TWO: "api text"})

    await kb.ainsert(url=SITE_URL, reader=reader, metadata={"team": "docs"})

    _assert_site_and_children_shape(vector_db, _rows(kb))


def test_multi_page_insert_lands_site_row_and_page_rows(vector_db, tmp_path):
    kb = _kb(tmp_path, vector_db)
    reader = FakePagesReader({PAGE_ONE: "guide text", PAGE_TWO: "api text"})

    kb.insert(url=SITE_URL, reader=reader, metadata={"team": "docs"})

    _assert_site_and_children_shape(vector_db, _rows(kb))


async def test_ainsert_unchanged_pages_skip_embedding_and_refresh_rows(vector_db, tmp_path):
    kb = _kb(tmp_path, vector_db)
    reader = FakePagesReader({PAGE_ONE: "guide text", PAGE_TWO: "api text"})
    await kb.ainsert(url=SITE_URL, reader=reader)
    first_ids = {row.id for row in _rows(kb)}
    _clear_writes(vector_db)

    future = int(time.time()) + 1000
    with mock.patch("time.time", return_value=float(future)):
        await kb.ainsert(url=SITE_URL, reader=reader)

    assert vector_db.writes == []
    rows = _rows(kb)
    assert {row.id for row in rows} == first_ids
    assert _site_row(rows).status_message == "2 of 2 pages loaded"
    for child in _child_rows(rows).values():
        assert child.status == "completed"
        assert child.updated_at == future, "unchanged page row did not refresh updated_at"


def test_insert_unchanged_pages_skip_embedding(vector_db, tmp_path):
    kb = _kb(tmp_path, vector_db)
    reader = FakePagesReader({PAGE_ONE: "guide text", PAGE_TWO: "api text"})
    kb.insert(url=SITE_URL, reader=reader)
    first_ids = {row.id for row in _rows(kb)}
    _clear_writes(vector_db)

    kb.insert(url=SITE_URL, reader=reader)

    assert vector_db.writes == []
    assert {row.id for row in _rows(kb)} == first_ids


async def test_ainsert_changed_page_reembeds_only_that_page(vector_db, tmp_path):
    kb = _kb(tmp_path, vector_db)
    await kb.ainsert(url=SITE_URL, reader=FakePagesReader({PAGE_ONE: "guide text", PAGE_TWO: "api text"}))
    _clear_writes(vector_db)

    await kb.ainsert(url=SITE_URL, reader=FakePagesReader({PAGE_ONE: "guide text", PAGE_TWO: "api text v2"}))

    assert len(vector_db.writes) == 1
    assert {doc.meta_data["url"] for doc in vector_db.inserted_documents} == {PAGE_TWO}


def test_insert_changed_page_reembeds_only_that_page(vector_db, tmp_path):
    kb = _kb(tmp_path, vector_db)
    kb.insert(url=SITE_URL, reader=FakePagesReader({PAGE_ONE: "guide text", PAGE_TWO: "api text"}))
    _clear_writes(vector_db)

    kb.insert(url=SITE_URL, reader=FakePagesReader({PAGE_ONE: "guide text", PAGE_TWO: "api text v2"}))

    assert len(vector_db.writes) == 1
    assert {doc.meta_data["url"] for doc in vector_db.inserted_documents} == {PAGE_TWO}


async def test_ainsert_removed_page_deletes_its_row_and_vectors(vector_db, tmp_path):
    kb = _kb(tmp_path, vector_db)
    await kb.ainsert(
        url=SITE_URL, reader=FakePagesReader({PAGE_ONE: "guide text", PAGE_TWO: "api text", PAGE_THREE: "faq text"})
    )
    removed_id = _child_by_url(_rows(kb), PAGE_THREE).id
    deleted = _record_deletes(vector_db)

    await kb.ainsert(url=SITE_URL, reader=FakePagesReader({PAGE_ONE: "guide text", PAGE_TWO: "api text"}))

    # The multi-page load clears the site row's own content_id first (legacy-vector
    # hygiene), then removes the departed page.
    assert deleted[-1] == (removed_id, None)
    assert (removed_id, None) in deleted
    rows = _rows(kb)
    assert removed_id not in {row.id for row in rows}
    site = _site_row(rows)
    assert removed_id not in get_agno_metadata(site.metadata, "children")
    assert len(get_agno_metadata(site.metadata, "children")) == 2
    assert site.status_message == "2 of 2 pages loaded"


async def test_ainsert_failed_page_gets_failed_row_and_is_retried(vector_db, tmp_path):
    kb = _kb(tmp_path, vector_db)
    await kb.ainsert(url=SITE_URL, reader=FakePagesReader({PAGE_ONE: "guide text", PAGE_TWO: None}))

    rows = _rows(kb)
    failed_child = _child_by_url(rows, PAGE_TWO)
    assert failed_child.status == "failed"
    assert failed_child.status_message == PAGE_ERROR
    assert len(vector_db.writes) == 1, "the failed page must not reach the vector db"
    assert {doc.meta_data["url"] for doc in vector_db.inserted_documents} == {PAGE_ONE}
    site = _site_row(rows)
    assert site.status == "completed"
    assert site.status_message == f"1 of 2 pages loaded; failed: {PAGE_TWO}"
    assert get_agno_metadata(site.metadata, "failed") == [{"url": PAGE_TWO, "error": PAGE_ERROR}]

    # The page comes back on the next run: FAILED rows retry
    _clear_writes(vector_db)
    await kb.ainsert(url=SITE_URL, reader=FakePagesReader({PAGE_ONE: "guide text", PAGE_TWO: "api text"}))

    rows = _rows(kb)
    retried = _child_by_url(rows, PAGE_TWO)
    assert retried.status == "completed"
    assert len(vector_db.writes) == 1
    assert {doc.meta_data["url"] for doc in vector_db.inserted_documents} == {PAGE_TWO}
    assert _site_row(rows).status_message == "2 of 2 pages loaded"


def test_insert_failed_page_gets_failed_row(vector_db, tmp_path):
    kb = _kb(tmp_path, vector_db)
    kb.insert(url=SITE_URL, reader=FakePagesReader({PAGE_ONE: "guide text", PAGE_TWO: None}))

    rows = _rows(kb)
    failed_child = _child_by_url(rows, PAGE_TWO)
    assert failed_child.status == "failed"
    assert failed_child.status_message == PAGE_ERROR
    assert len(vector_db.writes) == 1
    site = _site_row(rows)
    assert site.status == "completed"
    assert site.status_message == f"1 of 2 pages loaded; failed: {PAGE_TWO}"


async def test_ainsert_all_pages_failed_marks_site_row_failed(vector_db, tmp_path):
    kb = _kb(tmp_path, vector_db)
    await kb.ainsert(url=SITE_URL, reader=FakePagesReader({PAGE_ONE: None, PAGE_TWO: None}))

    rows = _rows(kb)
    site = _site_row(rows)
    assert site.status == "failed"
    assert site.status_message == f"0 of 2 pages loaded; failed: {PAGE_ONE}, {PAGE_TWO}"
    assert vector_db.writes == []
    for child in _child_rows(rows).values():
        assert child.status == "failed"


async def test_ainsert_scoped_owner_owns_rows_and_vectors(vector_db, tmp_path):
    kb = _kb(tmp_path, vector_db)
    await kb.ainsert(url=SITE_URL, reader=FakePagesReader({PAGE_ONE: "guide text", PAGE_TWO: "api text"}), user_id="u1")

    rows = _rows(kb)
    assert len(rows) == 3
    assert all(row.user_id == "u1" for row in rows)
    assert vector_db.owners == ["u1", "u1"]

    # Another user's scoped read sees only shared rows -- none here
    visible_to_u2, count_u2 = await kb.aget_content(user_id="u2")
    assert visible_to_u2 == []
    assert count_u2 == 0
    visible_to_u1, count_u1 = await kb.aget_content(user_id="u1")
    assert count_u1 == 3
    assert {content.id for content in visible_to_u1} == {row.id for row in rows}

    # The owner's scoped delete of the site row removes everything
    await kb.aremove_content_by_id(_site_row(rows).id, user_id="u1")
    assert _rows(kb) == []


async def test_aremove_site_row_cascades_to_page_rows(vector_db, tmp_path):
    kb = _kb(tmp_path, vector_db)
    await kb.ainsert(url=SITE_URL, reader=FakePagesReader({PAGE_ONE: "guide text", PAGE_TWO: "api text"}))
    rows = _rows(kb)
    site_id = _site_row(rows).id
    child_ids = set(_child_rows(rows).keys())
    deleted = _record_deletes(vector_db)

    await kb.aremove_content_by_id(site_id)

    assert _rows(kb) == []
    deleted_ids = [content_id for content_id, _ in deleted]
    for child_id in child_ids:
        assert deleted_ids.count(child_id) == 1
    assert deleted_ids.count(site_id) == 1


def test_remove_site_row_cascades_to_page_rows(vector_db, tmp_path):
    kb = _kb(tmp_path, vector_db)
    kb.insert(url=SITE_URL, reader=FakePagesReader({PAGE_ONE: "guide text", PAGE_TWO: "api text"}))
    rows = _rows(kb)
    site_id = _site_row(rows).id
    child_ids = set(_child_rows(rows).keys())
    deleted = _record_deletes(vector_db)

    kb.remove_content_by_id(site_id)

    assert _rows(kb) == []
    deleted_ids = [content_id for content_id, _ in deleted]
    for child_id in child_ids:
        assert deleted_ids.count(child_id) == 1
    assert deleted_ids.count(site_id) == 1


async def test_aremove_child_row_drops_it_from_parent_children(vector_db, tmp_path):
    kb = _kb(tmp_path, vector_db)
    await kb.ainsert(url=SITE_URL, reader=FakePagesReader({PAGE_ONE: "guide text", PAGE_TWO: "api text"}))
    rows = _rows(kb)
    removed_id = _child_by_url(rows, PAGE_TWO).id
    kept_id = _child_by_url(rows, PAGE_ONE).id

    await kb.aremove_content_by_id(removed_id)

    rows = _rows(kb)
    assert set(_child_rows(rows).keys()) == {kept_id}
    remaining_ids = {row.id for row in rows}
    assert removed_id not in remaining_ids
    site = _site_row(rows)
    children = get_agno_metadata(site.metadata, "children")
    assert removed_id not in children
    assert children == [kept_id]


async def test_single_page_read_keeps_legacy_single_row(vector_db, tmp_path):
    kb = _kb(tmp_path, vector_db)
    await kb.ainsert(url=SITE_URL, reader=FakePagesReader({PAGE_ONE: "only page"}))

    rows = _rows(kb)
    assert len(rows) == 1
    row = rows[0]
    assert row.name == "sitemap.xml"
    assert row.status == "completed"
    assert get_agno_metadata(row.metadata, "children") is None
    assert get_agno_metadata(row.metadata, "parent_id") is None
    assert len(vector_db.writes) == 1
    assert all(doc.content_id == row.id for doc in vector_db.inserted_documents)


def test_insert_single_page_read_keeps_legacy_single_row(vector_db, tmp_path):
    kb = _kb(tmp_path, vector_db)
    kb.insert(url=SITE_URL, reader=FakePagesReader({PAGE_ONE: "only page"}))

    rows = _rows(kb)
    assert len(rows) == 1
    assert rows[0].status == "completed"
    assert get_agno_metadata(rows[0].metadata, "children") is None
    assert len(vector_db.writes) == 1


async def test_shrink_to_one_page_keeps_site_row(vector_db, tmp_path):
    kb = _kb(tmp_path, vector_db)
    await kb.ainsert(url=SITE_URL, reader=FakePagesReader({PAGE_ONE: "guide text", PAGE_TWO: "api text"}))

    await kb.ainsert(url=SITE_URL, reader=FakePagesReader({PAGE_ONE: "guide text"}))

    rows = _rows(kb)
    assert len(rows) == 2
    site = _site_row(rows)
    assert site.status == "completed"
    assert site.status_message == "1 of 1 pages loaded"
    children = get_agno_metadata(site.metadata, "children")
    assert children == [_child_by_url(rows, PAGE_ONE).id]


async def test_lightrag_refuses_multi_page_read_async(tmp_path):
    lightrag = LightRag()
    kb = _kb(tmp_path, lightrag)
    reader = FakePagesReader({PAGE_ONE: "guide text", PAGE_TWO: "api text"})
    reader.chunk = True

    await kb.ainsert(url=SITE_URL, reader=reader)

    rows = _rows(kb)
    assert len(rows) == 1
    assert rows[0].status == "failed"
    assert rows[0].status_message == "LightRag does not support multi-page readers"
    assert lightrag.inserted_texts == []
    assert reader.chunk is True, "reader.chunk was not restored after the unchunked read"


def test_lightrag_refuses_multi_page_read_sync(tmp_path):
    lightrag = LightRag()
    kb = _kb(tmp_path, lightrag)
    reader = FakePagesReader({PAGE_ONE: "guide text", PAGE_TWO: "api text"})
    reader.chunk = True

    kb.insert(url=SITE_URL, reader=reader)

    rows = _rows(kb)
    assert len(rows) == 1
    assert rows[0].status == "failed"
    assert rows[0].status_message == "LightRag does not support multi-page readers"
    assert lightrag.inserted_texts == []
    assert reader.chunk is True, "reader.chunk was not restored after the unchunked read"


async def test_skip_if_exists_still_refreshes_changed_page(vector_db, tmp_path):
    kb = _kb(tmp_path, vector_db)
    await kb.ainsert(
        url=SITE_URL, reader=FakePagesReader({PAGE_ONE: "guide text", PAGE_TWO: "api text"}), skip_if_exists=True
    )
    _clear_writes(vector_db)

    await kb.ainsert(
        url=SITE_URL, reader=FakePagesReader({PAGE_ONE: "guide text", PAGE_TWO: "api text v2"}), skip_if_exists=True
    )

    assert len(vector_db.writes) == 1
    assert {doc.meta_data["url"] for doc in vector_db.inserted_documents} == {PAGE_TWO}


async def test_upsert_false_still_refreshes_changed_page(vector_db, tmp_path):
    kb = _kb(tmp_path, vector_db)
    await kb.ainsert(url=SITE_URL, reader=FakePagesReader({PAGE_ONE: "guide text", PAGE_TWO: "api text"}))
    _clear_writes(vector_db)

    await kb.ainsert(
        url=SITE_URL, reader=FakePagesReader({PAGE_ONE: "guide text", PAGE_TWO: "api text v2"}), upsert=False
    )

    assert len(vector_db.writes) == 1
    assert {doc.meta_data["url"] for doc in vector_db.inserted_documents} == {PAGE_TWO}


# ---------------------------------------------------------------------------
# Failure-mode hardening (review round: fail closed, keep ownership)
# ---------------------------------------------------------------------------


class RaisingReader(FakePagesReader):
    """Raises on read, standing in for a transient reader failure mid-refresh."""

    def read(self, obj, name=None, password=None):
        raise RuntimeError("transient reader failure")

    async def async_read(self, obj, name=None, password=None):
        raise RuntimeError("transient reader failure")


class IncompleteDiscoveryReader(FakePagesReader):
    """Marks every document as coming from an incomplete sitemap discovery."""

    def read(self, obj, name=None, password=None):
        documents = super().read(obj, name=name, password=password)
        for doc in documents:
            doc.meta_data["discovery_incomplete"] = True
        return documents


async def test_failed_refresh_keeps_children_on_site_row(vector_db, tmp_path):
    kb = _kb(tmp_path, vector_db)
    await kb.ainsert(url=SITE_URL, reader=FakePagesReader({PAGE_ONE: "guide text", PAGE_TWO: "api text"}))
    site = _site_row(_rows(kb))
    previous_children = get_agno_metadata(site.metadata, "children")

    # Reader failures are caught by the load path: the row lands FAILED, nothing raises
    await kb.ainsert(url=SITE_URL, reader=RaisingReader({}))

    row = await kb.aget_content_by_id(site.id)
    assert row.status == "failed"
    # The cascade record survives the failed read, so a site delete still reaches the pages
    assert get_agno_metadata(row.metadata, "children") == previous_children
    await kb.aremove_content_by_id(site.id)
    rows, count = await kb.aget_content()
    assert count == 0


async def test_embed_failure_does_not_persist_digest(vector_db, tmp_path):
    kb = _kb(tmp_path, vector_db)
    original_insert = vector_db.async_insert
    fail = {"active": True}

    async def failing_insert(content_hash, documents=None, filters=None, **kwargs):
        if fail["active"] and any(doc.meta_data.get("url") == PAGE_TWO for doc in documents):
            raise RuntimeError("embed down")
        return await original_insert(content_hash, documents=documents, filters=filters)

    vector_db.async_insert = failing_insert
    await kb.ainsert(url=SITE_URL, reader=FakePagesReader({PAGE_ONE: "guide text", PAGE_TWO: "api text"}))

    failed_child = next(row for row in _rows(kb) if get_agno_metadata(row.metadata, "source_url") == PAGE_TWO)
    assert failed_child.status == "failed"
    assert get_agno_metadata(failed_child.metadata, "content_digest") is None

    # Same text again with a healthy embedder: the page must re-embed, not flip to
    # completed on a digest recorded by the failed run
    fail["active"] = False
    _clear_writes(vector_db)
    await kb.ainsert(url=SITE_URL, reader=FakePagesReader({PAGE_ONE: "guide text", PAGE_TWO: "api text"}))
    healed = next(row for row in _rows(kb) if get_agno_metadata(row.metadata, "source_url") == PAGE_TWO)
    assert healed.status == "completed"
    assert any(doc.meta_data.get("url") == PAGE_TWO for doc in vector_db.inserted_documents)


async def test_incomplete_discovery_suppresses_prune(vector_db, tmp_path):
    kb = _kb(tmp_path, vector_db)
    await kb.ainsert(url=SITE_URL, reader=FakePagesReader({PAGE_ONE: "guide text", PAGE_TWO: "api text"}))

    # A read that lost a sitemap shard reports only page one, flagged incomplete
    await kb.ainsert(url=SITE_URL, reader=IncompleteDiscoveryReader({PAGE_ONE: "guide text"}))

    rows = _rows(kb)
    kept = {get_agno_metadata(row.metadata, "source_url") for row in rows} - {None}
    assert PAGE_TWO in kept, "a missing shard's pages must not be treated as removed"
    site = _site_row(rows)
    assert "discovery incomplete" in site.status_message
    # The transport flag never reaches vector metadata
    assert not any("discovery_incomplete" in (doc.meta_data or {}) for doc in vector_db.inserted_documents)


async def test_fetch_failure_keeps_last_known_good_page(vector_db, tmp_path):
    kb = _kb(tmp_path, vector_db)
    await kb.ainsert(url=SITE_URL, reader=FakePagesReader({PAGE_ONE: "guide text", PAGE_TWO: "api text"}))

    await kb.ainsert(url=SITE_URL, reader=FakePagesReader({PAGE_ONE: "guide text", PAGE_TWO: None}))

    rows = _rows(kb)
    kept = next(row for row in rows if get_agno_metadata(row.metadata, "source_url") == PAGE_TWO)
    assert kept.status == "completed", "a transient fetch failure must not demote a loaded page"
    site = _site_row(rows)
    failures = get_agno_metadata(site.metadata, "failed")
    assert failures and failures[0]["url"] == PAGE_TWO and failures[0].get("stale_kept") == "true"


async def test_all_pages_failed_single_group_marks_row_failed(vector_db, tmp_path):
    kb = _kb(tmp_path, vector_db)

    await kb.ainsert(url="https://docs.x.com/only", reader=FakePagesReader({PAGE_ONE: None}))

    rows, count = await kb.aget_content()
    assert count == 1
    assert rows[0].status == "failed"
    assert PAGE_ERROR in (rows[0].status_message or "")
    assert vector_db.writes == []


async def test_single_row_site_growing_to_pages_clears_legacy_vectors(vector_db, tmp_path):
    kb = _kb(tmp_path, vector_db)
    await kb.ainsert(url=SITE_URL, reader=FakePagesReader({PAGE_ONE: "only page"}))
    parent_id = _rows(kb)[0].id

    deleted = []
    original_delete = vector_db.delete_by_content_id

    def recording_delete(content_id, user_id=None):
        deleted.append(content_id)
        return original_delete(content_id)

    vector_db.delete_by_content_id = recording_delete
    await kb.ainsert(url=SITE_URL, reader=FakePagesReader({PAGE_ONE: "only page", PAGE_TWO: "second"}))

    assert parent_id in deleted, "the legacy single-row vectors must not stay searchable under the site row"


async def test_prune_failure_keeps_stale_child_in_children(vector_db, tmp_path):
    kb = _kb(tmp_path, vector_db)
    await kb.ainsert(url=SITE_URL, reader=FakePagesReader({PAGE_ONE: "guide text", PAGE_TWO: "api text"}))
    site = _site_row(_rows(kb))
    stale_ids = set(get_agno_metadata(site.metadata, "children"))

    original_delete = vector_db.delete_by_content_id

    def failing_delete(content_id, user_id=None):
        raise RuntimeError("adapter down")

    vector_db.delete_by_content_id = failing_delete
    await kb.ainsert(url=SITE_URL, reader=FakePagesReader({PAGE_ONE: "guide text"}))
    vector_db.delete_by_content_id = original_delete

    site = _site_row(_rows(kb))
    children = set(get_agno_metadata(site.metadata, "children"))
    # The page whose delete failed keeps its place in the cascade record
    assert stale_ids - children == set(), f"lost ownership of {stale_ids - children}"


async def test_site_row_records_reader_id(vector_db, tmp_path):
    kb = _kb(tmp_path, vector_db)
    reader = FakePagesReader({PAGE_ONE: "guide text", PAGE_TWO: "api text"})
    reader.__class__ = type("SitemapReader", (FakePagesReader,), {})

    await kb.ainsert(url=SITE_URL, reader=reader)

    site = _site_row(_rows(kb))
    assert get_agno_metadata(site.metadata, "reader_id") == "sitemap"


# ---------------------------------------------------------------------------
# Review round 2: total discovery failure never prunes; vector delete False honored
# ---------------------------------------------------------------------------


class EmptyReader(FakePagesReader):
    """A read that saw nothing — total outage: every shard failed, zero documents."""

    def read(self, obj, name=None, password=None):
        return []


class FallbackOutageReader(FakePagesReader):
    """The root sitemap is unreachable: the reader falls back to the single page at the
    URL, fails to fetch it, and flags the read as incomplete discovery — the exact
    document shape SitemapReader emits in that state."""

    def read(self, obj, name=None, password=None):
        return [
            Document(
                name=str(obj),
                meta_data={"url": str(obj), "error": "HTTP 503", "source": "page", "discovery_incomplete": True},
                content="",
            )
        ]


def _assert_pages_survive(kb, vector_db):
    rows = _rows(kb)
    kept_urls = {get_agno_metadata(row.metadata, "source_url") for row in rows} - {None}
    assert {PAGE_ONE, PAGE_TWO} <= kept_urls, f"pages lost: {kept_urls}"
    site = _site_row(rows)
    children = set(get_agno_metadata(site.metadata, "children") or [])
    page_row_ids = {row.id for row in rows if get_agno_metadata(row.metadata, "parent_id")}
    assert page_row_ids <= children, "surviving pages must stay owned by the site row"
    loaded_row_ids = {
        row.id for row in rows if get_agno_metadata(row.metadata, "parent_id") and row.status == "completed"
    }
    vector_ids = {doc.content_id for doc in vector_db.inserted_documents}
    assert loaded_row_ids <= vector_ids, "surviving loaded rows must keep their vector groups"


async def test_all_shards_failed_refresh_preserves_pages_async(vector_db, tmp_path):
    kb = _kb(tmp_path, vector_db)
    await kb.ainsert(url=SITE_URL, reader=FakePagesReader({PAGE_ONE: "guide text", PAGE_TWO: "api text"}))

    await kb.ainsert(url=SITE_URL, reader=EmptyReader({}))

    _assert_pages_survive(kb, vector_db)
    site = _site_row(_rows(kb))
    assert site.status == "failed"
    assert "no documents" in (site.status_message or "")
    # A later healthy refresh reconciles normally
    _clear_writes(vector_db)
    await kb.ainsert(url=SITE_URL, reader=FakePagesReader({PAGE_ONE: "guide text", PAGE_TWO: "api text v2"}))
    assert _site_row(_rows(kb)).status == "completed"
    assert {doc.meta_data["url"] for doc in vector_db.inserted_documents} == {PAGE_TWO}


def test_all_shards_failed_refresh_preserves_pages_sync(vector_db, tmp_path):
    kb = _kb(tmp_path, vector_db)
    kb.insert(url=SITE_URL, reader=FakePagesReader({PAGE_ONE: "guide text", PAGE_TWO: "api text"}))

    kb.insert(url=SITE_URL, reader=EmptyReader({}))

    _assert_pages_survive(kb, vector_db)
    assert _site_row(_rows(kb)).status == "failed"


async def test_root_sitemap_outage_refresh_preserves_pages_async(vector_db, tmp_path):
    kb = _kb(tmp_path, vector_db)
    await kb.ainsert(url=SITE_URL, reader=FakePagesReader({PAGE_ONE: "guide text", PAGE_TWO: "api text"}))

    await kb.ainsert(url=SITE_URL, reader=FallbackOutageReader({}))

    _assert_pages_survive(kb, vector_db)
    site = _site_row(_rows(kb))
    assert "discovery incomplete" in (site.status_message or "")


def test_root_sitemap_outage_refresh_preserves_pages_sync(vector_db, tmp_path):
    kb = _kb(tmp_path, vector_db)
    kb.insert(url=SITE_URL, reader=FakePagesReader({PAGE_ONE: "guide text", PAGE_TWO: "api text"}))

    kb.insert(url=SITE_URL, reader=FallbackOutageReader({}))

    _assert_pages_survive(kb, vector_db)


async def test_vector_delete_false_keeps_row_and_ownership_async(vector_db, tmp_path):
    kb = _kb(tmp_path, vector_db)
    await kb.ainsert(url=SITE_URL, reader=FakePagesReader({PAGE_ONE: "guide text", PAGE_TWO: "api text"}))
    site = _site_row(_rows(kb))
    child_id = get_agno_metadata(site.metadata, "children")[0]

    vector_db.delete_by_content_id = lambda content_id, user_id=None: False
    removed = await kb.aremove_content_by_id(child_id)

    assert removed is False
    assert await kb.aget_content_by_id(child_id) is not None, "the row must stay while its vectors exist"
    site = _site_row(_rows(kb))
    assert child_id in get_agno_metadata(site.metadata, "children"), "ownership must survive a failed delete"


def test_vector_delete_false_keeps_row_and_ownership_sync(vector_db, tmp_path):
    kb = _kb(tmp_path, vector_db)
    kb.insert(url=SITE_URL, reader=FakePagesReader({PAGE_ONE: "guide text", PAGE_TWO: "api text"}))
    site = _site_row(_rows(kb))
    child_id = get_agno_metadata(site.metadata, "children")[0]

    vector_db.delete_by_content_id = lambda content_id, user_id=None: False
    removed = kb.remove_content_by_id(child_id)

    assert removed is False
    assert kb.get_content_by_id(child_id) is not None


async def test_prune_honors_false_returning_adapter(vector_db, tmp_path):
    kb = _kb(tmp_path, vector_db)
    await kb.ainsert(url=SITE_URL, reader=FakePagesReader({PAGE_ONE: "guide text", PAGE_TWO: "api text"}))
    site = _site_row(_rows(kb))
    stale_ids = set(get_agno_metadata(site.metadata, "children"))

    original_delete = vector_db.delete_by_content_id
    vector_db.delete_by_content_id = lambda content_id, user_id=None: False
    await kb.ainsert(url=SITE_URL, reader=FakePagesReader({PAGE_ONE: "guide text"}))
    vector_db.delete_by_content_id = original_delete

    site = _site_row(_rows(kb))
    children = set(get_agno_metadata(site.metadata, "children"))
    assert stale_ids <= children, "a page whose vector delete failed keeps its place for retry"


# ---------------------------------------------------------------------------
# Review round 3: deletion-contract semantics
# ---------------------------------------------------------------------------


from conftest import StubVectorDb  # noqa: E402 - fixture class shared with the suite


class ZeroMatchFalseVectorDb(StubVectorDb):
    """Chroma/LanceDB/Weaviate-shaped: delete_by_content_id answers False when zero
    vectors matched, True when something was deleted."""

    def delete_by_content_id(self, content_id, user_id=None):
        remaining = [doc for doc in self.inserted_documents + self.upserted_documents if doc.content_id != content_id]
        matched = len(remaining) != len(self.inserted_documents) + len(self.upserted_documents)
        self.inserted_documents = [doc for doc in self.inserted_documents if doc.content_id != content_id]
        self.upserted_documents = [doc for doc in self.upserted_documents if doc.content_id != content_id]
        return matched


async def test_vectorless_site_parent_deletes_cleanly_on_zero_match_false_adapter_async(tmp_path):
    vector_db = ZeroMatchFalseVectorDb()
    kb = _kb(tmp_path, vector_db)
    await kb.ainsert(url=SITE_URL, reader=FakePagesReader({PAGE_ONE: "guide text", PAGE_TWO: "api text"}))
    site = _site_row(_rows(kb))

    removed = await kb.aremove_content_by_id(site.id)

    assert removed is True, "a zero-match False on the vectorless parent is a no-op, not a failure"
    rows, count = await kb.aget_content()
    assert count == 0
    assert vector_db.inserted_documents == []


def test_vectorless_site_parent_deletes_cleanly_on_zero_match_false_adapter_sync(tmp_path):
    vector_db = ZeroMatchFalseVectorDb()
    kb = _kb(tmp_path, vector_db)
    kb.insert(url=SITE_URL, reader=FakePagesReader({PAGE_ONE: "guide text", PAGE_TWO: "api text"}))
    site = _site_row(_rows(kb))

    removed = kb.remove_content_by_id(site.id)

    assert removed is True
    rows, count = kb.get_content()
    assert count == 0


async def test_partial_cascade_failure_preserves_parent_async(vector_db, tmp_path):
    kb = _kb(tmp_path, vector_db)
    await kb.ainsert(url=SITE_URL, reader=FakePagesReader({PAGE_ONE: "guide text", PAGE_TWO: "api text"}))
    rows = _rows(kb)
    site = _site_row(rows)
    failing_id = next(row.id for row in rows if get_agno_metadata(row.metadata, "source_url") == PAGE_TWO)

    vector_db.delete_by_content_id = lambda cid, user_id=None: False if cid == failing_id else True
    removed = await kb.aremove_content_by_id(site.id)

    assert removed is False
    site_row = await kb.aget_content_by_id(site.id)
    assert site_row is not None, "the parent stays as the retry anchor"
    assert get_agno_metadata(site_row.metadata, "children") == [failing_id]
    assert await kb.aget_content_by_id(failing_id) is not None

    # Retry with a healthy adapter reconciles fully
    vector_db.delete_by_content_id = lambda cid, user_id=None: True
    assert await kb.aremove_content_by_id(site.id) is True
    _, count = await kb.aget_content()
    assert count == 0


def test_partial_cascade_failure_preserves_parent_sync(vector_db, tmp_path):
    kb = _kb(tmp_path, vector_db)
    kb.insert(url=SITE_URL, reader=FakePagesReader({PAGE_ONE: "guide text", PAGE_TWO: "api text"}))
    rows = _rows(kb)
    site = _site_row(rows)
    failing_id = next(row.id for row in rows if get_agno_metadata(row.metadata, "source_url") == PAGE_TWO)

    vector_db.delete_by_content_id = lambda cid, user_id=None: False if cid == failing_id else True
    removed = kb.remove_content_by_id(site.id)

    assert removed is False
    site_row = kb.get_content_by_id(site.id)
    assert site_row is not None
    assert get_agno_metadata(site_row.metadata, "children") == [failing_id]


async def test_legacy_promotion_aborts_when_clear_fails_async(tmp_path):
    vector_db = ZeroMatchFalseVectorDb()
    kb = _kb(tmp_path, vector_db)
    await kb.ainsert(url=SITE_URL, reader=FakePagesReader({PAGE_ONE: "only page"}))
    row = _rows(kb)[0]

    def failing_clear(content_id, user_id=None):
        raise RuntimeError("adapter down")

    vector_db.delete_by_content_id = failing_clear
    inserted_before = len(vector_db.inserted_documents)
    await kb.ainsert(url=SITE_URL, reader=FakePagesReader({PAGE_ONE: "only page", PAGE_TWO: "second"}))

    refreshed = await kb.aget_content_by_id(row.id)
    assert refreshed.status == "failed"
    assert "previous vectors" in (refreshed.status_message or "")
    assert len(vector_db.inserted_documents) == inserted_before, "no child vectors beside uncleared legacy ones"


def test_legacy_promotion_aborts_when_clear_fails_sync(tmp_path):
    vector_db = ZeroMatchFalseVectorDb()
    kb = _kb(tmp_path, vector_db)
    kb.insert(url=SITE_URL, reader=FakePagesReader({PAGE_ONE: "only page"}))
    row = _rows(kb)[0]

    vector_db.delete_by_content_id = lambda content_id, user_id=None: False  # operational False mid-promotion
    inserted_before = len(vector_db.inserted_documents)
    kb.insert(url=SITE_URL, reader=FakePagesReader({PAGE_ONE: "only page", PAGE_TWO: "second"}))

    refreshed = kb.get_content_by_id(row.id)
    assert refreshed.status == "failed"
    assert len(vector_db.inserted_documents) == inserted_before


async def test_ordinary_reingest_tolerates_zero_match_false_clear(tmp_path):
    vector_db = ZeroMatchFalseVectorDb()
    kb = _kb(tmp_path, vector_db)
    await kb.ainsert(url=SITE_URL, reader=FakePagesReader({PAGE_ONE: "guide text", PAGE_TWO: "api text"}))

    # The site row owns no vectors: its clear answers False and that must not fail the read
    await kb.ainsert(url=SITE_URL, reader=FakePagesReader({PAGE_ONE: "guide text", PAGE_TWO: "api text"}))

    assert _site_row(_rows(kb)).status == "completed"


async def test_remove_all_content_aggregates_failures_async(vector_db, tmp_path):
    kb = _kb(tmp_path, vector_db)
    await kb.ainsert(url=SITE_URL, reader=FakePagesReader({PAGE_ONE: "guide text", PAGE_TWO: "api text"}))
    rows = _rows(kb)
    failing_id = next(row.id for row in rows if get_agno_metadata(row.metadata, "source_url") == PAGE_TWO)

    vector_db.delete_by_content_id = lambda cid, user_id=None: False if cid == failing_id else True
    result = await kb.aremove_all_content()

    assert result is False
    assert await kb.aget_content_by_id(failing_id) is not None

    vector_db.delete_by_content_id = lambda cid, user_id=None: True
    assert await kb.aremove_all_content() is True
    _, count = await kb.aget_content()
    assert count == 0


def test_remove_all_content_aggregates_failures_sync(vector_db, tmp_path):
    kb = _kb(tmp_path, vector_db)
    kb.insert(url=SITE_URL, reader=FakePagesReader({PAGE_ONE: "guide text", PAGE_TWO: "api text"}))
    rows = _rows(kb)
    failing_id = next(row.id for row in rows if get_agno_metadata(row.metadata, "source_url") == PAGE_TWO)

    vector_db.delete_by_content_id = lambda cid, user_id=None: False if cid == failing_id else True
    assert kb.remove_all_content() is False
    assert kb.get_content_by_id(failing_id) is not None


# ---------------------------------------------------------------------------
# Review round 4: persisted vector ownership, failed-first-ingest recovery, async LightRAG
# ---------------------------------------------------------------------------


async def test_text_row_operational_false_keeps_row_async(vector_db, tmp_path):
    kb = _kb(tmp_path, vector_db)
    await kb.ainsert(name="doc", text_content="important text")
    row = _rows(kb)[0]
    assert get_agno_metadata(row.metadata, "vectors_indexed") is True, "successful inserts persist ownership"

    vector_db.delete_by_content_id = lambda cid, user_id=None: False  # operational failure
    removed = await kb.aremove_content_by_id(row.id)

    assert removed is False
    assert await kb.aget_content_by_id(row.id) is not None, "the row must stay while its vectors exist"
    assert await kb.aremove_all_content() is False, "bulk removal reports the failure"


def test_text_row_operational_false_keeps_row_sync(vector_db, tmp_path):
    kb = _kb(tmp_path, vector_db)
    kb.insert(name="doc", text_content="important text")
    row = _rows(kb)[0]

    vector_db.delete_by_content_id = lambda cid, user_id=None: False
    removed = kb.remove_content_by_id(row.id)

    assert removed is False
    assert kb.get_content_by_id(row.id) is not None
    assert kb.remove_all_content() is False


async def test_failed_first_ingest_recovers_on_zero_match_false_adapter_async(tmp_path):
    vector_db = ZeroMatchFalseVectorDb()
    kb = _kb(tmp_path, vector_db)
    # Outage first ingest: FAILED row, no children, no vectors — not a legacy promotion
    await kb.ainsert(url=SITE_URL, reader=EmptyReader({}))
    assert _rows(kb)[0].status == "failed"

    await kb.ainsert(url=SITE_URL, reader=FakePagesReader({PAGE_ONE: "guide text", PAGE_TWO: "api text"}))

    site = _site_row(_rows(kb))
    assert site.status == "completed", "a healthy retry must not be mistaken for a failed legacy clear"
    assert len(get_agno_metadata(site.metadata, "children")) == 2


def test_failed_first_ingest_recovers_on_zero_match_false_adapter_sync(tmp_path):
    vector_db = ZeroMatchFalseVectorDb()
    kb = _kb(tmp_path, vector_db)
    kb.insert(url=SITE_URL, reader=EmptyReader({}))
    assert _rows(kb)[0].status == "failed"

    kb.insert(url=SITE_URL, reader=FakePagesReader({PAGE_ONE: "guide text", PAGE_TWO: "api text"}))

    assert _site_row(_rows(kb)).status == "completed"


class AsyncLightRag:
    """LightRag-shaped adapter: sync delete wrapper uses asyncio.run (fails inside a
    running loop); the async path must await async_delete_by_external_id instead."""

    def __init__(self) -> None:
        self.async_deleted: List[str] = []
        self.delete_result = True

    def exists(self) -> bool:
        return True

    def create(self) -> None:
        return None

    def update_metadata(self, content_id: str, metadata: dict) -> None:
        return None

    def delete_by_external_id(self, external_id: str) -> bool:
        asyncio.run(self._noop())  # what the real adapter does — raises inside a loop
        return True

    async def _noop(self) -> None:
        return None

    async def async_delete_by_external_id(self, external_id: str) -> bool:
        self.async_deleted.append(external_id)
        return self.delete_result


AsyncLightRag.__name__ = "LightRag"


async def test_async_lightrag_removal_awaits_async_delete(tmp_path):
    lightrag = AsyncLightRag()
    kb = Knowledge(name="t", vector_db=lightrag, contents_db=SqliteDb(db_file=str(tmp_path / "c.db")))
    content = Content(name="doc", user_id=None)
    content.content_hash = kb._build_content_hash(content)
    content.id = generate_id(content.content_hash)
    await kb._ainsert_contents_db(content)
    # external_id lands the way the LightRag load path writes it: through the update
    await kb.apatch_content(Content(id=content.id, external_id="ext-1"))

    removed = await kb.aremove_content_by_id(content.id)

    assert removed is True
    assert lightrag.async_deleted == ["ext-1"], "the async path must await async_delete_by_external_id"
    assert await kb.aget_content_by_id(content.id) is None


async def test_async_lightrag_removal_honors_false(tmp_path):
    lightrag = AsyncLightRag()
    lightrag.delete_result = False
    kb = Knowledge(name="t", vector_db=lightrag, contents_db=SqliteDb(db_file=str(tmp_path / "c.db")))
    content = Content(name="doc", user_id=None)
    content.content_hash = kb._build_content_hash(content)
    content.id = generate_id(content.content_hash)
    await kb._ainsert_contents_db(content)
    await kb.apatch_content(Content(id=content.id, external_id="ext-1"))

    removed = await kb.aremove_content_by_id(content.id)

    assert removed is False
    assert await kb.aget_content_by_id(content.id) is not None


# ---------------------------------------------------------------------------
# Post-merge review round: ownership survives aborted promotions
# ---------------------------------------------------------------------------


async def test_aborted_promotion_keeps_ownership_marker_and_guards_retry(vector_db, tmp_path):
    kb = _kb(tmp_path, vector_db)
    await kb.ainsert(url=SITE_URL, reader=FakePagesReader({PAGE_ONE: "legacy text"}))
    legacy_id = _rows(kb)[0].id

    def raising_clear(content_id, user_id=None):
        raise RuntimeError("adapter down")

    vector_db.delete_by_content_id = raising_clear
    await kb.ainsert(url=SITE_URL, reader=FakePagesReader({PAGE_ONE: "legacy text", PAGE_TWO: "second"}))

    row = await kb.aget_content_by_id(legacy_id)
    assert row.status == "failed"
    # The wholesale upsert must not erase the evidence the retry's promotion guard needs
    assert get_agno_metadata(row.metadata, "vectors_indexed") is True

    # A retry with the clear still failing stays guarded — no unguarded COMPLETED
    vector_db.delete_by_content_id = lambda cid, user_id=None: False
    await kb.ainsert(url=SITE_URL, reader=FakePagesReader({PAGE_ONE: "legacy text", PAGE_TWO: "second"}))
    assert (await kb.aget_content_by_id(legacy_id)).status == "failed"

    # A healed clear reconciles to a proper site
    del vector_db.delete_by_content_id
    await kb.ainsert(url=SITE_URL, reader=FakePagesReader({PAGE_ONE: "legacy text", PAGE_TWO: "second"}))
    site = await kb.aget_content_by_id(legacy_id)
    assert site.status == "completed"
    assert len(get_agno_metadata(site.metadata, "children")) == 2


def test_aborted_promotion_keeps_ownership_marker_sync(vector_db, tmp_path):
    kb = _kb(tmp_path, vector_db)
    kb.insert(url=SITE_URL, reader=FakePagesReader({PAGE_ONE: "legacy text"}))
    legacy_id = _rows(kb)[0].id

    vector_db.delete_by_content_id = lambda cid, user_id=None: False
    kb.insert(url=SITE_URL, reader=FakePagesReader({PAGE_ONE: "legacy text", PAGE_TWO: "second"}))

    row = kb.get_content_by_id(legacy_id)
    assert row.status == "failed"
    assert get_agno_metadata(row.metadata, "vectors_indexed") is True
