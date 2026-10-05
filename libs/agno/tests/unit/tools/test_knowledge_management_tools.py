"""Unit tests for KnowledgeManagementTools and the knowledge REST routes it pairs with.

Section 1 exercises the toolkit against a real Knowledge with a SQLite contents db and a
local stub vector db - no network: the sitemap reader is replaced by patching the toolkit's
_build_reader seam with a fake multi-page Reader.

Section 2 exercises the router-level parent_id filter and the refresh route with a mocked
Knowledge behind FastAPI's TestClient.
"""

from __future__ import annotations

import asyncio
import json
import os
import sqlite3
import tempfile
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agno.db.sqlite import SqliteDb
from agno.knowledge.content import Content, ContentStatus
from agno.knowledge.document import Document
from agno.knowledge.knowledge import Knowledge
from agno.knowledge.reader.base import Reader
from agno.knowledge.types import ContentType
from agno.run import RunContext
from agno.tools.knowledge import KnowledgeManagementTools
from agno.utils.string import generate_id
from agno.vectordb.base import VectorDb

SITE_URL = "https://docs.example.com"
PAGE_A = "https://docs.example.com/a"
PAGE_B = "https://docs.example.com/b"


class StubVectorDb(VectorDb):
    """Local minimal vector db stub; records writes and content-id deletes."""

    def __init__(self) -> None:
        self.writes: List[tuple] = []
        self.deleted_content_ids: List[str] = []

    def create(self) -> None:
        pass

    async def async_create(self) -> None:
        pass

    def name_exists(self, name: str) -> bool:
        return False

    def async_name_exists(self, name: str) -> bool:
        return False

    def id_exists(self, id: str) -> bool:
        return False

    def content_hash_exists(self, content_hash: str, user_id: Optional[str] = None) -> bool:
        return False

    def upsert_available(self) -> bool:
        return False

    def insert(self, content_hash: str, documents: List[Document], filters=None, user_id: Optional[str] = None) -> None:
        self.writes.append((content_hash, user_id))

    async def async_insert(
        self, content_hash: str, documents: List[Document], filters=None, user_id: Optional[str] = None
    ) -> None:
        self.insert(content_hash, documents, filters, user_id)

    def upsert(self, content_hash: str, documents: List[Document], filters=None, user_id: Optional[str] = None) -> None:
        self.writes.append((content_hash, user_id))

    async def async_upsert(
        self, content_hash: str, documents: List[Document], filters=None, user_id: Optional[str] = None
    ) -> None:
        self.upsert(content_hash, documents, filters, user_id)

    def search(self, query: str, limit: int = 5, filters=None, user_id: Optional[str] = None) -> List[Document]:
        return []

    async def async_search(
        self, query: str, limit: int = 5, filters=None, user_id: Optional[str] = None
    ) -> List[Document]:
        return []

    def drop(self) -> None:
        pass

    async def async_drop(self) -> None:
        pass

    def exists(self) -> bool:
        return True

    async def async_exists(self) -> bool:
        return True

    def delete(self) -> bool:
        return True

    def delete_by_id(self, id: str) -> bool:
        return True

    def delete_by_name(self, name: str) -> bool:
        return True

    def delete_by_metadata(self, metadata: Dict[str, Any]) -> bool:
        return True

    def update_metadata(self, content_id: str, metadata: Dict[str, Any]) -> None:
        pass

    def delete_by_content_id(self, content_id: str, user_id: Optional[str] = None) -> bool:
        self.deleted_content_ids.append(content_id)
        return True

    def get_supported_search_types(self) -> List[str]:
        return ["vector"]


class TwoPageReader(Reader):
    """Fake sitemap-style reader: yields one document per page, no network."""

    @classmethod
    def get_supported_content_types(cls) -> List[ContentType]:
        return [ContentType.URL]

    def read(self, obj: Any, name: Optional[str] = None, password: Optional[str] = None) -> List[Document]:
        return [
            Document(content="alpha page text", meta_data={"url": PAGE_A, "extractor": "test"}),
            Document(content="beta page text", meta_data={"url": PAGE_B, "extractor": "test"}),
        ]

    async def async_read(self, obj: Any, name: Optional[str] = None, password: Optional[str] = None) -> List[Document]:
        return self.read(obj, name=name, password=password)


def _make_kb():
    db_file = os.path.join(tempfile.mkdtemp(), "contents.db")
    kb = Knowledge(name="t", vector_db=StubVectorDb(), contents_db=SqliteDb(db_file=db_file))
    return kb, db_file


def _make_toolkit(kb: Knowledge, **kwargs) -> KnowledgeManagementTools:
    # Behaviour tests drive every tool, ingest_path included. The constructor defaults are
    # pinned by the registration tests instead.
    kwargs.setdefault("ingest_path", True)
    toolkit = KnowledgeManagementTools(knowledge=kb, **kwargs)
    toolkit._build_reader = lambda max_pages: TwoPageReader()  # type: ignore[method-assign]
    return toolkit


def _ctx(user_id: Optional[str] = "alice") -> RunContext:
    return RunContext(run_id="r1", session_id="s1", user_id=user_id)


