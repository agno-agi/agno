"""Ingestion must never report success for content that failed to embed."""

import inspect
from unittest.mock import AsyncMock, MagicMock

import pytest

from agno.exceptions import EmbeddingError
from agno.knowledge.content import Content, ContentStatus
from agno.knowledge.knowledge import Knowledge


def make_documents(embedded: int, total: int):
    """Build ``total`` documents of which the first ``embedded`` carry a vector."""
    documents = []
    for index in range(total):
        document = MagicMock()
        document.embedding = [0.1, 0.2, 0.3] if index < embedded else None
        documents.append(document)
    return documents


def make_knowledge(embeds_locally: bool = True) -> Knowledge:
    knowledge = Knowledge.__new__(Knowledge)
    if embeds_locally:
        vector_db = MagicMock()
        vector_db.embedder = MagicMock()
    else:
        # A store that embeds server-side exposes no embedder
        vector_db = MagicMock(spec=[])
    knowledge.vector_db = vector_db
    return knowledge


class TestEmbeddingErrorClassification:
    @pytest.mark.parametrize(
        "message,status_code,expected",
        [
            ("Rate limit reached for requests", 429, "rate_limit"),
            ("You exceeded your current quota", 200, "rate_limit"),
            ("Incorrect API key provided", 401, "authentication"),
            ("Permission denied for this resource", 403, "authentication"),
            ("maximum context length is 8192 tokens", 400, "content_too_large"),
            ("connection reset by peer", 502, "unknown"),
        ],
    )
    def test_reason_is_derived_from_message_and_status(self, message, status_code, expected):
        error = EmbeddingError(message, status_code=status_code, model_id="text-embedding-3-small")
        assert error.reason == expected

    def test_every_reason_has_an_actionable_hint(self):
        for message, code in [("rate limit", 429), ("api key", 401), ("too long", 400), ("boom", 502)]:
            error = EmbeddingError(message, status_code=code)
            assert error.recovery_hint
            assert error.recovery_hint.endswith(".")


class TestSuccessPathStatus:
    def test_all_chunks_embedded_is_completed(self):
        knowledge = make_knowledge()
        content = Content()

        knowledge._set_embedding_success_status(content, make_documents(10, 10))

        assert content.status == ContentStatus.COMPLETED
        assert content.status_message is None

    def test_some_chunks_embedded_is_partial(self):
        knowledge = make_knowledge()
        content = Content()

        knowledge._set_embedding_success_status(content, make_documents(7, 10))

        assert content.status == ContentStatus.PARTIAL
        assert "7 of 10" in content.status_message
        assert "3 failed" in content.status_message

    def test_no_chunks_embedded_is_failed_not_completed(self):
        """The reported bug: the write raised nothing, but nothing is retrievable."""
        knowledge = make_knowledge()
        content = Content()

        knowledge._set_embedding_success_status(content, make_documents(0, 10))

        assert content.status == ContentStatus.FAILED
        assert "10 attempted" in content.status_message

    def test_empty_document_list_is_completed(self):
        knowledge = make_knowledge()
        content = Content()

        knowledge._set_embedding_success_status(content, [])

        assert content.status == ContentStatus.COMPLETED

    def test_server_side_embedding_store_is_not_judged_by_chunk_counts(self):
        """Stores that embed server-side never populate Document.embedding."""
        knowledge = make_knowledge(embeds_locally=False)
        content = Content()

        knowledge._set_embedding_success_status(content, make_documents(0, 10))

        assert content.status == ContentStatus.COMPLETED
        assert content.status_message is None


