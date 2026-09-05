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
        contents_db=db,
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
    assert knowledge.contents_db.get_knowledge_content(page.content_id).status == "failed"
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


def test_listing_byte_budget_recovers_every_page_with_large_unicode_metadata(corpus):
    knowledge, _, site = corpus
    url = "https://docs.example.com/llms.txt"
    paths = [f"/section/page-{index:03}.md" for index in range(40)]
    site[url] = "\n".join(f"- [Page](https://docs.example.com{path})" for path in paths)
    for path in paths:
        site["https://docs.example.com" + path] = "# " + ('标题 😀 \\"' * 80) + "\n\nPage body.\n"
    assert knowledge.sync_pages(url=url).updated == len(paths)
    cursor, recovered = None, []
    while True:
        result = knowledge.list_pages(prefix="/section/", cursor=cursor, limit=200)
        assert len(result.model_dump_json().encode()) <= 24000
        assert result.pages and not result.restart_required
        recovered.extend(page.path for page in result.pages)
        cursor = result.next_cursor
        if cursor is None:
            break
    assert recovered == paths
    assert knowledge.read_page("/section/page-010").text == site["https://docs.example.com/section/page-010.md"]


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
        contents_db=knowledge.contents_db,
        vector_db=knowledge.vector_db,
        page_store=FileSystem(knowledge.contents_db, namespace="neighbor-" + uuid4().hex[:8]),
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


def test_search_uses_readonly_snapshot_and_restores_transaction_settings(corpus):
    from sqlalchemy import event

    knowledge, _, _ = corpus
    knowledge.sync_pages(url="https://docs.example.com/llms.txt")
    statements, settings = [], []

    def capture(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)
        if "embedding <=>" in statement:
            settings.append(
                tuple(
                    conn.execute(
                        text(
                            "SELECT current_setting('transaction_read_only'), "
                            "current_setting('transaction_isolation'), current_setting('hnsw.ef_search')"
                        )
                    ).one()
                )
            )

    event.listen(knowledge._page_engine, "before_cursor_execute", capture)
    try:
        assert knowledge.search_pages("the and").results
    finally:
        event.remove(knowledge._page_engine, "before_cursor_execute", capture)
    assert settings == [("on", "repeatable read", "200")]
    assert not any("SAVEPOINT" in statement for statement in statements)
    assert len(statements) == 5  # Four search statements and the test's settings inspection.
    with knowledge._page_engine.connect() as conn:
        assert conn.execute(text("SHOW transaction_read_only")).scalar_one() == "off"
        assert conn.execute(text("SHOW enable_seqscan")).scalar_one() == "on"
        assert conn.execute(text("SHOW parallel_setup_cost")).scalar_one() != "0"


def test_search_alternative_sql_failure_keeps_primary_snapshot(corpus, monkeypatch):
    from agno.knowledge.page import SearchUnavailable

    knowledge, _, _ = corpus
    knowledge.sync_pages(url="https://docs.example.com/llms.txt")
    coordinator = knowledge._pages()
    monkeypatch.setattr(knowledge, "_pages", lambda: coordinator)
    original = coordinator._hybrid_sql
    calls = []

    def sql():
        calls.append(None)
        return "SELECT 1 / 0" if len(calls) == 2 else original()

    monkeypatch.setattr(coordinator, "_hybrid_sql", sql)
    result = knowledge.search_pages("Agent", alternatives=["broken", "tools"])
    assert len(calls) == 3
    assert result.results and result.partial and result.warnings == ("alternative_unavailable",)
    monkeypatch.setattr(coordinator, "_hybrid_sql", lambda: "SELECT 1 / 0")
    with pytest.raises(SearchUnavailable):
        knowledge.search_pages("Agent", alternatives=["tools"])


def test_search_alternatives_share_revision_during_concurrent_publication(corpus):
    from sqlalchemy import event

    knowledge, _, site = corpus
    url = "https://docs.example.com/llms.txt"
    knowledge.sync_pages(url=url)
    before = knowledge.read_page("/agent")
    updated = []

    def publish(conn, cursor, statement, parameters, context, executemany):
        if "embedding <=>" in statement and not updated:
            updated.append(True)
            site["https://docs.example.com/agent.md"] += "\nA new published revision.\n"
            assert knowledge.sync_pages(url=url).updated == 1

    event.listen(knowledge._page_engine, "after_cursor_execute", publish)
    try:
        result = knowledge.search_pages("Agent", alternatives=["tools", "configured"])
    finally:
        event.remove(knowledge._page_engine, "after_cursor_execute", publish)
    assert updated and result.results and not result.partial
    assert {hit.revision for hit in result.results} == {before.revision}
    assert knowledge.read_page("/agent").revision != before.revision