def _rows(db_file: str):
    conn = sqlite3.connect(db_file)
    try:
        return conn.execute("SELECT id, name, user_id, status FROM agno_knowledge").fetchall()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Toolkit: registration
# ---------------------------------------------------------------------------


def test_registration_default_exposes_every_tool_but_ingest_path():
    kb, _ = _make_kb()
    toolkit = KnowledgeManagementTools(knowledge=kb)

    expected = ["ingest_url", "ingest_text", "list_content", "ingest_status", "remove_content"]
    assert list(toolkit.functions.keys()) == expected
    assert list(toolkit.async_functions.keys()) == expected


def test_ingest_path_is_off_by_default_and_opts_in():
    kb, _ = _make_kb()

    assert "ingest_path" not in KnowledgeManagementTools(knowledge=kb).functions

    toolkit = KnowledgeManagementTools(knowledge=kb, ingest_path=True)
    assert "ingest_path" in toolkit.functions
    assert "ingest_path" in toolkit.async_functions


def test_remove_content_requires_confirmation_by_default():
    kb, _ = _make_kb()
    toolkit = KnowledgeManagementTools(knowledge=kb)

    assert toolkit.functions["remove_content"].requires_confirmation is True
    assert toolkit.async_functions["remove_content"].requires_confirmation is True
    # The other tools stay unguarded
    assert not toolkit.functions["ingest_url"].requires_confirmation
    assert not toolkit.functions["list_content"].requires_confirmation


def test_caller_supplied_confirmation_list_keeps_remove_content_gated():
    kb, _ = _make_kb()
    toolkit = KnowledgeManagementTools(knowledge=kb, requires_confirmation_tools=["ingest_url"])

    assert set(toolkit.requires_confirmation_tools) == {"remove_content", "ingest_url"}
    assert toolkit.functions["remove_content"].requires_confirmation is True
    assert toolkit.async_functions["remove_content"].requires_confirmation is True
    assert toolkit.functions["ingest_url"].requires_confirmation is True


def test_remove_content_false_drops_tool_and_sets_no_confirmation_flag():
    kb, _ = _make_kb()
    toolkit = KnowledgeManagementTools(knowledge=kb, remove_content=False)

    assert "remove_content" not in toolkit.functions
    assert "remove_content" not in toolkit.async_functions
    assert toolkit.requires_confirmation_tools == []


def test_ingest_flags_false_drop_the_write_tools():
    kb, _ = _make_kb()
    toolkit = KnowledgeManagementTools(knowledge=kb, ingest_url=False, ingest_text=False)

    assert list(toolkit.functions.keys()) == ["list_content", "ingest_status", "remove_content"]
    assert list(toolkit.async_functions.keys()) == ["list_content", "ingest_status", "remove_content"]


def test_enable_flags_are_gone_and_fail_loudly():
    # 2.x-era enable_* kwargs must not reach Toolkit and be silently ignored — a swallowed
    # enable_ingest=False would register the write tools the caller thinks it disabled.
    kb, _ = _make_kb()
    with pytest.raises(TypeError):
        KnowledgeManagementTools(knowledge=kb, enable_ingest=False)  # type: ignore[call-arg]
    with pytest.raises(TypeError):
        KnowledgeManagementTools(knowledge=kb, enable_remove=False)  # type: ignore[call-arg]


def test_requires_knowledge():
    with pytest.raises(ValueError, match="knowledge"):
        KnowledgeManagementTools(knowledge=None)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Toolkit: ingest_url
# ---------------------------------------------------------------------------


def test_ingest_url_sync_reports_site_and_writes_rows():
    kb, db_file = _make_kb()
    toolkit = _make_toolkit(kb)

    report = json.loads(toolkit.ingest_url(_ctx(), SITE_URL))

    assert report["ok"] is True
    assert report["status"] == "completed"
    assert report["pages"] == 2
    assert report["failed"] == []
    assert report["extractors"] == {"test": 2}
    assert report["page_rows"] == 2
    assert isinstance(report["seconds"], (int, float))

    rows = _rows(db_file)
    assert len(rows) == 3  # one site row + two page rows
    assert report["site_id"] in {row[0] for row in rows}
    site_row = kb.get_content_by_id(report["site_id"])
    assert site_row is not None
    assert site_row.name == "docs.example.com"


def test_ingest_url_shared_scope_writes_owner_none_even_with_run_user():
    kb, db_file = _make_kb()
    toolkit = _make_toolkit(kb)  # scope defaults to "shared"

    report = json.loads(toolkit.ingest_url(_ctx(user_id="alice"), SITE_URL))

    assert report["ok"] is True
    assert all(row[2] is None for row in _rows(db_file))
    site_row = kb.get_content_by_id(report["site_id"])
    assert site_row is not None and site_row.user_id is None


