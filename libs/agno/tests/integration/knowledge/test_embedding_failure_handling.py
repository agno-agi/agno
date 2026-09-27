"""End-to-end ingestion behaviour when embedding fails.

These exercise a real vector store and a real embedder rather than mocks, because
the unit tests for this behaviour passed while the live path still misreported
status. Failures are injected at the embedder boundary so the rest of the
ingestion path - chunking, the vector store write, the status round-trip through
the contents database - runs exactly as it does in production.
"""

import os

import pytest

from agno.db.sqlite import SqliteDb
from agno.exceptions import EmbeddingError
from agno.knowledge.content import ContentStatus
from agno.knowledge.embedder.openai import OpenAIEmbedder
from agno.knowledge.knowledge import Knowledge
from agno.vectordb.lancedb import LanceDb

SAMPLE_TEXT = (
    "Quarterly revenue grew twelve percent, driven by enterprise renewals. "
    "Churn fell to three percent after the onboarding revamp. "
    "Headcount rose by fourteen people, mostly in support."
)


@pytest.fixture
def vector_db():
    table_name = f"embed_fail_{os.urandom(4).hex()}"
    db = LanceDb(table_name=table_name, uri="tmp/lancedb", embedder=OpenAIEmbedder(id="text-embedding-3-small"))
    yield db
    db.drop()


@pytest.fixture
def contents_db(tmp_path):
    return SqliteDb(id=f"embed_fail_{os.urandom(4).hex()}", db_file=str(tmp_path / "contents.db"))


def make_knowledge(vector_db, contents_db, **kwargs) -> Knowledge:
    return Knowledge(name="embedding failure probe", vector_db=vector_db, contents_db=contents_db, **kwargs)


def fail_embeddings(embedder, error: EmbeddingError, succeed_after: int = 0):
    """Make ``embedder`` raise ``error`` on its first ``succeed_after`` calls.

    ``succeed_after=0`` fails every call. Returns a dict whose ``count`` key
    records how many embedding calls were made.
    """
    real = embedder.get_embedding_and_usage
    calls = {"count": 0}

    def flaky(text):
        calls["count"] += 1
        if succeed_after == 0 or calls["count"] <= succeed_after:
            raise error
        return real(text)

    embedder.get_embedding_and_usage = flaky
    return calls


def fail_async_embeddings(embedder, error: EmbeddingError, succeed_after: int = 0):
    """Async twin of ``fail_embeddings``."""
    real = embedder.async_get_embedding_and_usage
    calls = {"count": 0}

    async def flaky(text):
        calls["count"] += 1
        if succeed_after == 0 or calls["count"] <= succeed_after:
            raise error
        return await real(text)

    embedder.async_get_embedding_and_usage = flaky
    return calls


def stored_status(knowledge: Knowledge, content_id: str):
    """Read the status back through the contents database, as a caller would."""
    return knowledge.get_content_status(content_id)


def only_content(knowledge: Knowledge):
    contents, _ = knowledge.get_content()
    assert len(contents) == 1, f"expected exactly one content row, got {len(contents)}"
    return contents[0]


class TestIngestionReportsEmbeddingFailure:
    """A file whose chunks never embed must not be reported as complete."""

    def test_total_embedding_failure_is_reported_as_failed(self, vector_db, contents_db):
        knowledge = make_knowledge(vector_db, contents_db, max_embedding_retries=0)
        error = EmbeddingError(
            "Incorrect API key provided: sk-live-abcdef0123456789",
            status_code=401,
            model_id="text-embedding-3-small",
            provider="OpenAI",
        )
        fail_embeddings(vector_db.embedder, error)

        knowledge.insert(name="q3-report", description="quarterly numbers", text_content=SAMPLE_TEXT)

        content = only_content(knowledge)
        assert content.status == ContentStatus.FAILED, "unembedded content must never report completed"

        status, message = stored_status(knowledge, content.id)
        assert status == ContentStatus.FAILED
        assert "0 of" in message
        assert "authentication" in message
        # The message is persisted and served over the API
        assert "sk-live-abcdef0123456789" not in message
        assert "[redacted]" in message

    def test_failed_content_is_not_retrievable(self, vector_db, contents_db):
        """The bug being fixed: status said complete while search returned nothing."""
        knowledge = make_knowledge(vector_db, contents_db, max_embedding_retries=0)
        fail_embeddings(vector_db.embedder, EmbeddingError("Service unavailable", status_code=503))

        knowledge.insert(name="q3-report", description="quarterly numbers", text_content=SAMPLE_TEXT)

        content = only_content(knowledge)
        assert content.status != ContentStatus.COMPLETED
        assert knowledge.search("revenue") == [], "nothing embedded, so nothing should be retrievable"

    def test_successful_ingestion_still_completes_and_is_searchable(self, vector_db, contents_db):
        """The healthy path must be unaffected by the failure handling."""
        knowledge = make_knowledge(vector_db, contents_db)

        knowledge.insert(name="q3-report", description="quarterly numbers", text_content=SAMPLE_TEXT)

        content = only_content(knowledge)
        assert content.status == ContentStatus.COMPLETED
        assert len(knowledge.search("revenue")) >= 1

    @pytest.mark.asyncio
    async def test_async_total_failure_is_reported_as_failed(self, vector_db, contents_db):
        knowledge = make_knowledge(vector_db, contents_db, max_embedding_retries=0)
        error = EmbeddingError("Service unavailable", status_code=503, provider="OpenAI")
        # Some stores fall back to sync embedding when the async batch fails, so a
        # genuinely unembeddable document has to fail on both routes.
        fail_embeddings(vector_db.embedder, error)
        fail_async_embeddings(vector_db.embedder, error)

        await knowledge.ainsert(name="q3-report", description="quarterly numbers", text_content=SAMPLE_TEXT)

        content = only_content(knowledge)
        assert content.status == ContentStatus.FAILED