def test_point_read_transfers_only_requested_unicode_slice(corpus, monkeypatch):
    knowledge, _, site = corpus
    body = "# Unicode\n\n" + '😀é中\\"\n' * 10000
    site["https://docs.example.com/agent.md"] = body
    knowledge.sync_pages(url="https://docs.example.com/llms.txt")
    coordinator = knowledge._pages()
    monkeypatch.setattr(knowledge, "_pages", lambda: coordinator)
    original = coordinator._rows
    transferred = []

    def rows(*args, **kwargs):
        result = original(*args, **kwargs)
        transferred.extend((len(row.content), row.total_chars) for row in result)
        return result

    monkeypatch.setattr(coordinator, "_rows", rows)
    result = knowledge.read_page("/agent", offset=13, max_chars=19)
    assert result.text == body[13:32]
    assert result.next_offset == 32 and result.total_chars == len(body)
    assert transferred == [(19, len(body))]


def test_parallel_lexical_cutoff_preserves_serial_ties(corpus):
    knowledge, _, site = corpus
    site["https://docs.example.com/agent.md"] = "# Agent\n\n" + "\n\n".join(
        "## Section " + str(index) + "\n\nShared lexical match." for index in range(800)
    )
    assert knowledge.sync_pages(url="https://docs.example.com/llms.txt").updated == 1
    coordinator = knowledge._pages()
    params = {"namespace": coordinator.namespace, "tsquery": "'share'", "vector": "[1,0.5,0.2]"}
    # The serial bitmap scan is the established reference for ties at the
    # 200-candidate boundary. Compare the actual candidate IDs, not just scores.
    serial = (
        f"SELECT id FROM {coordinator._vector_name} WHERE meta_data->>'namespace'=:namespace "
        "AND _agno_page_tsv @@ CAST(:tsquery AS tsquery) "
        "ORDER BY ts_rank_cd(_agno_page_tsv, CAST(:tsquery AS tsquery)) DESC LIMIT 200"
    )
    parallel = coordinator._hybrid_sql().split(", candidates AS", 1)[0] + " SELECT id FROM by_keyword"
    with coordinator._snapshot() as conn:
        conn.execute(text("SET LOCAL enable_seqscan=off; SET LOCAL max_parallel_workers_per_gather=0"))
        expected = list(conn.execute(text(serial), params).scalars())
        assert len(expected) == 200
        conn.execute(
            text(
                "SET LOCAL max_parallel_workers_per_gather=2; SET LOCAL parallel_setup_cost=0; "
                "SET LOCAL parallel_tuple_cost=0; SET LOCAL min_parallel_table_scan_size=0; "
                "SET LOCAL min_parallel_index_scan_size=0"
            )
        )
        assert list(conn.execute(text(parallel), params).scalars()) == expected


@pytest.mark.asyncio
async def test_parallel_phrasings_share_one_snapshot_on_distinct_connections(corpus):
    from threading import Barrier

    from sqlalchemy import event

    knowledge, _, _ = corpus
    await knowledge.async_sync_pages(url="https://docs.example.com/llms.txt")
    rendezvous = Barrier(3)
    observed = []

    def inspect(conn, cursor, statement, parameters, context, executemany):
        if "embedding <=>" not in statement:
            return
        observed.append(
            (
                id(conn.connection.driver_connection),
                conn.execute(text("SELECT txid_current_snapshot()::text")).scalar_one(),
                conn.execute(text("SHOW transaction_read_only")).scalar_one(),
            )
        )
        rendezvous.wait(timeout=1)

    event.listen(knowledge._page_engine, "before_cursor_execute", inspect)
    try:
        result = await knowledge.asearch_pages("Agent", alternatives=["tools", "configuration"])
    finally:
        event.remove(knowledge._page_engine, "before_cursor_execute", inspect)
    assert result.results and not result.partial
    assert len({connection for connection, _, _ in observed}) == 3
    assert len({snapshot for _, snapshot, _ in observed}) == 1
    assert {readonly for _, _, readonly in observed} == {"on"}


