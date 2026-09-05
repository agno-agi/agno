"""Real transaction tests; each module owns a disposable local database."""

import os
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from agno.db.postgres import PostgresDb
from agno.fs import FileSystem
from agno.knowledge._page_source import PageSource
from agno.knowledge.embedder.base import Embedder
from agno.knowledge.knowledge import Knowledge
from agno.knowledge.page import PageChanged, PageError
from agno.vectordb.pgvector import PgVector

pytestmark = pytest.mark.skipif(not os.getenv("AGNO_PAGE_TEST_DB_URL"), reason="requires isolated local PostgreSQL")


class RecordingEmbedder(Embedder):
    dimensions = 3

    def __init__(self):
        super().__init__(dimensions=3)
        self.calls = []
        self.fail = False

    def get_embedding(self, text, *, timeout=30):
        self.calls.append(text)
        if self.fail:
            raise RuntimeError("secret provider diagnostic")
        return [1.0, 0.5, 0.2]


@pytest.fixture(scope="module")
def engine():
    url = make_url(os.environ["AGNO_PAGE_TEST_DB_URL"])
    assert url.host in ("127.0.0.1", "localhost", "::1")
    admin = create_engine(url, isolation_level="AUTOCOMMIT")
    name = "agno_pages_" + uuid4().hex[:12]
    with admin.connect() as conn:
        conn.execute(text(f'CREATE DATABASE "{name}"'))
    db_engine = create_engine(url.set(database=name), connect_args={"connect_timeout": 3})
    with db_engine.begin() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
    try:
        yield db_engine
    finally:
        db_engine.dispose()
        with admin.connect() as conn:
            conn.execute(text(f'DROP DATABASE "{name}" WITH (FORCE)'))
        admin.dispose()


@pytest.fixture
def corpus(engine, monkeypatch):
    namespace = "test-" + uuid4().hex[:8]
    db = PostgresDb(db_engine=engine)
    embedder = RecordingEmbedder()
    vector = PgVector(db_engine=engine, table_name="page_vectors", embedder=embedder)
    knowledge = Knowledge(
        content_db=db,
        page_store=FileSystem(
            db, namespace=namespace, max_file_bytes=4 * 1024 * 1024, max_namespace_bytes=256 * 1024 * 1024
        ),
        vector_db=vector,
    )
    knowledge.setup()
    site = {
        "https://docs.example.com/llms.txt": "- [Agent](https://docs.example.com/agent.md)",
        "https://docs.example.com/agent.md": "# Agent\n\nUse Agent with tools.\n\n```python\nAgent(tools=[])\n```\n",
    }

    def fetch(self, url, max_bytes):
        return site[url]

    monkeypatch.setattr(PageSource, "fetch", fetch)
    return knowledge, embedder, site


def test_atomic_publication_failed_refresh_and_reconciliation(corpus, monkeypatch):
    knowledge, embedder, site = corpus
    url = "https://docs.example.com/llms.txt"
    report = knowledge.sync_pages(url=url)
    assert report.updated == 1 and report.status == "completed"
    before = knowledge.read_page("/agent")
    count = len(embedder.calls)
    assert knowledge.sync_pages(url=url).status == "unchanged"
    assert len(embedder.calls) == count
    assert knowledge.search_pages("Agent").results[0].revision == before.revision
    assert knowledge.grep_pages("Agent(tools").matches[0].line_number == 6
    assert knowledge.retrieve("Agent", user_id="a-reader")[0].meta_data["revision"] == before.revision
    site["https://docs.example.com/agent.md"] += "\nNew revision.\n"
    original = knowledge.vector_db._replace_page_on

    def fail_after_vector_write(conn, content_id, records):
        original(conn, content_id, records)
        raise RuntimeError("late vector batch failure")

    monkeypatch.setattr(knowledge.vector_db, "_replace_page_on", fail_after_vector_write)
    report = knowledge.sync_pages(url=url)
    assert report.status == "partial" and report.failed == 1
    assert knowledge.read_page("/agent") == before
    page = knowledge.list_pages().pages[0]
    assert knowledge.content_db.get_knowledge_content(page.content_id).status == "failed"
    assert knowledge.search_pages("Agent").results[0].revision == before.revision
    monkeypatch.setattr(knowledge.vector_db, "_replace_page_on", original)
    assert knowledge.sync_pages(url=url).updated == 1
    with pytest.raises(PageChanged):
        knowledge.read_page("/agent", revision=before.revision)
    knowledge.page_store.write("agent.md", "unauthorized direct modification")
    with pytest.raises(PageError):
        knowledge.read_page("/agent")
    assert knowledge.sync_pages(url=url).updated == 1
    assert "New revision" in knowledge.read_page("/agent").text