def test_ingest_url_user_scope_writes_run_user_id():
    kb, db_file = _make_kb()
    toolkit = _make_toolkit(kb, scope="user")

    report = json.loads(toolkit.ingest_url(_ctx(user_id="alice"), SITE_URL))

    assert report["ok"] is True
    rows = _rows(db_file)
    assert len(rows) == 3
    assert all(row[2] == "alice" for row in rows)
    site_row = kb.get_content_by_id(report["site_id"], user_id="alice")
    assert site_row is not None and site_row.user_id == "alice"


def test_aingest_url_reports_site_and_writes_rows():
    kb, db_file = _make_kb()
    toolkit = _make_toolkit(kb)

    report = json.loads(asyncio.run(toolkit.aingest_url(_ctx(), SITE_URL)))

    assert report["ok"] is True
    assert report["pages"] == 2
    assert report["extractors"] == {"test": 2}
    assert "seconds" in report
    rows = _rows(db_file)
    assert len(rows) == 3
    assert report["site_id"] in {row[0] for row in rows}


def test_aingest_url_user_scope_writes_run_user_id():
    kb, db_file = _make_kb()
    toolkit = _make_toolkit(kb, scope="user")

    report = json.loads(asyncio.run(toolkit.aingest_url(_ctx(user_id="alice"), SITE_URL)))

    assert report["ok"] is True
    assert all(row[2] == "alice" for row in _rows(db_file))


# ---------------------------------------------------------------------------
# Toolkit: ingest_text
# ---------------------------------------------------------------------------


def test_ingest_text_sync_lands_named_row():
    kb, db_file = _make_kb()
    toolkit = _make_toolkit(kb)

    report = json.loads(toolkit.ingest_text(_ctx(), name="mydoc", text="hello world"))

    assert report["ok"] is True
    assert report["name"] == "mydoc"
    rows = _rows(db_file)
    assert len(rows) == 1
    assert rows[0][1] == "mydoc"
    assert rows[0][3] == "completed"
    assert rows[0][2] is None  # shared scope


def test_aingest_text_lands_named_row_with_user_scope():
    kb, db_file = _make_kb()
    toolkit = _make_toolkit(kb, scope="user")

    report = json.loads(asyncio.run(toolkit.aingest_text(_ctx(user_id="alice"), name="mydoc", text="hello world")))

    assert report["ok"] is True
    rows = _rows(db_file)
    assert len(rows) == 1
    assert rows[0][1] == "mydoc"
    assert rows[0][2] == "alice"


def test_ingest_text_returned_id_matches_db_row():
    kb, db_file = _make_kb()
    toolkit = _make_toolkit(kb)

    sync_report = json.loads(toolkit.ingest_text(_ctx(), name="mydoc", text="hello world"))
    async_report = json.loads(asyncio.run(toolkit.aingest_text(_ctx(), name="otherdoc", text="hello again")))

    row_ids = {row[0] for row in _rows(db_file)}
    assert sync_report["id"] in row_ids
    assert async_report["id"] in row_ids


# ---------------------------------------------------------------------------
# Toolkit: list_content
# ---------------------------------------------------------------------------


def test_list_content_groups_pages_under_site():
    kb, _ = _make_kb()
    toolkit = _make_toolkit(kb)
    report = json.loads(toolkit.ingest_url(_ctx(), SITE_URL))

    listing = json.loads(toolkit.list_content(_ctx()))

    assert listing["total_rows"] == 3
    assert listing["other"] == []  # page rows are grouped away, never listed as other
    assert len(listing["sites"]) == 1
    site = listing["sites"][0]
    assert site["site_id"] == report["site_id"]
    assert site["name"] == "docs.example.com"
    assert site["pages"] == 2
    assert site["failed"] == 0
    assert site["status"] == "completed"


def test_list_content_host_filter():
    kb, _ = _make_kb()
    toolkit = _make_toolkit(kb)
    toolkit.ingest_url(_ctx(), SITE_URL)

    match = json.loads(toolkit.list_content(_ctx(), host="docs.example.com"))
    assert len(match["sites"]) == 1

    miss = json.loads(toolkit.list_content(_ctx(), host="nope.example.org"))
    assert miss["sites"] == []


def test_alist_content_groups_pages_under_site():
    kb, _ = _make_kb()
    toolkit = _make_toolkit(kb)
    toolkit.ingest_url(_ctx(), SITE_URL)

    listing = json.loads(asyncio.run(toolkit.alist_content(_ctx())))

    assert listing["total_rows"] == 3
    assert len(listing["sites"]) == 1
    assert listing["sites"][0]["pages"] == 2


# ---------------------------------------------------------------------------
# Toolkit: ingest_status
# ---------------------------------------------------------------------------


def test_ingest_status_reports_site():
    kb, _ = _make_kb()
    toolkit = _make_toolkit(kb)
    report = json.loads(toolkit.ingest_url(_ctx(), SITE_URL))

    status = json.loads(toolkit.ingest_status(_ctx(), report["site_id"]))

    assert status["ok"] is True
    assert status["site_id"] == report["site_id"]
    assert status["status"] == "completed"
    assert status["status_message"] == "2 of 2 pages loaded"
    assert status["pages"] == 2
    assert status["failed"] == []
    assert status["extractors"] == {"test": 2}