def test_search_stays_available_when_parallel_admission_is_full(corpus, monkeypatch):
    from threading import BoundedSemaphore

    from sqlalchemy import event

    import agno.knowledge._pages as pages

    knowledge, _, _ = corpus
    knowledge.sync_pages(url="https://docs.example.com/llms.txt")
    monkeypatch.setattr(pages, "_PARALLEL_SEARCHES", BoundedSemaphore(0))
    connections = []

    def capture(conn, cursor, statement, parameters, context, executemany):
        if "embedding <=>" in statement:
            connections.append(id(conn.connection.driver_connection))

    event.listen(knowledge._page_engine, "before_cursor_execute", capture)
    try:
        result = knowledge.search_pages("Agent", alternatives=["tools", "configuration"])
    finally:
        event.remove(knowledge._page_engine, "before_cursor_execute", capture)
    assert result.results and not result.partial
    assert len(connections) == 3 and len(set(connections)) == 1


@pytest.mark.asyncio
async def test_cancelled_parallel_search_retains_snapshot_and_admission_until_children_exit(corpus):
    import asyncio
    import threading

    from sqlalchemy import event

    import agno.knowledge._pages as pages

    knowledge, _, _ = corpus
    await knowledge.async_sync_pages(url="https://docs.example.com/llms.txt")
    entered, release = threading.Event(), threading.Event()

    def delay(conn, cursor, statement, parameters, context, executemany):
        if "embedding <=>" in statement and threading.current_thread().name.startswith("knowledge-query"):
            entered.set()
            release.wait(timeout=3)

    event.listen(knowledge._page_engine, "after_cursor_execute", delay)
    task = asyncio.create_task(knowledge.asearch_pages("Agent", alternatives=["tools"]))
    try:
        assert await asyncio.to_thread(entered.wait, 1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert pages._PARALLEL_SEARCHES.acquire(blocking=False)
        try:
            assert not pages._PARALLEL_SEARCHES.acquire(blocking=False)
            assert knowledge._page_engine.pool.checkedout() >= 2
        finally:
            pages._PARALLEL_SEARCHES.release()
    finally:
        release.set()
        if not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        for _ in range(100):
            if knowledge._page_engine.pool.checkedout() == 0:
                break
            await asyncio.sleep(0.01)
        event.remove(knowledge._page_engine, "after_cursor_execute", delay)
    assert knowledge._page_engine.pool.checkedout() == 0
    assert pages._PARALLEL_SEARCHES.acquire(blocking=False)
    assert pages._PARALLEL_SEARCHES.acquire(blocking=False)
    pages._PARALLEL_SEARCHES.release()
    pages._PARALLEL_SEARCHES.release()


def test_rrf_ties_keep_primary_query_order_at_result_limit(corpus, monkeypatch):
    from agno.knowledge._pages import PageCoordinator

    knowledge, _, _ = corpus

    def row(ident):
        return {
            "id": ident,
            "file_version": 1,
            "score": 0.8,
            "breadcrumb": ident,
            "content": ident,
            "page": {
                "filesystem_version": 1,
                "path": f"/{ident}.md",
                "url": f"https://docs.example.com/{ident}",
                "title": ident,
                "revision": "r",
            },
        }

    primary, alternative = row("z-primary"), row("a-alternative")
    monkeypatch.setattr(
        PageCoordinator, "_search_queries", lambda *args, **kwargs: [[primary, alternative], [alternative, primary]]
    )
    result = knowledge.search_pages("primary", alternatives=["alternative"], limit=1)
    assert [hit.path for hit in result.results] == ["/z-primary.md"]


def test_search_clipping_accounts_for_partial_warning_bytes(corpus, monkeypatch):
    from agno.knowledge._pages import PageCoordinator
    from agno.knowledge.page import SearchHit, SearchResult, encoded_size

    knowledge, _, _ = corpus
    hit = SearchHit(
        path="/agent.md",
        url="https://docs.example.com/agent",
        title="Agent",
        revision="r",
        chunk_id="c",
        content="",
        score=0.8,
        rank=1,
    )
    overhead = encoded_size(SearchResult(results=(hit,), partial=True, truncated=True))
    content = "x" * (24000 - overhead - 5)
    row = {
        "id": "c",
        "file_version": 1,
        "score": 0.8,
        "breadcrumb": "Agent",
        "content": content,
        "page": {"filesystem_version": 1, "path": hit.path, "url": hit.url, "title": hit.title, "revision": "r"},
    }
    monkeypatch.setattr(
        PageCoordinator, "_search_queries", lambda *args, **kwargs: [[row], RuntimeError("alternative failed")]
    )
    result = knowledge.search_pages("primary", alternatives=["alternative"])
    assert result.partial and result.warnings == ("alternative_unavailable",)
    assert result.truncated and result.omitted_count == 1 and not result.results
    assert encoded_size(result) <= 24000