def test_unicode_pagination_and_listing_revision(corpus):
    knowledge, _, site = corpus
    site["https://docs.example.com/agent.md"] = "# Unicode\n\n" + ('\\"é😀\n' * 10000)
    assert knowledge.sync_pages(url="https://docs.example.com/llms.txt").updated == 1
    parts, offset = [], 0
    while True:
        result = knowledge.read_page("/agent", offset=offset, max_chars=24000)
        assert len(result.model_dump_json().encode()) <= 24000
        parts.append(result.text)
        if result.next_offset is None:
            break
        assert result.next_offset > offset
        offset = result.next_offset
    assert "".join(parts) == site["https://docs.example.com/agent.md"]


def test_initial_failure_and_incomplete_discovery_do_not_prune(corpus):
    knowledge, embedder, site = corpus
    url = "https://docs.example.com/llms.txt"
    embedder.fail = True
    assert knowledge.sync_pages(url=url).failed == 1
    assert knowledge.list_pages().pages == ()
    embedder.fail = False
    assert knowledge.sync_pages(url=url).updated == 1
    site[url] += "\n- [Missing](https://docs.example.com/_llms/missing.md)"
    assert knowledge.sync_pages(url=url).status == "partial"
    assert knowledge.read_page("/agent").text
    with pytest.raises(ValueError):
        knowledge.insert(text_content="must not bypass coordinator")


def test_namespaces_keep_hnsw_recall_and_legacy_search_scoped(corpus, monkeypatch):
    knowledge, embedder, site = corpus
    url = "https://docs.example.com/llms.txt"
    knowledge.sync_pages(url=url)
    monkeypatch.setattr(embedder, "get_embedding", lambda query, *, timeout: [1.0, 0.0, 0.0])
    other = Knowledge(
        content_db=knowledge.content_db,
        vector_db=knowledge.vector_db,
        page_store=FileSystem(knowledge.content_db, namespace="neighbor-" + uuid4().hex[:8]),
    )
    other.setup()
    site[url] = "- [Other](https://docs.example.com/other.md)"
    site["https://docs.example.com/other.md"] = "\n\n".join(
        "## Other " + str(index) + "\n\nOther corpus prose." for index in range(1000)
    )
    assert other.sync_pages(url=url).updated == 1
    for _ in range(8):  # Includes the driver's server-side preparation threshold.
        assert [hit.path for hit in knowledge.search_pages("zzzzzzzz").results] == ["/agent.md"]
    assert all(item.meta_data["path"] == "/agent.md" for item in knowledge.search("zzzzzzzz"))
    other._page_engine.dispose()


def test_metadata_updates_skip_embedding_and_mutation_bypasses_fail(corpus):
    knowledge, embedder, site = corpus
    url = "https://docs.example.com/llms.txt"
    knowledge.sync_pages(url=url)
    page = knowledge.list_pages().pages[0]
    before = len(embedder.calls)
    site[url] = "- [Renamed](https://docs.example.com/agent.md)"
    assert knowledge.sync_pages(url=url).updated == 1
    assert len(embedder.calls) == before
    assert knowledge.read_page("/agent").title == "Renamed"
    with pytest.raises(ValueError):
        from agno.knowledge.content import Content

        knowledge.patch_content(Content(id=page.content_id, metadata={"unsafe": True}))
    assert knowledge.read_page("/agent").revision == page.revision


def test_bounded_pool_preserves_credentials_and_connection_hooks(engine):
    from sqlalchemy import event

    from agno.db.postgres._bounded import bounded_engine

    configured = create_engine(engine.url.set(password=None), connect_args={"password": engine.url.password})

    @event.listens_for(configured, "connect")
    def setup_connection(dbapi_connection, connection_record):
        dbapi_connection.execute("SET application_name='page-configured-hook'")
        dbapi_connection.commit()

    bounded = bounded_engine(configured, capacity=1)
    try:
        with bounded.connect() as conn:
            assert conn.execute(text("SHOW application_name")).scalar_one() == "page-configured-hook"
            assert conn.execute(text("SHOW statement_timeout")).scalar_one() == "30s"
        with configured.connect() as conn:
            assert conn.execute(text("SHOW statement_timeout")).scalar_one() == "0"
    finally:
        bounded.dispose()
        configured.dispose()


