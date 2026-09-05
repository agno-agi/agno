"""Real transaction tests; each module owns a disposable local database."""

import os
from contextlib import ExitStack
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from agno.db.postgres import PostgresDb
from agno.fs import FileSystem
from agno.knowledge.embedder.base import Embedder
from agno.knowledge.knowledge import Knowledge
from agno.knowledge.page import PageChanged, PageError
from agno.knowledge.page._source import PageSource
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


def warm_search_pool(knowledge, count):
    # Parallel optional work reuses pooled connections; cold work falls back to
    # the parent's snapshot instead of adding an unbounded transport handshake.
    with ExitStack() as stack:
        for _ in range(count):
            stack.enter_context(knowledge._page_engine.connect())


@pytest.mark.parametrize("tuned", [False, True])
@pytest.mark.parametrize("plan_mode", [None, "force_custom_plan"])
def test_search_tuning_honors_hnsw_and_operator_defaults_without_leaking(corpus, tuned, plan_mode):
    from sqlalchemy import event

    from agno.knowledge.page import PageSearchConfig
    from agno.vectordb.pgvector.index import HNSW

    knowledge, _, _ = corpus
    knowledge.sync_pages(url="https://docs.example.com/llms.txt")
    knowledge.vector_db.vector_index = HNSW(ef_search=73)
    knowledge.page_search = PageSearchConfig(plan_cache_mode=plan_mode)
    if tuned:
        knowledge.page_search = PageSearchConfig(
            plan_cache_mode=plan_mode,
            enable_seqscan=False,
            parallel_setup_cost=0,
            parallel_tuple_cost=0,
            max_parallel_workers_per_gather=4,
            min_parallel_table_scan_size=0,
        )
    operator = {
        "enable_seqscan": "on",
        "parallel_setup_cost": "123",
        "parallel_tuple_cost": "0.37",
        "max_parallel_workers_per_gather": "1",
        "min_parallel_table_scan_size": "64kB",
        "plan_cache_mode": "auto",
        "hnsw.ef_search": "41",
    }
    observed = []
    with ExitStack() as stack:
        for _ in range(knowledge._page_engine.pool.size()):
            conn = stack.enter_context(knowledge._page_engine.connect())
            for name, value in operator.items():
                conn.execute(text("SELECT set_config(:name, :value, false)"), {"name": name, "value": value})
            conn.commit()

    def capture(conn, cursor, statement, parameters, context, many):
        if "WITH by_vector AS" in statement:
            observed.append(
                {
                    name: conn.execute(text("SELECT current_setting(:name)"), {"name": name}).scalar_one()
                    for name in operator
                }
            )

    event.listen(knowledge._page_engine, "before_cursor_execute", capture)
    try:
        assert knowledge.search_pages("Agent").results
        expected = {**operator, "hnsw.ef_search": "73", "plan_cache_mode": plan_mode or operator["plan_cache_mode"]}
        if tuned:
            expected.update(
                enable_seqscan="off",
                parallel_setup_cost="0",
                parallel_tuple_cost="0",
                max_parallel_workers_per_gather="4",
                min_parallel_table_scan_size="0",
            )
        assert observed == [expected]
        with knowledge._page_engine.connect() as conn:
            assert {
                name: conn.execute(text("SELECT current_setting(:name)"), {"name": name}).scalar_one()
                for name in operator
            } == operator
    finally:
        event.remove(knowledge._page_engine, "before_cursor_execute", capture)
        knowledge._page_engine.dispose()


def test_custom_plan_can_use_the_namespace_partial_hnsw_index(corpus):
    import json

    knowledge, _, _ = corpus
    knowledge.sync_pages(url="https://docs.example.com/llms.txt")
    coordinator = knowledge._pages()
    index = list(coordinator._search_indexes())[1][1]
    name = "page_plan_" + uuid4().hex[:8]
    with knowledge._page_engine.begin() as conn:
        conn.execute(text("SET LOCAL enable_seqscan=off"))
        conn.execute(
            text(
                f"PREPARE {name}(text, vector) AS SELECT id FROM {coordinator._vector_name} "
                "WHERE meta_data->>'namespace'=$1 ORDER BY embedding <=> $2 LIMIT 200"
            )
        )
        try:
            # The namespace is generated by the test fixture, not external SQL input.
            explain = f"EXPLAIN (FORMAT JSON) EXECUTE {name}('{coordinator.namespace}', '[1,0.5,0.2]')"
            conn.execute(text("SET LOCAL plan_cache_mode=force_generic_plan"))
            generic = conn.execute(text(explain)).scalar_one()
            conn.execute(text("SET LOCAL plan_cache_mode=force_custom_plan"))
            custom = conn.execute(text(explain)).scalar_one()
            assert index not in json.dumps(generic) and index in json.dumps(custom)
            print("NAMESPACE_PLANS", json.dumps({"generic": generic, "custom": custom}), flush=True)
        finally:
            conn.execute(text(f"DEALLOCATE {name}"))