class TestFailurePathStatus:
    def test_total_failure_is_failed_with_recovery_hint(self):
        knowledge = make_knowledge()
        content = Content()
        error = EmbeddingError("Incorrect API key provided", status_code=401)

        knowledge._set_embedding_failure_status(content, error, make_documents(0, 10), "insert")

        assert content.status == ContentStatus.FAILED
        assert "0 of 10 chunks embedded" in content.status_message
        assert "authentication (HTTP 401)" in content.status_message
        assert "API key" in content.status_message
        assert "Retrying will not help" in content.status_message

    def test_raised_write_is_failed_not_partial(self):
        """A write that raised committed nothing, whatever the in-memory documents say.

        Stores that write only after embedding the whole batch discard everything on an
        exception, so counting ``Document.embedding`` here would report chunks that are
        not retrievable and mark the row repairable-in-place.
        """
        knowledge = make_knowledge()
        content = Content()
        error = EmbeddingError("Rate limit reached", status_code=429)

        knowledge._set_embedding_failure_status(content, error, make_documents(4, 10), "insert")

        assert content.status == ContentStatus.FAILED
        assert "0 of 10" in content.status_message
        assert "4 of 10" not in content.status_message
        assert "rate-limited" in content.status_message

    def test_message_names_the_embedder_that_failed(self):
        """A multi-provider setup must not leave the user guessing which one broke."""
        knowledge = make_knowledge()
        content = Content(name="q3-report.pdf")
        error = EmbeddingError("boom", status_code=502, provider="OpenAI", model_id="text-embedding-3-small")

        knowledge._set_embedding_failure_status(content, error, make_documents(0, 3), "upsert")

        assert "q3-report.pdf" in content.status_message
        assert "OpenAI text-embedding-3-small" in content.status_message

    def test_credentials_are_not_persisted_in_the_message(self):
        """status_message is stored in the contents DB and served over the API."""
        knowledge = make_knowledge()
        content = Content()
        error = EmbeddingError("Incorrect API key provided: sk-abc123XYZdef456", status_code=401)

        knowledge._set_embedding_failure_status(content, error, make_documents(0, 3), "insert")

        assert "sk-abc123XYZdef456" not in content.status_message
        assert "[redacted]" in content.status_message

    def test_exhausted_retries_are_reported(self):
        knowledge = make_knowledge()
        content = Content()
        error = EmbeddingError("Rate limit reached", status_code=429)

        knowledge._set_embedding_failure_status(content, error, make_documents(0, 3), "insert", attempts=4)

        assert "after 4 attempts" in content.status_message


class TestVectorDbInsertMarksStatus:
    """The status written to the contents DB must reflect the embedding outcome."""

    def _knowledge_with_db(self, insert_side_effect=None, documents=None):
        knowledge = Knowledge.__new__(Knowledge)
        vector_db = MagicMock()
        vector_db.embedder = MagicMock()
        vector_db.upsert_available.return_value = False
        vector_db.insert.side_effect = insert_side_effect
        knowledge.vector_db = vector_db
        knowledge.contents_db = None
        knowledge._update_content = MagicMock()
        return knowledge

    def test_embedding_error_marks_failed_not_completed(self):
        error = EmbeddingError("Rate limit reached", status_code=429)
        knowledge = self._knowledge_with_db(insert_side_effect=error)
        content = Content(content_hash="abc")

        knowledge._handle_vector_db_insert(content, make_documents(0, 5), upsert=False)

        assert content.status == ContentStatus.FAILED
        knowledge._update_content.assert_called_once()

    def test_silent_partial_embedding_marks_partial(self):
        """Insert succeeds, but only some documents came back with vectors."""
        knowledge = self._knowledge_with_db()
        content = Content(content_hash="abc")

        knowledge._handle_vector_db_insert(content, make_documents(3, 5), upsert=False)

        assert content.status == ContentStatus.PARTIAL

    def test_fully_embedded_insert_marks_completed(self):
        knowledge = self._knowledge_with_db()
        content = Content(content_hash="abc")

        knowledge._handle_vector_db_insert(content, make_documents(5, 5), upsert=False)

        assert content.status == ContentStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_async_embedding_error_marks_failed(self):
        knowledge = Knowledge.__new__(Knowledge)
        vector_db = MagicMock()
        vector_db.embedder = MagicMock()
        vector_db.upsert_available.return_value = False
        vector_db.async_insert = AsyncMock(side_effect=EmbeddingError("boom", status_code=502))
        knowledge.vector_db = vector_db
        knowledge.contents_db = None
        knowledge._aupdate_content = AsyncMock()
        content = Content(content_hash="abc")

        await knowledge._ahandle_vector_db_insert(content, make_documents(0, 5), upsert=False)

        assert content.status == ContentStatus.FAILED
        knowledge._aupdate_content.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_async_partial_embedding_marks_partial(self):
        knowledge = Knowledge.__new__(Knowledge)
        vector_db = MagicMock()
        vector_db.embedder = MagicMock()
        vector_db.upsert_available.return_value = False
        vector_db.async_insert = AsyncMock()
        knowledge.vector_db = vector_db
        knowledge.contents_db = None
        knowledge._aupdate_content = AsyncMock()
        content = Content(content_hash="abc")

        await knowledge._ahandle_vector_db_insert(content, make_documents(2, 5), upsert=False)

        assert content.status == ContentStatus.PARTIAL


