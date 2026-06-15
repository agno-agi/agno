import inspect

import pytest

# The 7 Knowledge-layer methods that must carry user_id as the LAST param.
SCOPED_METHODS = [
    "insert",
    "async_insert",
    "upsert",
    "async_upsert",
    "search",
    "async_search",
    "delete_by_content_id",
]


def _assert_user_id_param(method):
    """Assert method accepts a user_id kwarg defaulting to None."""
    sig = inspect.signature(method)
    assert "user_id" in sig.parameters, f"{method.__qualname__} is missing a user_id parameter"
    assert sig.parameters["user_id"].default is None, (
        f"{method.__qualname__} user_id default is {sig.parameters['user_id'].default!r}, expected None"
    )


def _get_langchain_db():
    pytest.importorskip("langchain_core")
    from agno.vectordb.langchaindb import LangChainVectorDb

    return LangChainVectorDb()


def _get_llamaindex_db():
    pytest.importorskip("llama_index.core")
    from agno.vectordb.llamaindex import LlamaIndexVectorDb

    return LlamaIndexVectorDb(knowledge_retriever=None)


def _get_lightrag_db():
    pytest.importorskip("httpx")
    from agno.vectordb.lightrag import LightRag

    return LightRag()


class TestSignatureContract:
    """Every wrapper's 7 scoped methods must accept user_id=None."""

    def test_langchaindb_signatures(self):
        db = _get_langchain_db()
        for name in SCOPED_METHODS:
            _assert_user_id_param(getattr(db, name))

    def test_llamaindexdb_signatures(self):
        db = _get_llamaindex_db()
        for name in SCOPED_METHODS:
            _assert_user_id_param(getattr(db, name))

    def test_lightrag_signatures(self):
        db = _get_lightrag_db()
        for name in SCOPED_METHODS:
            _assert_user_id_param(getattr(db, name))


class TestScopedCallFailsClosed:
    """A scoped call on a wrapper that can't isolate must raise NotImplementedError,
    never silently return unscoped results. Unscoped (user_id=None) calls are unaffected."""

    def test_lightrag_scoped_methods_raise(self):
        db = _get_lightrag_db()
        for name in ["insert", "upsert"]:
            with pytest.raises(NotImplementedError):
                getattr(db, name)("hash", [], user_id="alice")
        with pytest.raises(NotImplementedError):
            db.delete_by_content_id("content-id", user_id="alice")
        with pytest.raises(NotImplementedError):
            db.search("query", user_id="alice")

    async def test_lightrag_async_scoped_methods_raise(self):
        db = _get_lightrag_db()
        with pytest.raises(NotImplementedError):
            await db.async_insert("hash", [], user_id="alice")
        with pytest.raises(NotImplementedError):
            await db.async_upsert("hash", [], user_id="alice")
        with pytest.raises(NotImplementedError):
            await db.async_search("query", user_id="alice")

    def test_lightrag_unscoped_calls_pass_through(self):
        db = _get_lightrag_db()
        # user_id=None requests no isolation, so the write methods stay a passthrough.
        assert db.insert("hash", [], user_id=None) is None
        assert db.upsert("hash", [], user_id=None) is None
        assert db.delete_by_content_id("content-id", user_id=None) is None

    def test_llamaindex_scoped_search_raises(self):
        db = _get_llamaindex_db()
        with pytest.raises(NotImplementedError):
            db.search("query", user_id="alice")

    async def test_llamaindex_async_scoped_search_raises(self):
        db = _get_llamaindex_db()
        with pytest.raises(NotImplementedError):
            await db.async_search("query", user_id="alice")

    def test_llamaindex_write_methods_not_supported(self):
        db = _get_llamaindex_db()
        # insert/upsert are unsupported for everyone, not just scoped callers.
        for name in ["insert", "upsert"]:
            with pytest.raises(NotImplementedError):
                getattr(db, name)("hash", [], user_id="alice")
        # delete_by_content_id is unsupported and returns False (it can't leak, so it
        # must not raise — the Knowledge delete path doesn't wrap it in try/except).
        assert db.delete_by_content_id("content-id", user_id="alice") is False
        assert db.delete_by_content_id("content-id", user_id=None) is False

    async def test_llamaindex_async_write_methods_not_supported(self):
        db = _get_llamaindex_db()
        with pytest.raises(NotImplementedError):
            await db.async_insert("hash", [], user_id="alice")
        with pytest.raises(NotImplementedError):
            await db.async_upsert("hash", [], user_id="alice")

    def test_langchaindb_write_methods_not_supported(self):
        db = _get_langchain_db()
        # langchaindb forwards user_id on search; its write methods are unsupported.
        for name in ["insert", "upsert"]:
            with pytest.raises(NotImplementedError):
                getattr(db, name)("hash", [], user_id="alice")
        with pytest.raises(NotImplementedError):
            db.delete_by_content_id("content-id", user_id="alice")

    async def test_langchaindb_async_write_methods_not_supported(self):
        db = _get_langchain_db()
        with pytest.raises(NotImplementedError):
            await db.async_insert("hash", [], user_id="alice")
        with pytest.raises(NotImplementedError):
            await db.async_upsert("hash", [], user_id="alice")