def test_cold_optional_search_uses_parent_snapshot_without_losing_queries(corpus, monkeypatch):
    from threading import BoundedSemaphore

    from sqlalchemy import event

    import agno.knowledge.page._coordinator as pages

    knowledge, _, _ = corpus
    knowledge.sync_pages(url="https://docs.example.com/llms.txt")
    knowledge._page_engine.dispose()
    connections = []

    def capture(conn, cursor, statement, parameters, context, many):
        if "WITH by_vector AS" in statement:
            connections.append(id(conn.connection.driver_connection))

    event.listen(knowledge._page_engine, "before_cursor_execute", capture)
    try:
        actual = knowledge.search_pages("Agent", alternatives=["tools", "configuration"])
    finally:
        event.remove(knowledge._page_engine, "before_cursor_execute", capture)
    assert actual.results and not actual.partial
    assert len(connections) == 3 and len(set(connections)) == 1
    monkeypatch.setattr(pages, "_PARALLEL_SEARCHES", BoundedSemaphore(0))
    assert actual == knowledge.search_pages("Agent", alternatives=["tools", "configuration"])


def test_first_setup_serializes_until_required_schema_is_committed(engine):
    import threading
    import time
    from concurrent.futures import ThreadPoolExecutor

    from sqlalchemy import event

    from agno.db.postgres._bounded import bounded_engine

    suffix = uuid4().hex[:8]
    db = PostgresDb(db_engine=engine, knowledge_table="init_catalog_" + suffix)
    vector = PgVector(db_engine=engine, table_name="init_vectors_" + suffix, embedder=RecordingEmbedder())
    first = Knowledge(content_db=db, vector_db=vector, page_store=FileSystem(db, namespace="init-" + suffix))
    second = Knowledge(content_db=db, vector_db=vector, page_store=FileSystem(db, namespace="init-" + suffix))
    first._page_engine = bounded_engine(engine, capacity=8)
    entered, release = threading.Event(), threading.Event()

    def hold(conn, cursor, statement, parameters, context, many):
        if "ADD COLUMN IF NOT EXISTS _agno_page_tsv" in statement:
            entered.set()
            assert release.wait(5)

    event.listen(first._page_engine, "before_cursor_execute", hold)
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            one = pool.submit(first.setup)
            assert entered.wait(3)
            two = pool.submit(second.setup)
            try:
                time.sleep(0.1)
                assert not two.done() and not getattr(second, "_page_ready", False)
            finally:
                release.set()
            one.result(timeout=5)
            two.result(timeout=5)
        assert first._page_ready and second._page_ready
        assert second.list_pages().pages == ()
    finally:
        release.set()
        event.remove(first._page_engine, "before_cursor_execute", hold)
        first._page_engine.dispose()
        if hasattr(second, "_page_engine"):
            second._page_engine.dispose()


def test_initialized_setup_repairs_missing_index_and_rejects_wrong_definition(corpus):
    knowledge, _, _ = corpus
    coordinator = knowledge._pages()
    schema, name, table, _ = next(coordinator._search_indexes())
    with knowledge._page_engine.begin() as conn:
        conn.execute(text(f'DROP INDEX "{schema}"."{name}"'))
    second = Knowledge(
        content_db=knowledge.content_db,
        vector_db=knowledge.vector_db,
        page_store=FileSystem(knowledge.content_db, namespace=knowledge.page_store.namespace),
    )
    try:
        second.setup()
        assert second._page_ready
        with second._page_engine.begin() as conn:
            conn.execute(text(f'DROP INDEX "{schema}"."{name}"'))
            conn.execute(text(f'CREATE INDEX "{name}" ON {table} (id)'))
        third = Knowledge(
            content_db=knowledge.content_db,
            vector_db=knowledge.vector_db,
            page_store=FileSystem(knowledge.content_db, namespace=knowledge.page_store.namespace),
        )
        try:
            with pytest.raises(ValueError, match="incompatible_page_search_index"):
                third.setup()
            assert not getattr(third, "_page_ready", False)
        finally:
            third._page_engine.dispose()
    finally:
        with second._page_engine.begin() as conn:
            conn.execute(text(f'DROP INDEX "{schema}"."{name}"'))
        knowledge.setup()
        second._page_engine.dispose()


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