class TestEmbeddingRetry:
    """Transient embedding failures must be retried before any status is reported.

    A chunk lost to a passing rate limit is unretrievable forever, so the write is
    repeated in place while the chunk text is still in memory.
    """

    def _knowledge(self, side_effect, retries=3):
        knowledge = Knowledge.__new__(Knowledge)
        vector_db = MagicMock()
        vector_db.embedder = MagicMock()
        vector_db.upsert_available.return_value = False
        vector_db.insert.side_effect = side_effect
        knowledge.vector_db = vector_db
        knowledge.contents_db = None
        knowledge._update_content = MagicMock()
        knowledge.max_embedding_retries = retries
        knowledge.embedding_retry_backoff = 0.0
        return knowledge

    def test_transient_failure_recovers_and_reports_completed(self):
        calls = {"n": 0}

        def flaky(*args, **kwargs):
            calls["n"] += 1
            if calls["n"] < 3:
                raise EmbeddingError("Rate limit reached", status_code=429)

        knowledge = self._knowledge(flaky)
        content = Content(name="q3.pdf")

        knowledge._handle_vector_db_insert(content, make_documents(10, 10), upsert=False)

        assert calls["n"] == 3
        assert content.status == ContentStatus.COMPLETED

    def test_authentication_failure_is_not_retried(self):
        calls = {"n": 0}

        def bad_key(*args, **kwargs):
            calls["n"] += 1
            raise EmbeddingError("Incorrect API key provided", status_code=401)

        knowledge = self._knowledge(bad_key)
        content = Content(name="q3.pdf")

        knowledge._handle_vector_db_insert(content, make_documents(0, 10), upsert=False)

        assert calls["n"] == 1, "a rejected credential fails identically on every attempt"
        assert content.status == ContentStatus.FAILED

    def test_retries_are_exhausted_then_reported(self):
        calls = {"n": 0}

        def always(*args, **kwargs):
            calls["n"] += 1
            raise EmbeddingError("Rate limit reached", status_code=429)

        knowledge = self._knowledge(always, retries=2)
        content = Content(name="q3.pdf")

        knowledge._handle_vector_db_insert(content, make_documents(4, 10), upsert=False)

        assert calls["n"] == 3  # first attempt plus two retries
        assert content.status == ContentStatus.FAILED

    def test_retries_can_be_disabled(self):
        calls = {"n": 0}

        def always(*args, **kwargs):
            calls["n"] += 1
            raise EmbeddingError("Rate limit reached", status_code=429)

        knowledge = self._knowledge(always, retries=0)
        content = Content(name="q3.pdf")

        knowledge._handle_vector_db_insert(content, make_documents(0, 10), upsert=False)

        assert calls["n"] == 1

    def test_non_embedding_errors_are_not_retried(self):
        """Only embedding failures are retryable here; other errors surface as-is."""
        calls = {"n": 0}

        def boom(*args, **kwargs):
            calls["n"] += 1
            raise RuntimeError("table is gone")

        knowledge = self._knowledge(boom)
        content = Content(name="q3.pdf")

        knowledge._handle_vector_db_insert(content, make_documents(0, 10), upsert=False)

        assert calls["n"] == 1
        assert content.status == ContentStatus.FAILED

    @pytest.mark.asyncio
    async def test_async_transient_failure_recovers(self):
        calls = {"n": 0}

        async def flaky(*args, **kwargs):
            calls["n"] += 1
            if calls["n"] < 3:
                raise EmbeddingError("Rate limit reached", status_code=429)

        knowledge = Knowledge.__new__(Knowledge)
        vector_db = MagicMock()
        vector_db.embedder = MagicMock()
        vector_db.upsert_available.return_value = False
        vector_db.async_insert = flaky
        knowledge.vector_db = vector_db
        knowledge.contents_db = None
        knowledge._aupdate_content = AsyncMock()
        knowledge.max_embedding_retries = 3
        knowledge.embedding_retry_backoff = 0.0
        content = Content(name="q3.pdf")

        await knowledge._ahandle_vector_db_insert(content, make_documents(10, 10), upsert=False)

        assert calls["n"] == 3
        assert content.status == ContentStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_async_authentication_failure_is_not_retried(self):
        calls = {"n": 0}

        async def bad_key(*args, **kwargs):
            calls["n"] += 1
            raise EmbeddingError("Incorrect API key provided", status_code=401)

        knowledge = Knowledge.__new__(Knowledge)
        vector_db = MagicMock()
        vector_db.embedder = MagicMock()
        vector_db.upsert_available.return_value = False
        vector_db.async_insert = bad_key
        knowledge.vector_db = vector_db
        knowledge.contents_db = None
        knowledge._aupdate_content = AsyncMock()
        knowledge.max_embedding_retries = 3
        knowledge.embedding_retry_backoff = 0.0
        content = Content(name="q3.pdf")

        await knowledge._ahandle_vector_db_insert(content, make_documents(0, 10), upsert=False)

        assert calls["n"] == 1
        assert content.status == ContentStatus.FAILED