class TestRealProviderFailure:
    """Drives a genuine provider rejection instead of an injected EmbeddingError."""

    def test_invalid_credentials_do_not_report_completed(self, contents_db):
        table_name = f"embed_fail_{os.urandom(4).hex()}"
        vector_db = LanceDb(
            table_name=table_name,
            uri="tmp/lancedb",
            embedder=OpenAIEmbedder(id="text-embedding-3-small", api_key="sk-proj-INVALIDKEYFORTESTING123456"),
        )
        knowledge = make_knowledge(vector_db, contents_db, max_embedding_retries=0)
        try:
            knowledge.insert(name="q3-report", description="quarterly numbers", text_content=SAMPLE_TEXT)

            content = only_content(knowledge)
            assert content.status != ContentStatus.COMPLETED, (
                "a real credential rejection must never be reported as complete"
            )
            assert knowledge.search("revenue") == []

            _, message = stored_status(knowledge, content.id)
            assert "authentication" in message
            assert "sk-proj-INVALIDKEYFORTESTING123456" not in message
        finally:
            vector_db.drop()


class TestStatusIsVisibleToCallers:
    """Whatever ingestion decided must survive the round-trip to the caller."""

    def test_failed_status_round_trips_through_the_contents_db(self, vector_db, contents_db):
        knowledge = make_knowledge(vector_db, contents_db, max_embedding_retries=0)
        fail_embeddings(vector_db.embedder, EmbeddingError("Service unavailable", status_code=503))

        knowledge.insert(name="q3-report", description="quarterly numbers", text_content=SAMPLE_TEXT)
        content_id = only_content(knowledge).id

        # A fresh Knowledge over the same contents db, as a separate process would see it
        reopened = make_knowledge(vector_db, contents_db)
        status, message = reopened.get_content_status(content_id)

        assert status == ContentStatus.FAILED
        assert message

    def test_message_names_the_embedder_and_the_fix(self, vector_db, contents_db):
        knowledge = make_knowledge(vector_db, contents_db, max_embedding_retries=0)
        error = EmbeddingError(
            "Incorrect API key provided",
            status_code=401,
            model_id="text-embedding-3-small",
            provider="OpenAI",
        )
        fail_embeddings(vector_db.embedder, error)

        knowledge.insert(name="q3-report", description="quarterly numbers", text_content=SAMPLE_TEXT)

        _, message = stored_status(knowledge, only_content(knowledge).id)
        assert "OpenAI text-embedding-3-small" in message
        assert "Retrying will not help" in message
        assert "API key" in message