@pytest.mark.parametrize("asynchronous", [False, True])
def test_public_discovery_validation_preserves_publication_and_releases_lock(corpus, engine, monkeypatch, asynchronous):
    import asyncio

    from sqlalchemy import func, select

    knowledge, embedder, site = corpus
    url = "https://docs.example.com/llms.txt"
    for index in range(3):
        site[url] += f"\n- [Extra](https://docs.example.com/extra-{index}.md)"
        site[f"https://docs.example.com/extra-{index}.md"] = f"# Extra {index}\n\nPublished evidence."
    assert knowledge.sync_pages(url=url).updated == 4
    coordinator = knowledge._pages()
    pages = knowledge.list_pages()
    bodies = [knowledge.read_page(page.path) for page in pages.pages]
    vector = knowledge.vector_db.table

    def stored_state():
        with engine.connect() as conn:
            return (
                conn.execute(select(coordinator.catalog).where(coordinator._predicate())).mappings().all(),
                conn.execute(
                    select(func.row_to_json(vector.table_valued()))
                    .where(vector.c.content_id.in_([page.content_id for page in pages.pages]))
                    .order_by(vector.c.id)
                )
                .scalars()
                .all(),
                conn.execute(
                    select(coordinator.binding).where(coordinator.binding.c.namespace == coordinator.namespace)
                )
                .mappings()
                .one(),
            )

    before = stored_state()
    # A neighboring namespace must not inflate the published count.
    other = Knowledge(
        contents_db=knowledge.contents_db,
        vector_db=knowledge.vector_db,
        page_store=FileSystem(knowledge.contents_db, namespace="neighbor-" + uuid4().hex[:8]),
    )
    other.setup()
    assert other.sync_pages(url=url).updated == 4
    other._page_engine.dispose()
    site[url] = "- [Agent](https://docs.example.com/agent.md)"
    site["https://docs.example.com/agent.md"] += "\nMust not publish on rejection."
    fetched = []

    def fetch(self, url, max_bytes):
        fetched.append(url)
        return site[url]

    monkeypatch.setattr(PageSource, "fetch", fetch)
    calls = len(embedder.calls)

    def reject(discovered, published):
        assert (discovered, published) == (1, 4)
        with engine.connect() as conn:
            acquired = conn.execute(
                text("SELECT pg_try_advisory_lock(:key)"), {"key": coordinator.lock_key}
            ).scalar_one()
            if acquired:
                conn.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": coordinator.lock_key})
            assert not acquired, "validation must hold the namespace writer lock"
        raise ValueError("index rejected by product policy")

    def run(callback):
        if asynchronous:
            return asyncio.run(knowledge.async_sync_pages(url=url, validate_discovery=callback))
        return knowledge.sync_pages(url=url, validate_discovery=callback)

    with pytest.raises(ValueError, match="index rejected by product policy"):
        run(reject)
    assert fetched == [url] and len(embedder.calls) == calls
    assert stored_state() == before
    assert knowledge.list_pages() == pages
    assert [knowledge.read_page(page.path) for page in pages.pages] == bodies
    with engine.connect() as conn:
        assert (
            conn.execute(
                select(coordinator.catalog.c.status).where(
                    coordinator.catalog.c.type == "source",
                    coordinator.catalog.c.metadata["_agno"]["namespace"].astext == coordinator.namespace,
                )
            ).scalar_one()
            == "failed"
        )
        assert conn.execute(text("SELECT pg_try_advisory_lock(:key)"), {"key": coordinator.lock_key}).scalar_one()
        conn.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": coordinator.lock_key})
    report = run(lambda discovered, published: None)
    assert (report.updated, report.deleted, report.status) == (1, 3, "completed")
    assert knowledge.read_page("/agent").text == site["https://docs.example.com/agent.md"]