class TestSecretRedaction:
    """Provider messages are persisted and served, so credential shapes are scrubbed."""

    @pytest.mark.parametrize(
        "raw",
        [
            "Incorrect API key provided: sk-abc123XYZdef456",
            "Incorrect API key provided: sk-proj-abc123realkeyvalue456",
            # OpenAI echoes a partially masked key; normalise it rather than pass it through
            "Incorrect API key provided: sk-proj-**************************TEST",
            "Authorization: Bearer eyJhbGciOiJIUzI1NiJ9abcdef",
            "invalid api_key=supersecretvalue123",
            "token 0123456789abcdef0123456789abcdef",
        ],
    )
    def test_credential_shapes_are_redacted(self, raw):
        from agno.exceptions import redact_secrets

        cleaned = redact_secrets(raw)

        assert "[redacted]" in cleaned
        for leak in ("sk-abc123XYZdef456", "supersecretvalue123", "eyJhbGciOiJIUzI1NiJ9abcdef"):
            assert leak not in cleaned

    @pytest.mark.parametrize(
        "raw",
        [
            "Rate limit reached for text-embedding-3-small",
            "maximum context length is 8191 tokens, however you requested 9000",
            "connection reset by peer",
        ],
    )
    def test_diagnostic_text_is_preserved(self, raw):
        from agno.exceptions import redact_secrets

        assert redact_secrets(raw) == raw