def test_ingest_status_unknown_id_returns_error_envelope():
    kb, _ = _make_kb()
    toolkit = _make_toolkit(kb)

    status = json.loads(toolkit.ingest_status(_ctx(), "no-such-id"))
    assert status == {"ok": False, "error": "content no-such-id not found"}

    astatus = json.loads(asyncio.run(toolkit.aingest_status(_ctx(), "no-such-id")))
    assert astatus == {"ok": False, "error": "content no-such-id not found"}


# ---------------------------------------------------------------------------
# Toolkit: remove_content
# ---------------------------------------------------------------------------


def test_remove_content_deletes_site_and_children():
    kb, db_file = _make_kb()
    toolkit = _make_toolkit(kb)
    report = json.loads(toolkit.ingest_url(_ctx(), SITE_URL))
    assert len(_rows(db_file)) == 3

    removed = json.loads(toolkit.remove_content(_ctx(), report["site_id"]))

    assert removed["ok"] is True
    assert removed["removed"] == report["site_id"]
    assert removed["name"] == "docs.example.com"
    assert _rows(db_file) == []


def test_aremove_content_deletes_site_and_children():
    kb, db_file = _make_kb()
    toolkit = _make_toolkit(kb)
    report = json.loads(toolkit.ingest_url(_ctx(), SITE_URL))

    removed = json.loads(asyncio.run(toolkit.aremove_content(_ctx(), report["site_id"])))

    assert removed["ok"] is True
    assert _rows(db_file) == []


def test_remove_content_unknown_id_returns_error_envelope():
    kb, _ = _make_kb()
    toolkit = _make_toolkit(kb)

    removed = json.loads(toolkit.remove_content(_ctx(), "no-such-id"))
    assert removed == {"ok": False, "error": "content no-such-id not found"}

    aremoved = json.loads(asyncio.run(toolkit.aremove_content(_ctx(), "no-such-id")))
    assert aremoved == {"ok": False, "error": "content no-such-id not found"}


# ---------------------------------------------------------------------------
# Toolkit: error envelopes, never raises
# ---------------------------------------------------------------------------


def test_list_content_error_returns_envelope():
    kb, _ = _make_kb()
    toolkit = _make_toolkit(kb)

    def boom(**kwargs):
        raise RuntimeError("db exploded")

    kb.get_content = boom  # type: ignore[method-assign]
    result = json.loads(toolkit.list_content(_ctx()))
    assert result == {"ok": False, "error": "db exploded"}


def test_alist_content_error_returns_envelope():
    kb, _ = _make_kb()
    toolkit = _make_toolkit(kb)

    async def aboom(**kwargs):
        raise RuntimeError("db exploded")

    kb.aget_content = aboom  # type: ignore[method-assign]
    result = json.loads(asyncio.run(toolkit.alist_content(_ctx())))
    assert result == {"ok": False, "error": "db exploded"}


def test_ingest_url_error_returns_envelope():
    kb, _ = _make_kb()
    toolkit = _make_toolkit(kb)

    def boom(**kwargs):
        raise RuntimeError("reader blew up")

    kb.insert = boom  # type: ignore[method-assign]
    result = json.loads(toolkit.ingest_url(_ctx(), SITE_URL))
    assert result == {"ok": False, "error": "reader blew up"}


def test_ingest_text_error_returns_envelope():
    kb, _ = _make_kb()
    toolkit = _make_toolkit(kb)

    def boom(**kwargs):
        raise RuntimeError("insert failed")

    kb.insert = boom  # type: ignore[method-assign]
    result = json.loads(toolkit.ingest_text(_ctx(), name="mydoc", text="hello"))
    assert result == {"ok": False, "error": "insert failed"}


def test_ingest_status_error_returns_envelope():
    kb, _ = _make_kb()
    toolkit = _make_toolkit(kb)

    def boom(*args, **kwargs):
        raise RuntimeError("lookup failed")

    kb.get_content_by_id = boom  # type: ignore[method-assign]
    result = json.loads(toolkit.ingest_status(_ctx(), "some-id"))
    assert result == {"ok": False, "error": "lookup failed"}


def test_remove_content_error_returns_envelope():
    kb, _ = _make_kb()
    toolkit = _make_toolkit(kb)
    report = json.loads(toolkit.ingest_url(_ctx(), SITE_URL))

    def boom(*args, **kwargs):
        raise RuntimeError("delete failed")

    kb.remove_content_by_id = boom  # type: ignore[method-assign]
    result = json.loads(toolkit.remove_content(_ctx(), report["site_id"]))
    assert result == {"ok": False, "error": "delete failed"}


# ===========================================================================
# REST routes: parent_id filter and refresh
# ===========================================================================


def _mock_router_knowledge() -> MagicMock:
    mock = MagicMock(spec=Knowledge)
    mock.name = "test-kb"
    mock.id = "test-kb-id"
    mock.db_id = "test-db"
    mock.knowledge_id = "test-kb-id"
    mock.aget_content = AsyncMock(return_value=([], 0))
    return mock