@pytest.mark.parametrize("invalid", ["boolean", "coroutine", "noncallable"])
def test_discovery_validation_rejects_invalid_callbacks_before_page_work(corpus, invalid):
    import inspect

    knowledge, embedder, _ = corpus
    coroutine = None

    async def asynchronous_check():
        return None

    if invalid == "coroutine":
        coroutine = asynchronous_check()

        def callback(discovered, published):
            return coroutine

    elif invalid == "boolean":

        def callback(discovered, published):
            return False

    else:
        callback = False
    with pytest.raises(ValueError, match="validate_discovery must"):
        knowledge.sync_pages(url="https://docs.example.com/llms.txt", validate_discovery=callback)
    assert not embedder.calls and not knowledge.list_pages().pages
    if coroutine is not None:
        assert inspect.getcoroutinestate(coroutine) == inspect.CORO_CLOSED


@pytest.mark.parametrize("failure", ["empty", "incomplete", "page"])
def test_accepting_discovery_validation_does_not_bypass_other_pruning_guards(corpus, failure):
    from agno.knowledge.page import SyncFailed

    knowledge, _, site = corpus
    url = "https://docs.example.com/llms.txt"
    original_index = site[url]
    site[url] += "\n- [Keep](https://docs.example.com/keep.md)"
    site["https://docs.example.com/keep.md"] = "# Keep\n\nPublished evidence."
    assert knowledge.sync_pages(url=url).updated == 2
    before = knowledge.list_pages()
    site[url] = original_index
    if failure == "empty":
        site[url] = ""
    elif failure == "incomplete":
        site[url] += "\n- [Missing](https://docs.example.com/_llms/missing.md)"
    else:
        del site["https://docs.example.com/agent.md"]
    if failure == "empty":
        with pytest.raises(SyncFailed):
            knowledge.sync_pages(url=url, validate_discovery=lambda discovered, published: None)
    else:
        report = knowledge.sync_pages(url=url, validate_discovery=lambda discovered, published: None)
        assert report.status == "partial" and report.deleted == 0
    assert knowledge.list_pages() == before


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
    validation_counts = []

    def validate(discovered, published):
        validation_counts.append((discovered, published))

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
            futures = [
                pool.submit(knowledge.sync_pages, url=base + "/llms.txt", validate_discovery=validate) for _ in range(2)
            ]
            reports = [future.result(timeout=10) for future in futures]
        assert sorted(report.updated for report in reports) == [0, 2]
        assert len(embedding_threads) == 2
        assert not embedding_threads & database_threads
        assert len(knowledge.list_pages().pages) == 2
        assert validation_counts == [(2, 0), (2, 2)]
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
    assert settings == [("on", "repeatable read", str(knowledge.vector_db.vector_index.ef_search))]
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
    warm_search_pool(knowledge, 3)
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

    import agno.knowledge.page._coordinator as pages

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

    import agno.knowledge.page._coordinator as pages

    knowledge, _, _ = corpus
    await knowledge.async_sync_pages(url="https://docs.example.com/llms.txt")
    warm_search_pool(knowledge, 2)
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
    from agno.knowledge.page._coordinator import PageCoordinator

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
    from agno.knowledge.page import SearchHit, SearchResult, encoded_size
    from agno.knowledge.page._coordinator import PageCoordinator

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