class TestReingestGuidance:
    """The message must say how to re-run ingestion, which differs by source."""

    def test_uploaded_file_is_told_to_upload_again(self):
        """Uploaded bytes are never retained, so the caller has to supply them."""
        knowledge = make_knowledge()
        content = Content(name="q3-report.pdf")
        error = EmbeddingError("Incorrect API key provided", status_code=401)

        knowledge._set_embedding_failure_status(content, error, make_documents(0, 10), "insert")

        assert "not retained" in content.status_message
        assert "upload it again" in content.status_message

    @pytest.mark.parametrize(
        "content,expected",
        [
            (Content(name="q3.pdf", path="/data/q3.pdf"), "/data/q3.pdf"),
            (Content(name="d", url="https://example.com/a.txt"), "https://example.com/a.txt"),
        ],
    )
    def test_a_reachable_source_is_named_instead_of_asking_for_a_re_upload(self, content, expected):
        """A file still on disk or a URL can be re-ingested without the caller resupplying it."""
        knowledge = make_knowledge()
        error = EmbeddingError("Service unavailable", status_code=503)

        knowledge._set_embedding_failure_status(content, error, make_documents(0, 3), "insert")

        assert expected in content.status_message
        assert "not retained" not in content.status_message

    def test_remote_source_is_not_told_to_re_upload(self):
        knowledge = make_knowledge()
        content = Content(name="q3.pdf", remote_content=object())

        knowledge._set_embedding_failure_status(
            content, EmbeddingError("Service unavailable", status_code=503), make_documents(0, 3), "insert"
        )

        assert "remote source" in content.status_message
        assert "not retained" not in content.status_message

    def test_url_source_is_told_which_url_to_re_ingest(self):
        knowledge = make_knowledge()
        content = Content(name="agno docs", metadata={"_agno": {"source_url": "https://docs.agno.com/intro"}})
        error = EmbeddingError("Rate limit reached", status_code=429)

        knowledge._set_embedding_failure_status(content, error, make_documents(0, 10), "insert", attempts=4)

        assert "https://docs.agno.com/intro" in content.status_message
        assert "not retained" not in content.status_message

    def test_failed_ingest_also_says_how_to_recover(self):
        knowledge = make_knowledge()
        content = Content(name="q3-report.pdf")
        error = EmbeddingError("Rate limit reached", status_code=429)

        knowledge._set_embedding_failure_status(content, error, make_documents(7, 10), "insert", attempts=4)

        assert content.status == ContentStatus.FAILED
        assert "upload it again" in content.status_message

    def test_message_has_no_trailing_whitespace(self):
        knowledge = make_knowledge()
        content = Content(name="q3-report.pdf")

        knowledge._set_embedding_failure_status(
            content, EmbeddingError("boom", status_code=502), make_documents(0, 3), "insert"
        )

        assert content.status_message == content.status_message.strip()


class TestIncompleteContentIsNotSkipped:
    """Re-ingesting content that did not finish embedding must actually repair it."""

    def _knowledge(self):
        knowledge = Knowledge.__new__(Knowledge)
        vector_db = MagicMock()
        vector_db.content_hash_exists.return_value = True
        knowledge.vector_db = vector_db
        return knowledge

    @pytest.mark.parametrize("prior", [ContentStatus.PARTIAL, ContentStatus.FAILED])
    def test_incomplete_content_is_re_ingested(self, prior):
        """The hash exists, but skipping would leave the missing chunks missing."""
        knowledge = self._knowledge()

        assert knowledge._should_skip("hash", skip_if_exists=True, prior_status=prior) is False

    @pytest.mark.parametrize("prior", [ContentStatus.COMPLETED, None])
    def test_complete_content_is_still_skipped(self, prior):
        knowledge = self._knowledge()

        assert knowledge._should_skip("hash", skip_if_exists=True, prior_status=prior) is True

    def test_skip_if_exists_false_always_re_ingests(self):
        knowledge = self._knowledge()

        assert knowledge._should_skip("hash", skip_if_exists=False, prior_status=ContentStatus.COMPLETED) is False