def _build_client(knowledge: MagicMock) -> TestClient:
    from agno.os.routers.knowledge import get_knowledge_router
    from agno.os.settings import AgnoAPISettings

    app = FastAPI()
    router = get_knowledge_router(knowledge_instances=[knowledge], settings=AgnoAPISettings())
    app.include_router(router)
    return TestClient(app)


def _content(content_id: str, name: str, metadata: Optional[Dict[str, Any]] = None, user_id: Optional[str] = None):
    return Content(
        id=content_id,
        name=name,
        metadata=metadata,
        status=ContentStatus.COMPLETED,
        user_id=user_id,
        created_at=1700000000,
        updated_at=1700000000,
    )


class TestGetContentParentIdFilter:
    def _knowledge_with_rows(self):
        site = _content("site-1", "docs.example.com", metadata={"_agno": {"children": ["page-a", "page-b"]}})
        page_a = _content("page-a", "docs.example.com/a", metadata={"_agno": {"parent_id": "site-1"}})
        page_b = _content("page-b", "docs.example.com/b", metadata={"_agno": {"parent_id": "site-1"}})
        stray = _content("page-x", "other.example.com/x", metadata={"_agno": {"parent_id": "site-2"}})
        loose = _content("doc-1", "loose-doc", metadata={"foo": "bar"})
        rows = [site, page_a, page_b, stray, loose]
        knowledge = _mock_router_knowledge()
        knowledge.aget_content = AsyncMock(return_value=(rows, len(rows)))
        return knowledge

    def test_parent_id_returns_only_matching_page_rows(self):
        knowledge = self._knowledge_with_rows()
        client = _build_client(knowledge)

        response = client.get("/knowledge/content?parent_id=site-1")

        assert response.status_code == 200
        body = response.json()
        assert [entry["id"] for entry in body["data"]] == ["page-a", "page-b"]
        assert body["meta"]["total_count"] == 2

        # The route fetches every row for the base and filters in the route
        call_kwargs = knowledge.aget_content.call_args.kwargs
        assert "limit" not in call_kwargs

    def test_parent_id_no_match_returns_empty(self):
        knowledge = self._knowledge_with_rows()
        client = _build_client(knowledge)

        response = client.get("/knowledge/content?parent_id=site-404")

        assert response.status_code == 200
        body = response.json()
        assert body["data"] == []
        assert body["meta"]["total_count"] == 0

    def test_parent_id_filter_paginates_but_counts_all_matches(self):
        knowledge = self._knowledge_with_rows()
        client = _build_client(knowledge)

        response = client.get("/knowledge/content?parent_id=site-1&limit=1&page=2")

        assert response.status_code == 200
        body = response.json()
        assert [entry["id"] for entry in body["data"]] == ["page-b"]
        assert body["meta"]["total_count"] == 2

    def test_without_parent_id_all_rows_returned(self):
        knowledge = self._knowledge_with_rows()
        client = _build_client(knowledge)

        response = client.get("/knowledge/content")

        assert response.status_code == 200
        body = response.json()
        assert len(body["data"]) == 5
        assert body["meta"]["total_count"] == 5


class TestRefreshContentRoute:
    def test_refresh_unknown_content_returns_404(self):
        knowledge = _mock_router_knowledge()
        knowledge.aget_content_by_id = AsyncMock(return_value=None)
        client = _build_client(knowledge)

        response = client.post("/knowledge/content/no-such-id/refresh")

        assert response.status_code == 404

    def test_refresh_row_without_source_url_returns_400(self):
        knowledge = _mock_router_knowledge()
        existing = _content("doc-1", "loose-doc", metadata={"foo": "bar"})
        knowledge.aget_content_by_id = AsyncMock(return_value=existing)
        client = _build_client(knowledge)

        response = client.post("/knowledge/content/doc-1/refresh")

        assert response.status_code == 400

    def test_refresh_reconstructable_row_schedules_background_ingest(self):
        content_hash = "stable-hash"
        content_id = generate_id(content_hash)
        knowledge = _mock_router_knowledge()
        knowledge._build_content_hash = MagicMock(return_value=content_hash)
        existing = _content(
            content_id,
            "docs.example.com",
            metadata={"_agno": {"source_url": SITE_URL, "source_type": "sitemap"}},
        )
        knowledge.aget_content_by_id = AsyncMock(return_value=existing)
        client = _build_client(knowledge)

        with patch("agno.os.routers.knowledge.knowledge.process_content", new=AsyncMock()) as process_content:
            response = client.post(f"/knowledge/content/{content_id}/refresh")

        assert response.status_code == 202
        body = response.json()
        assert body["id"] == content_id
        assert body["status"] == "processing"

        # The background task re-ingests the reconstructed Content through the sitemap reader
        process_content.assert_awaited_once()
        args = process_content.await_args.args
        assert args[0] is knowledge
        reconstructed = args[1]
        assert reconstructed.url == SITE_URL
        assert reconstructed.id == content_id
        assert args[2] == "sitemap"

    def test_refresh_unmatchable_row_returns_400(self):
        # The stored id cannot be reproduced from the row's fields -> explicit 400, no task
        knowledge = _mock_router_knowledge()
        knowledge._build_content_hash = MagicMock(return_value="different-hash")
        existing = _content(
            "id-that-wont-match",
            "docs.example.com",
            metadata={"_agno": {"source_url": SITE_URL}},
        )
        knowledge.aget_content_by_id = AsyncMock(return_value=existing)
        client = _build_client(knowledge)

        with patch("agno.os.routers.knowledge.knowledge.process_content", new=AsyncMock()) as process_content:
            response = client.post("/knowledge/content/id-that-wont-match/refresh")

        assert response.status_code == 400
        process_content.assert_not_awaited()