@pytest.mark.asyncio
@pytest.mark.parametrize("async_search", [False, True])
@pytest.mark.parametrize("partial", [False, True])
async def test_public_search_output_allowance_preserves_ranked_prefix_and_exact_bytes(
    corpus, monkeypatch, async_search, partial
):
    from agno.knowledge.page import SearchHit, SearchResult, encoded_size
    from agno.knowledge.page._coordinator import PageCoordinator

    knowledge, _, _ = corpus
    hits = tuple(
        SearchHit(
            path=f"/page-{index}.md",
            url=f"https://docs.example.com/page-{index}",
            title=f"Page {index}",
            revision="r",
            chunk_id=str(index),
            content='é😀\\"\n' * 200,
            score=0.8,
            rank=index + 1,
        )
        for index in range(10)
    )
    rows = [
        {
            "id": hit.chunk_id,
            "file_version": 1,
            "score": hit.score,
            "breadcrumb": hit.title,
            "content": hit.content,
            "page": {
                "filesystem_version": 1,
                "path": hit.path,
                "url": hit.url,
                "title": hit.title,
                "revision": hit.revision,
            },
        }
        for hit in hits
    ]
    outcomes = [rows, RuntimeError("alternative failed")] if partial else [rows]
    monkeypatch.setattr(PageCoordinator, "_search_queries", lambda *args, **kwargs: outcomes)
    warnings = ("alternative_unavailable",) if partial else ()
    complete = SearchResult(results=hits, partial=partial, warnings=warnings)
    full_size = encoded_size(complete)
    assert 24_000 < full_size < 32_000

    async def search(**kwargs):
        alternatives = ["optional"] if partial else None
        if async_search:
            return await knowledge.asearch_pages("primary", alternatives=alternatives, **kwargs)
        return knowledge.search_pages("primary", alternatives=alternatives, **kwargs)

    default = await search()
    assert default.truncated and encoded_size(default) <= 24_000
    for allowance in (24_000, 26_000, full_size - 1, full_size, 32_000):
        result = await search(max_output_bytes=allowance)
        assert encoded_size(result) <= allowance
        assert result.results == hits[: len(result.results)]
        assert result.omitted_count == len(hits) - len(result.results)
        assert result.partial == partial and result.warnings == warnings
        assert result.truncated == (allowance < full_size)
        if allowance >= full_size:
            assert result == complete
        elif allowance == full_size - 1:
            assert result.omitted_count == 1
        if allowance == 24_000:
            assert result == default
    # An opt-in on one search must not change subsequent callers' default budget.
    assert await search() == default


@pytest.mark.asyncio
@pytest.mark.parametrize("allowance", [23_999, 32_001, True, False, 32_000.0, "32000", None])
async def test_public_search_rejects_invalid_output_allowance_before_embedding(corpus, allowance):
    knowledge, embedder, _ = corpus
    with pytest.raises(ValueError, match="invalid_search_output_budget"):
        knowledge.search_pages("primary", max_output_bytes=allowance)
    with pytest.raises(ValueError, match="invalid_search_output_budget"):
        await knowledge.asearch_pages("primary", max_output_bytes=allowance)
    assert embedder.calls == []


def test_alternative_wait_deadline_preserves_primary_results(corpus):
    import threading
    import time

    from sqlalchemy import event

    from agno.utils.bounded import WorkBudget

    knowledge, _, _ = corpus
    knowledge.sync_pages(url="https://docs.example.com/llms.txt")

    def delay(conn, cursor, statement, parameters, context, executemany):
        if "embedding <=>" in statement and threading.current_thread().name.startswith("knowledge-query"):
            # Simulate a response arriving after the caller's remaining deadline.
            time.sleep(0.15)

    event.listen(knowledge._page_engine, "after_cursor_execute", delay)
    try:
        result = knowledge._pages().search("Agent", alternatives=["tools"], budget=WorkBudget(0.1))
    finally:
        event.remove(knowledge._page_engine, "after_cursor_execute", delay)
    assert result.results and result.partial
    assert result.warnings == ("alternative_unavailable",)
    assert knowledge._page_engine.pool.checkedout() == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("parallel", [True, False])