class TestRetryConfigEdgeCases:
    def _knowledge(self, retries, backoff):
        knowledge = Knowledge.__new__(Knowledge)
        vector_db = MagicMock()
        vector_db.embedder = MagicMock()
        vector_db.upsert_available.return_value = False
        vector_db.insert.side_effect = lambda *a, **kw: (_ for _ in ()).throw(
            EmbeddingError("Rate limit reached", status_code=429, provider="OpenAI")
        )
        knowledge.vector_db = vector_db
        knowledge.contents_db = None
        knowledge._update_content = MagicMock()
        knowledge.max_embedding_retries = retries
        knowledge.embedding_retry_backoff = backoff
        return knowledge

    def test_negative_backoff_does_not_break_the_retry_loop(self):
        """A negative delay would make sleep raise, losing the retries and the reason."""
        knowledge = self._knowledge(retries=2, backoff=-1.0)
        content = Content(name="doc")

        knowledge._handle_vector_db_insert(content, make_documents(0, 3), upsert=False)

        assert content.status == ContentStatus.FAILED
        assert "rate_limit" in content.status_message, "the real reason must survive"

    @pytest.mark.parametrize("retries", [-5, 0, None])
    def test_non_positive_retries_mean_a_single_attempt(self, retries):
        knowledge = self._knowledge(retries=retries, backoff=0.0)

        assert knowledge._retry_attempts() == 1

    def test_delay_is_never_negative(self):
        knowledge = self._knowledge(retries=3, backoff=-2.0)

        assert all(knowledge._retry_delay(i) >= 0 for i in range(4))


class TestPriorStatusIsDefensive:
    """A contents-db problem must degrade to 'unknown', never break ingestion."""

    def test_missing_contents_db_returns_none(self):
        knowledge = Knowledge.__new__(Knowledge)
        knowledge.contents_db = None

        assert knowledge._prior_status("cid") is None

    def test_db_read_failure_returns_none(self):
        knowledge = Knowledge.__new__(Knowledge)
        failing = MagicMock()
        failing.get_knowledge_content.side_effect = RuntimeError("db down")
        knowledge.contents_db = failing

        assert knowledge._prior_status("cid") is None

    def test_async_db_is_skipped_by_the_sync_helper(self):
        from agno.db.base import AsyncBaseDb

        knowledge = Knowledge.__new__(Knowledge)
        knowledge.contents_db = MagicMock(spec=AsyncBaseDb)

        assert knowledge._prior_status("cid") is None


class TestRedactionKeepsDiagnostics:
    """Redaction must not destroy the identifiers needed to debug a failure."""

    @pytest.mark.parametrize(
        "text",
        [
            # md5 content hashes and chunk ids are 32 hex characters
            "Chunk 0123456789abcdef0123456789abcdef could not be parsed",
            "Document a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4 failed",
            "maximum context length is 8191 tokens, however you requested 9000",
            "Model text-embedding-3-small returned 400",
        ],
    )
    def test_diagnostic_identifiers_survive(self, text):
        from agno.exceptions import redact_secrets

        assert redact_secrets(text) == text

    @pytest.mark.parametrize(
        "text,leak",
        [
            ("Incorrect API key provided: sk-abc123XYZdef456", "sk-abc123XYZdef456"),
            ("Authorization: Bearer eyJhbGciOiJIUzI1NiJ9abcdef", "eyJhbGciOiJIUzI1NiJ9abcdef"),
            ("invalid api_key=supersecretvalue123", "supersecretvalue123"),
            ("token 0123456789abcdef0123456789abcdef", "0123456789abcdef0123456789abcdef"),
        ],
    )
    def test_credentials_are_still_redacted(self, text, leak):
        from agno.exceptions import redact_secrets

        cleaned = redact_secrets(text)

        assert leak not in cleaned
        assert "[redacted]" in cleaned