def test_two_embedding_pages_and_concurrent_syncs_keep_one_writer(corpus, monkeypatch):
    import threading
    from concurrent.futures import ThreadPoolExecutor

    from sqlalchemy import event

    knowledge, embedder, site = corpus
    base = "https://docs.example.com"
    site[base + "/llms.txt"] += "\n- [Second](" + base + "/second.md)"
    site[base + "/second.md"] = "# Second\n\nA second complete page.\n"
    barrier = threading.Barrier(2)
    embedding_threads, database_threads = set(), set()

    def embed(content, *, timeout):
        embedding_threads.add(threading.get_ident())
        barrier.wait(timeout=3)
        return [1.0, 0.5, 0.2]

    def statement(*args):
        database_threads.add(threading.get_ident())

    monkeypatch.setattr(embedder, "get_embedding", embed)
    event.listen(knowledge._page_engine, "before_cursor_execute", statement)
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(knowledge.sync_pages, url=base + "/llms.txt") for _ in range(2)]
            reports = [future.result(timeout=10) for future in futures]
        assert sorted(report.updated for report in reports) == [0, 2]
        assert len(embedding_threads) == 2
        assert not embedding_threads & database_threads
        assert len(knowledge.list_pages().pages) == 2
    finally:
        event.remove(knowledge._page_engine, "before_cursor_execute", statement)


def test_same_revision_commit_acknowledgement_and_atomic_deletion(corpus, monkeypatch):
    knowledge, _, site = corpus
    base = "https://docs.example.com"
    site[base + "/llms.txt"] += "\n- [Keep](" + base + "/keep.md)"
    site[base + "/keep.md"] = "# Keep\n\nThis page stays published.\n"
    assert knowledge.sync_pages(url=base + "/llms.txt").updated == 2
    before = knowledge.read_page("/agent")
    coordinator = knowledge._pages()
    monkeypatch.setattr(knowledge, "_pages", lambda: coordinator)
    original = coordinator.engine.dialect.do_commit
    lose_ack = {"publication": True, "delete": False}

    def commit(connection):
        original(connection)
        if lose_ack["publication"] and coordinator._pending_publication is not None:
            lose_ack["publication"] = False
            raise RuntimeError("simulated lost acknowledgement after actual COMMIT")
        if lose_ack["delete"]:
            lose_ack["delete"] = False
            raise RuntimeError("simulated lost deletion acknowledgement")

    monkeypatch.setattr(coordinator.engine.dialect, "do_commit", commit)
    report = knowledge.sync_pages(url=base + "/llms.txt", reindex=True)
    assert report.updated == 1 and report.unknown == 0 and report.status == "partial"
    assert knowledge.read_page("/agent").revision == before.revision
    assert "sync_connection_lost" in report.errors
    assert knowledge.sync_pages(url=base + "/llms.txt").status == "unchanged"

    site[base + "/llms.txt"] = "- [Keep](" + base + "/keep.md)"
    delete_file = coordinator.backend._delete_on

    def fail_after_file_delete(conn, namespace, path):
        delete_file(conn, namespace, path)
        raise RuntimeError("late deletion failure")

    monkeypatch.setattr(coordinator.backend, "_delete_on", fail_after_file_delete)
    report = knowledge.sync_pages(url=base + "/llms.txt")
    assert report.failed == 1 and report.deleted == 0
    assert knowledge.read_page("/agent").text == before.text
    assert any(hit.path == "/agent.md" for hit in knowledge.search_pages("Agent").results)

    def delete_with_lost_ack(conn, namespace, path):
        delete_file(conn, namespace, path)
        lose_ack["delete"] = True

    monkeypatch.setattr(coordinator.backend, "_delete_on", delete_with_lost_ack)
    report = knowledge.sync_pages(url=base + "/llms.txt")
    assert report.deleted == 1 and report.unknown == report.failed == 0
    assert report.status == "partial" and "sync_connection_lost" in report.errors
    assert [page.path for page in knowledge.list_pages().pages] == ["/keep.md"]
    assert knowledge.sync_pages(url=base + "/llms.txt").status == "unchanged"


def test_ignore_case_grep_uses_consistent_unicode_folding(corpus):
    knowledge, _, site = corpus
    site["https://docs.example.com/agent.md"] = "# Unicode\n\nİstanbul\nΟΣ\nAgent tools\n"
    knowledge.sync_pages(url="https://docs.example.com/llms.txt")
    for query in ("İstanbul", "ΟΣ", "agent TOOLS"):
        result = knowledge.grep_pages(query, ignore_case=True)
        assert result.complete and len(result.matches) == 1
    assert knowledge.grep_pages("absent", ignore_case=True).matches == ()