@pytest.mark.parametrize("alternative_count", [1, 3])
@pytest.mark.parametrize("embedding_delay", [0, 1.2])
async def test_public_async_search_returns_primary_before_optional_deadline(
    corpus, monkeypatch, parallel, alternative_count, embedding_delay
):
    import asyncio
    import time
    from threading import BoundedSemaphore

    from sqlalchemy import event

    import agno.knowledge.page._coordinator as pages

    knowledge, embedder, _ = corpus
    await knowledge.async_sync_pages(url="https://docs.example.com/llms.txt")
    primary = await knowledge.asearch_pages("Agent")
    assert primary.results and not primary.partial
    if parallel:
        warm_search_pool(knowledge, alternative_count + 1)

    embed = embedder.get_embedding

    def delayed_embedding(content, *, timeout):
        if content == "Agent":
            time.sleep(embedding_delay)
        return embed(content, timeout=timeout)

    monkeypatch.setattr(embedder, "get_embedding", delayed_embedding)
    admission = BoundedSemaphore(2 if parallel else 0)
    monkeypatch.setattr(pages, "_PARALLEL_SEARCHES", admission)
    coordinator = knowledge._pages()
    hybrid = coordinator._hybrid_sql
    calls, cancelled = [], []

    def sql():
        calls.append(None)
        return hybrid() if len(calls) == 1 else "SELECT pg_sleep(3)"

    def cleanup_delay(context):
        if getattr(context.original_exception, "sqlstate", None) == "57014":
            cancelled.append(context.statement)
            # Leave real time for an ordinary rollback/connection cleanup after
            # PostgreSQL cancels optional SQL, not just for catching its exception.
            time.sleep(0.075)

    monkeypatch.setattr(coordinator, "_hybrid_sql", sql)
    monkeypatch.setattr(knowledge, "_pages", lambda: coordinator)
    event.listen(knowledge._page_engine, "handle_error", cleanup_delay)
    started = time.monotonic()
    try:
        result = await knowledge.asearch_pages(
            "Agent", alternatives=[f"optional {i}" for i in range(alternative_count)]
        )
        elapsed = time.monotonic() - started
        print(
            f"PUBLIC_ASYNC_DEADLINE parallel={parallel} alternatives={alternative_count} "
            f"embedding_delay={embedding_delay} seconds={elapsed:.6f}"
        )
        assert elapsed < 2
        assert result.results == primary.results
        assert result.partial and result.warnings == ("alternative_unavailable",)
        assert cancelled and set(cancelled) == {"SELECT pg_sleep(3)"}
        assert knowledge._page_engine.pool.checkedout() == 0
        assert len(calls) == alternative_count + 1
        if parallel:
            assert admission.acquire(blocking=False)
            assert admission.acquire(blocking=False)
            admission.release()
            admission.release()
        # Capacity is returned only after the parent and children have finished.
        acquired = 0
        try:
            while pages.READ_WORKERS._capacity.acquire(blocking=False):
                acquired += 1
            assert acquired == 8
        finally:
            for _ in range(acquired):
                pages.READ_WORKERS._capacity.release()
    finally:
        # Also drain the failed pre-fix worker before removing its listener.
        for _ in range(100):
            if knowledge._page_engine.pool.checkedout() == 0:
                break
            await asyncio.sleep(0.01)
        event.remove(knowledge._page_engine, "handle_error", cleanup_delay)