class TestSearchSurfacesQueryEmbeddingFailures:
    """A failed query embedding must not look like "no matches"."""

    STORES = [
        ("agno.vectordb.pgvector.pgvector", "PgVector"),
        ("agno.vectordb.redis.redisdb", "RedisDb"),
        ("agno.vectordb.valkey.valkeydb", "ValkeyDb"),
        ("agno.vectordb.weaviate.weaviate", "Weaviate"),
    ]

    @pytest.mark.parametrize("module_path,class_name", STORES, ids=[s[1] for s in STORES])
    def test_search_reraises_embedding_error(self, module_path, class_name):
        import ast
        import importlib

        try:
            module = importlib.import_module(module_path)
        except ImportError as e:
            pytest.skip(f"{module_path} unavailable: {e}")

        tree = ast.parse(inspect.getsource(module))
        embed_calls = {
            "get_embedding",
            "async_get_embedding",
            "get_embedding_and_usage",
            "async_get_embedding_and_usage",
        }
        unguarded = []
        for fn in ast.walk(tree):
            if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)) or "search" not in fn.name:
                continue
            for block in ast.walk(fn):
                if not isinstance(block, ast.Try):
                    continue
                embeds = any(
                    isinstance(n, ast.Call) and getattr(n.func, "attr", None) in embed_calls
                    for b in block.body
                    for n in ast.walk(b)
                )
                if not embeds:
                    continue
                if not any(
                    isinstance(h.type, ast.Name) and h.type.id == "EmbeddingError" for h in block.handlers
                ):
                    unguarded.append(f"{fn.name}@L{block.lineno}")

        assert not unguarded, (
            f"{class_name} swallows a failed query embedding in {unguarded}, so the caller "
            "sees an empty result set instead of the reason the search could not run"
        )


class TestPreClearDoesNotDestroyChunks:
    """Re-ingesting incomplete content must not leave the caller worse off.

    An insert-only store cannot roll a delete back, so the replacement chunks are
    embedded before the old ones are cleared.
    """

    def _knowledge(self):
        knowledge = Knowledge.__new__(Knowledge)
        vector_db = MagicMock()
        vector_db.embedder = MagicMock()
        vector_db.upsert_available.return_value = False
        knowledge.vector_db = vector_db
        knowledge.contents_db = None
        knowledge._update_content = MagicMock()
        knowledge._aupdate_content = AsyncMock()
        knowledge.max_embedding_retries = 0
        knowledge.embedding_retry_backoff = 0.0
        return knowledge, vector_db

    def _failing_documents(self):
        document = MagicMock(embedding=None)

        def boom(embedder=None):
            raise EmbeddingError("Incorrect API key", status_code=401, provider="OpenAI")

        async def aboom(embedder=None):
            raise EmbeddingError("Incorrect API key", status_code=401, provider="OpenAI")

        document.embed = boom
        document.async_embed = aboom
        return [document]

    @pytest.mark.parametrize("prior", [ContentStatus.PARTIAL, ContentStatus.FAILED])
    def test_failed_embed_leaves_existing_chunks_alone(self, prior):
        knowledge, vector_db = self._knowledge()
        content = Content(name="doc", id="cid", content_hash="h")

        knowledge._handle_vector_db_insert(content, self._failing_documents(), upsert=False, prior_status=prior)

        assert vector_db.delete_by_content_id.call_count == 0, "the old chunks must survive a failed retry"
        assert content.status == ContentStatus.FAILED
        assert "authentication" in content.status_message

    def test_successful_embed_still_clears_before_writing(self):
        """The pre-clear exists to stop duplicates, so it must still run on success."""
        knowledge, vector_db = self._knowledge()
        content = Content(name="doc", id="cid", content_hash="h")

        knowledge._handle_vector_db_insert(
            content, [MagicMock(embedding=[0.1])], upsert=False, prior_status=ContentStatus.PARTIAL
        )

        assert vector_db.delete_by_content_id.call_count == 1

    @pytest.mark.asyncio
    async def test_async_failed_embed_leaves_existing_chunks_alone(self):
        knowledge, vector_db = self._knowledge()
        content = Content(name="doc", id="cid", content_hash="h")

        await knowledge._ahandle_vector_db_insert(
            content, self._failing_documents(), upsert=False, prior_status=ContentStatus.PARTIAL
        )

        assert vector_db.delete_by_content_id.call_count == 0
        assert content.status == ContentStatus.FAILED