class TestRetryRecoversTransientFailures:
    """A chunk lost to a passing rate limit is unretrievable forever, so it is retried."""

    def test_transient_failure_recovers_and_content_is_searchable(self, vector_db, contents_db):
        knowledge = make_knowledge(vector_db, contents_db, max_embedding_retries=3, embedding_retry_backoff=0.05)
        error = EmbeddingError("Rate limit reached", status_code=429, provider="OpenAI")
        calls = fail_embeddings(vector_db.embedder, error, succeed_after=2)

        knowledge.insert(name="q3-report", description="quarterly numbers", text_content=SAMPLE_TEXT)

        content = only_content(knowledge)
        assert calls["count"] > 2, "the first attempts should have failed"
        assert content.status == ContentStatus.COMPLETED
        assert len(knowledge.search("revenue")) >= 1, "recovered content must be retrievable"

    def test_authentication_failure_is_not_retried(self, vector_db, contents_db):
        """A rejected credential fails identically on every attempt."""
        knowledge = make_knowledge(vector_db, contents_db, max_embedding_retries=3, embedding_retry_backoff=0.05)
        error = EmbeddingError("Incorrect API key provided", status_code=401, provider="OpenAI")
        calls = fail_embeddings(vector_db.embedder, error)

        knowledge.insert(name="q3-report", description="quarterly numbers", text_content=SAMPLE_TEXT)

        assert calls["count"] == 1, "an authentication failure must not be retried"
        assert only_content(knowledge).status == ContentStatus.FAILED

    def test_exhausted_retries_report_the_attempt_count(self, vector_db, contents_db):
        knowledge = make_knowledge(vector_db, contents_db, max_embedding_retries=2, embedding_retry_backoff=0.05)
        error = EmbeddingError("Rate limit reached", status_code=429, provider="OpenAI")
        calls = fail_embeddings(vector_db.embedder, error)

        knowledge.insert(name="q3-report", description="quarterly numbers", text_content=SAMPLE_TEXT)

        assert calls["count"] == 3, "one initial attempt plus two retries"
        _, message = stored_status(knowledge, only_content(knowledge).id)
        assert "3 attempts" in message

    @pytest.mark.asyncio
    async def test_async_transient_failure_recovers(self, vector_db, contents_db):
        knowledge = make_knowledge(vector_db, contents_db, max_embedding_retries=3, embedding_retry_backoff=0.05)
        error = EmbeddingError("Rate limit reached", status_code=429, provider="OpenAI")
        sync_calls = fail_embeddings(vector_db.embedder, error, succeed_after=2)
        async_calls = fail_async_embeddings(vector_db.embedder, error, succeed_after=2)

        await knowledge.ainsert(name="q3-report", description="quarterly numbers", text_content=SAMPLE_TEXT)

        assert sync_calls["count"] + async_calls["count"] > 2, "the first attempts should have failed"
        assert only_content(knowledge).status == ContentStatus.COMPLETED
        assert len(knowledge.search("revenue")) >= 1, "recovered content must be retrievable"


class TestReingestGuidance:
    """After a failed ingest the caller must be told how to recover this content."""

    def test_uploaded_text_is_told_to_supply_the_source_again(self, vector_db, contents_db):
        knowledge = make_knowledge(vector_db, contents_db, max_embedding_retries=0)
        fail_embeddings(vector_db.embedder, EmbeddingError("Service unavailable", status_code=503))

        knowledge.insert(name="q3-report", description="quarterly numbers", text_content=SAMPLE_TEXT)

        _, message = stored_status(knowledge, only_content(knowledge).id)
        assert "not retained" in message, "uploaded bytes are never persisted, so say so"
        assert "upload it again" in message

    def test_url_source_is_told_which_url_to_re_ingest(self, vector_db, contents_db, monkeypatch):
        """URL content records its origin, so recovery names the URL instead."""
        knowledge = make_knowledge(vector_db, contents_db, max_embedding_retries=0)
        url = "https://example.com/report.txt"

        class FakeResponse:
            content = SAMPLE_TEXT.encode()
            text = SAMPLE_TEXT
            status_code = 200

            def raise_for_status(self):
                return None

        monkeypatch.setattr("agno.utils.http.fetch_with_retry", lambda *a, **k: FakeResponse())
        fail_embeddings(vector_db.embedder, EmbeddingError("Service unavailable", status_code=503))

        knowledge.insert(name="report", description="remote report", url=url)

        _, message = stored_status(knowledge, only_content(knowledge).id)
        assert url in message
        assert "not retained" not in message

    def test_partial_ingest_also_explains_recovery(self, vector_db, contents_db):
        knowledge = make_knowledge(vector_db, contents_db, max_embedding_retries=1, embedding_retry_backoff=0.05)
        fail_embeddings(vector_db.embedder, EmbeddingError("Rate limit reached", status_code=429))

        knowledge.insert(name="q3-report", description="quarterly numbers", text_content=SAMPLE_TEXT)

        _, message = stored_status(knowledge, only_content(knowledge).id)
        assert "upload it again" in message
        assert "attempts" in message