def test_public_contention_preserves_completed_primary_and_cleans_up(corpus, monkeypatch):
    import asyncio
    import threading
    import time
    from concurrent.futures import ThreadPoolExecutor

    from sqlalchemy import event

    import agno.knowledge.page._coordinator as module

    knowledge, embedder, site = corpus
    url = "https://docs.example.com/llms.txt"
    knowledge.sync_pages(url=url)
    published = knowledge.read_page("/agent")
    sync_started, sync_release = threading.Event(), threading.Event()
    site["https://docs.example.com/agent.md"] += "\nNew publication after the search.\n"

    def fetch(self, address, max_bytes):
        if address.endswith("/agent.md"):
            sync_started.set()
            assert sync_release.wait(10)
        return site[address]

    monkeypatch.setattr(PageSource, "fetch", fetch)
    sync_results = []
    sync_thread = threading.Thread(target=lambda: sync_results.append(knowledge.sync_pages(url=url)))
    sync_thread.start()
    assert sync_started.wait(5)
    embedding_started, embedding_release, readers_ready = threading.Event(), threading.Event(), threading.Event()
    original = embedder.get_embedding

    def embed(content, *, timeout=30):
        if content == "question":
            embedding_started.set()
            assert embedding_release.wait(timeout)
        return original(content, timeout=timeout)

    monkeypatch.setattr(embedder, "get_embedding", embed)
    count = [0]
    lock = threading.Lock()
    read_times = []
    primary_times = []

    def before(conn, cursor, statement, params, context, many):
        if " AS total_chars" in statement:
            with lock:
                count[0] += 1
                if count[0] == 6:
                    readers_ready.set()
            # Simulate a 1.4-second database read on each real public aread_page
            # connection, after its existing transaction deadline is installed.
            cursor.execute("SELECT pg_sleep(1.4)")

    def after(conn, cursor, statement, params, context, many):
        if "WITH by_vector AS" in statement:
            primary_times.append(time.monotonic())

    event.listen(knowledge._page_engine, "before_cursor_execute", before)
    event.listen(knowledge._page_engine, "after_cursor_execute", after)

    def search():
        start = time.monotonic()
        try:
            result = asyncio.run(knowledge.asearch_pages("question", alternatives=["tools"]))
            return start, time.monotonic() - start, result
        except Exception:
            raise

    def read():
        start = time.monotonic()
        result = asyncio.run(knowledge.aread_page("/agent"))
        read_times.append(time.monotonic() - start)
        return result

    try:
        with ThreadPoolExecutor(max_workers=7) as pool:
            searched = pool.submit(search)
            assert embedding_started.wait(5)
            time.sleep(0.9)
            reads = [pool.submit(read) for _ in range(6)]
            assert readers_ready.wait(5)
            embedding_release.set()
            start, elapsed, outcome = searched.result(timeout=5)
            held = module.READ_WORKERS._capacity._value
            for r in reads:
                assert r.result(timeout=5).text
        time.sleep(0.1)
        print(
            "PUBLIC_CONTENTION",
            {
                "search_seconds": elapsed,
                "outcome": type(outcome).__name__,
                "primary_seconds": [t - start for t in primary_times],
                "read_seconds": read_times,
                "free_slots_at_timeout": held,
                "free_slots_after_cleanup": module.READ_WORKERS._capacity._value,
            },
            flush=True,
        )
        assert elapsed < 2 and primary_times and primary_times[0] - start < 1.5
        assert outcome.results and all(hit.revision == published.revision for hit in outcome.results)
        assert outcome.partial and outcome.warnings == ("alternative_unavailable",)
        assert module.READ_WORKERS._capacity._value == 8
        assert knowledge._page_engine.pool.checkedout() == 1
        assert all(t < 2 for t in read_times)
    finally:
        embedding_release.set()
        sync_release.set()
        sync_thread.join(10)
        event.remove(knowledge._page_engine, "before_cursor_execute", before)
        event.remove(knowledge._page_engine, "after_cursor_execute", after)
    assert sync_results[0].updated == 1
    assert knowledge.read_page("/agent").revision != published.revision


def test_initialized_setup_during_sync_uses_validated_read_only_path(corpus, monkeypatch):
    import threading
    import time

    from sqlalchemy import event

    first, _, site = corpus
    url = "https://docs.example.com/llms.txt"
    first.sync_pages(url=url)
    entered, release = threading.Event(), threading.Event()

    def fetch(self, address, max_bytes):
        if address.endswith("/agent.md"):
            entered.set()
            assert release.wait(45)
        return site[address]

    monkeypatch.setattr(PageSource, "fetch", fetch)
    outcome = []

    def synchronize():
        try:
            outcome.append(first.sync_pages(url=url))
        except BaseException as e:
            outcome.append(e)

    worker = threading.Thread(target=synchronize)
    worker.start()
    assert entered.wait(5)
    second = Knowledge(
        contents_db=first.contents_db,
        vector_db=first.vector_db,
        page_store=FileSystem(first.contents_db, namespace=first.page_store.namespace),
    )
    statements = []
    from agno.db.postgres._bounded import bounded_engine

    second._page_engine = bounded_engine(second.contents_db.db_engine, capacity=8)

    def capture(conn, cursor, statement, parameters, context, many):
        statements.append(statement)

    event.listen(second._page_engine, "before_cursor_execute", capture)
    started = time.monotonic()
    try:
        second.setup()
        elapsed = time.monotonic() - started
        print("INITIALIZED_SETUP_DURING_SYNC", elapsed, flush=True)
        assert elapsed < 2 and second._page_ready
        assert not any("pg_advisory" in sql or sql.startswith(("ALTER", "CREATE", "INSERT")) for sql in statements)
        assert second.read_page("/agent").text == first.read_page("/agent").text
    finally:
        release.set()
        worker.join(10)
        if hasattr(second, "_page_engine"):
            second._page_engine.dispose()
    assert len(outcome) == 1 and not isinstance(outcome[0], BaseException)