# ---------------------------------------------------------------------------
# Review-round hardening: fail-closed scope, honest envelopes, reader identity
# ---------------------------------------------------------------------------


def test_user_scope_without_user_id_fails_closed():
    kb, db_file = _make_kb()
    toolkit = _make_toolkit(kb, scope="user")

    report = json.loads(asyncio.run(toolkit.aingest_text(_ctx(user_id=None), name="secret", text="private notes")))

    def rows_or_empty():
        try:
            return _rows(db_file)
        except sqlite3.OperationalError:
            return []  # nothing was ever written, so the table does not exist

    assert report["ok"] is False
    assert "user_id" in report["error"]
    assert rows_or_empty() == [], "nothing may land in the shared bucket when user scope has no user"
    sync_report = json.loads(toolkit.ingest_text(_ctx(user_id=None), name="secret", text="private notes"))
    assert sync_report["ok"] is False and rows_or_empty() == []


def test_ingest_text_reports_failed_row():
    kb, db_file = _make_kb()
    toolkit = _make_toolkit(kb)

    def failing_insert(*args, **kwargs):
        raise RuntimeError("embed down")

    kb.vector_db.insert = failing_insert
    kb.vector_db.async_insert = failing_insert

    report = json.loads(toolkit.ingest_text(_ctx(), name="doomed", text="text"))

    assert report["ok"] is False, "a FAILED row must not be reported as ok"
    rows = _rows(db_file)
    assert rows and rows[0][1] == "doomed"


def test_remove_content_reports_refused_delete():
    kb, db_file = _make_kb()
    # A shared row (user_id None): core refuses a scoped delete of shared content
    kb.insert(name="shared-doc", text_content="for everyone", user_id=None)
    toolkit = _make_toolkit(kb, scope="user")
    row_id = _rows(db_file)[0][0]

    report = json.loads(toolkit.remove_content(_ctx(user_id="alice"), row_id))

    assert report["ok"] is False
    assert "not removed" in report["error"]
    assert _rows(db_file), "the shared row must still exist"


class TestRefreshReaderIdentity:
    def test_refresh_uses_recorded_reader_id(self):
        content_hash = "stable-hash"
        content_id = generate_id(content_hash)
        knowledge = _mock_router_knowledge()
        knowledge._build_content_hash = MagicMock(return_value=content_hash)
        existing = _content(
            content_id,
            "x.com",
            metadata={"_agno": {"source_url": "https://x.com/llms.txt", "source_type": "url", "reader_id": "llms_txt"}},
        )
        knowledge.aget_content_by_id = AsyncMock(return_value=existing)
        client = _build_client(knowledge)

        with patch("agno.os.routers.knowledge.knowledge.process_content", new=AsyncMock()) as process_content:
            response = client.post(f"/knowledge/content/{content_id}/refresh")

        assert response.status_code == 202
        assert process_content.await_args.args[2] == "llms_txt"

    def test_refresh_without_reader_record_refuses_to_guess(self):
        content_hash = "stable-hash"
        content_id = generate_id(content_hash)
        knowledge = _mock_router_knowledge()
        knowledge._build_content_hash = MagicMock(return_value=content_hash)
        # An llms.txt-shaped row with no reader record: guessing would rewrite the site
        existing = _content(
            content_id,
            "x.com",
            metadata={"_agno": {"source_url": "https://x.com/llms.txt", "source_type": "url"}},
        )
        knowledge.aget_content_by_id = AsyncMock(return_value=existing)
        client = _build_client(knowledge)

        response = client.post(f"/knowledge/content/{content_id}/refresh")

        assert response.status_code == 400
        assert "re-ingest" in response.json()["detail"]


def test_toolkit_rejects_vector_only_knowledge():
    knowledge = Knowledge(name="vector-only", vector_db=StubVectorDb())

    with pytest.raises(ValueError, match="contents_db"):
        KnowledgeManagementTools(knowledge=knowledge)


def test_remove_content_reports_vector_store_failure():
    kb, _ = _make_kb()
    toolkit = _make_toolkit(kb)
    report = json.loads(toolkit.ingest_url(_ctx(), SITE_URL))

    kb.vector_db.delete_by_content_id = lambda content_id, user_id=None: False
    result = json.loads(toolkit.remove_content(_ctx(), report["site_id"]))

    assert result["ok"] is False
    assert "vector store failed" in result["error"]


class TestDeleteContentRouteVectorFailure:
    def test_delete_returns_500_when_vector_delete_fails(self):
        knowledge = _mock_router_knowledge()
        existing = _content("row-1", "docs.example.com", metadata={})
        knowledge.aget_content_by_id = AsyncMock(return_value=existing)
        knowledge.aremove_content_by_id = AsyncMock(return_value=False)
        client = _build_client(knowledge)

        response = client.delete("/knowledge/content/row-1")

        assert response.status_code == 500
        assert "vector deletion failed" in response.json()["detail"]

    def test_delete_succeeds_when_removal_reports_true(self):
        knowledge = _mock_router_knowledge()
        existing = _content("row-1", "docs.example.com", metadata={})
        knowledge.aget_content_by_id = AsyncMock(return_value=existing)
        knowledge.aremove_content_by_id = AsyncMock(return_value=True)
        client = _build_client(knowledge)

        response = client.delete("/knowledge/content/row-1")

        assert response.status_code == 200


class TestDeleteAllRouteAggregation:
    def test_delete_all_returns_500_when_any_removal_fails(self):
        knowledge = _mock_router_knowledge()
        knowledge.aremove_all_content = AsyncMock(return_value=False)
        client = _build_client(knowledge)

        response = client.delete("/knowledge/content")

        assert response.status_code == 500
        assert "not fully removed" in response.json()["detail"]

    def test_delete_all_succeeds_when_aggregate_is_true(self):
        knowledge = _mock_router_knowledge()
        knowledge.aremove_all_content = AsyncMock(return_value=True)
        client = _build_client(knowledge)

        response = client.delete("/knowledge/content")

        assert response.status_code == 200
        assert response.json() == "success"


class TestRemoteParentIdFilter:
    def test_parent_id_on_remote_knowledge_returns_501(self):
        from agno.remote.base import RemoteKnowledge

        knowledge = MagicMock(spec=RemoteKnowledge)
        knowledge.name = "remote"
        knowledge.id = "remote-kb"
        knowledge.db_id = None
        knowledge.knowledge_id = "remote-kb"
        client = _build_client(knowledge)

        response = client.get("/knowledge/content", params={"parent_id": "site-1"})

        assert response.status_code == 501
        assert "parent_id" in response.json()["detail"]


# ===========================================================================
# ingest_path (files and folders) and refresh-by-path
# ===========================================================================


def _make_folder() -> str:
    folder = tempfile.mkdtemp()
    with open(os.path.join(folder, "a.txt"), "w") as handle:
        handle.write("alpha file text")
    with open(os.path.join(folder, "b.txt"), "w") as handle:
        handle.write("beta file text")
    return folder


def test_ingest_path_folder_sync_reports_and_writes_rows():
    kb, db_file = _make_kb()
    toolkit = _make_toolkit(kb)
    folder = _make_folder()

    report = json.loads(toolkit.ingest_path(_ctx(), folder))

    assert report["ok"] is True
    assert report["status"] == "completed"
    assert report["status_message"] == "2 of 2 files loaded"
    assert report["pages"] == 2
    assert report["page_rows"] == 2
    assert report["failed"] == []
    assert isinstance(report["seconds"], (int, float))

    rows = _rows(db_file)
    assert len(rows) == 3  # one folder row + two file rows
    assert report["site_id"] in {row[0] for row in rows}
    folder_row = kb.get_content_by_id(report["site_id"])
    assert folder_row is not None
    assert folder_row.name == os.path.basename(folder)
    assert {row[1] for row in rows} == {os.path.basename(folder), "a.txt", "b.txt"}


def test_aingest_path_folder_reports_and_writes_rows():
    kb, db_file = _make_kb()
    toolkit = _make_toolkit(kb)
    folder = _make_folder()

    report = json.loads(asyncio.run(toolkit.aingest_path(_ctx(), folder)))

    assert report["ok"] is True
    assert report["status_message"] == "2 of 2 files loaded"
    assert report["pages"] == 2
    assert report["page_rows"] == 2
    assert "seconds" in report
    rows = _rows(db_file)
    assert len(rows) == 3
    assert report["site_id"] in {row[0] for row in rows}


def test_ingest_path_single_file_reports_matching_row():
    kb, db_file = _make_kb()
    toolkit = _make_toolkit(kb)
    file_path = os.path.join(tempfile.mkdtemp(), "solo.txt")
    with open(file_path, "w") as handle:
        handle.write("solo file text")

    report = json.loads(toolkit.ingest_path(_ctx(), file_path))

    assert report["ok"] is True
    assert report["status"] == "completed"
    # A single file has no children, so the folder-only fields stay unset.
    assert report["pages"] is None
    assert "page_rows" not in report
    rows = _rows(db_file)
    assert len(rows) == 1
    assert report["site_id"] == rows[0][0]
    assert report["name"] == rows[0][1] == "solo.txt"


def test_aingest_path_single_file_reports_matching_row():
    kb, db_file = _make_kb()
    toolkit = _make_toolkit(kb)
    file_path = os.path.join(tempfile.mkdtemp(), "solo.txt")
    with open(file_path, "w") as handle:
        handle.write("solo file text")

    report = json.loads(asyncio.run(toolkit.aingest_path(_ctx(), file_path)))

    assert report["ok"] is True
    rows = _rows(db_file)
    assert len(rows) == 1
    assert report["site_id"] == rows[0][0]


def test_ingest_path_user_scope_writes_run_user_id():
    kb, db_file = _make_kb()
    toolkit = _make_toolkit(kb, scope="user")
    folder = _make_folder()

    report = json.loads(toolkit.ingest_path(_ctx(user_id="alice"), folder))

    assert report["ok"] is True
    rows = _rows(db_file)
    assert len(rows) == 3
    assert all(row[2] == "alice" for row in rows)
    folder_row = kb.get_content_by_id(report["site_id"], user_id="alice")
    assert folder_row is not None and folder_row.user_id == "alice"


def test_ingest_path_missing_path_returns_error_envelope():
    kb, db_file = _make_kb()
    toolkit = _make_toolkit(kb)
    missing = os.path.join(tempfile.mkdtemp(), "gone")
    predicted = toolkit._predict_path_row_id(missing, None)

    def rows_or_empty():
        try:
            return _rows(db_file)
        except sqlite3.OperationalError:
            return []  # nothing was ever written, so the table does not exist

    # The toolkit pre-checks existence and names the real problem, writing nothing
    report = json.loads(toolkit.ingest_path(_ctx(), missing))
    assert report == {"ok": False, "error": f"path does not exist: {missing}"}
    assert rows_or_empty() == []

    areport = json.loads(asyncio.run(toolkit.aingest_path(_ctx(), missing)))
    assert areport == {"ok": False, "error": f"path does not exist: {missing}"}
    assert rows_or_empty() == []
    assert predicted  # id prediction stays stable for callers that stored it


def test_ingest_path_error_returns_envelope():
    kb, _ = _make_kb()
    toolkit = _make_toolkit(kb)

    def boom(**kwargs):
        raise RuntimeError("disk exploded")

    kb.insert = boom  # type: ignore[method-assign]
    real_dir = tempfile.mkdtemp()
    result = json.loads(toolkit.ingest_path(_ctx(), real_dir))
    assert result == {"ok": False, "error": "disk exploded"}


def test_list_content_groups_folder_like_site():
    kb, _ = _make_kb()
    toolkit = _make_toolkit(kb)
    folder = _make_folder()
    report = json.loads(toolkit.ingest_path(_ctx(), folder))

    listing = json.loads(toolkit.list_content(_ctx()))

    assert listing["total_rows"] == 3
    assert listing["other"] == []  # file rows are grouped away, never listed as other
    assert len(listing["sites"]) == 1
    site = listing["sites"][0]
    assert site["site_id"] == report["site_id"]
    assert site["name"] == os.path.basename(folder)
    assert site["pages"] == 2
    assert site["failed"] == 0
    assert site["status"] == "completed"


class TestRefreshByPathRoute:
    def test_refresh_path_row_schedules_background_ingest(self):
        content_hash = "stable-hash"
        content_id = generate_id(content_hash)
        knowledge = _mock_router_knowledge()
        knowledge._build_content_hash = MagicMock(return_value=content_hash)
        existing = _content(
            content_id,
            "product-docs",
            metadata={"_agno": {"source_path": "/data/product-docs", "source_type": "folder"}},
        )
        knowledge.aget_content_by_id = AsyncMock(return_value=existing)
        client = _build_client(knowledge)

        with patch("agno.os.routers.knowledge.knowledge.process_content", new=AsyncMock()) as process_content:
            response = client.post(f"/knowledge/content/{content_id}/refresh")

        assert response.status_code == 202
        body = response.json()
        assert body["id"] == content_id
        assert body["status"] == "processing"

        # The background task re-ingests the reconstructed Content from its recorded path
        process_content.assert_awaited_once()
        args = process_content.await_args.args
        assert args[0] is knowledge
        reconstructed = args[1]
        assert reconstructed.path == "/data/product-docs"
        assert reconstructed.url is None
        assert reconstructed.id == content_id
        assert reconstructed.user_id is None
        assert reconstructed.metadata is None  # only _agno bookkeeping was stored
        # Path refreshes pick readers by file extension, never a recorded URL reader
        assert args[2] is None

    def test_refresh_unmatchable_path_row_returns_400(self):
        # The stored id cannot be reproduced from the row's fields -> explicit 400, no task
        knowledge = _mock_router_knowledge()
        knowledge._build_content_hash = MagicMock(return_value="different-hash")
        existing = _content(
            "path-id-that-wont-match",
            "product-docs",
            metadata={"_agno": {"source_path": "/data/product-docs"}},
        )
        knowledge.aget_content_by_id = AsyncMock(return_value=existing)
        client = _build_client(knowledge)

        with patch("agno.os.routers.knowledge.knowledge.process_content", new=AsyncMock()) as process_content:
            response = client.post("/knowledge/content/path-id-that-wont-match/refresh")

        assert response.status_code == 400
        assert "re-ingest the path" in response.json()["detail"]
        process_content.assert_not_awaited()
