"""Adversarial tests for DatabricksEmbedder.

These tests try to break the embedder with malformed responses, edge cases
in batch processing, dimension auto-learning quirks, client reuse, async
error paths, and auth/settings edge cases.
"""

from unittest.mock import AsyncMock, Mock

import pytest

from agno.knowledge.embedder.databricks import DatabricksEmbedder


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_embedder(**kwargs):
    """Create an embedder with a mock client already injected."""
    defaults = dict(endpoint="test-ep", host="https://test.databricks.com")
    defaults.update(kwargs)
    return DatabricksEmbedder(**defaults)


def _mock_client(return_value=None, side_effect=None):
    client = Mock()
    if side_effect is not None:
        client.request_json.side_effect = side_effect
    else:
        client.request_json.return_value = return_value or {}
    return client


def _mock_async_client(return_value=None, side_effect=None):
    client = Mock()
    if side_effect is not None:
        client.request_json = AsyncMock(side_effect=side_effect)
    else:
        client.request_json = AsyncMock(return_value=return_value or {})
    return client


# ===================================================================
# 1. Empty / malformed responses
# ===================================================================

class TestMalformedResponses:
    """Responses that deviate from the expected OpenAI-style schema."""

    def test_empty_data_list(self):
        embedder = _make_embedder()
        embedder.client = _mock_client({"data": [], "usage": {"prompt_tokens": 1}})

        result = embedder.get_embedding("hello")
        assert result == []

    def test_data_items_missing_embedding_key(self):
        embedder = _make_embedder()
        embedder.client = _mock_client({
            "data": [{"index": 0, "vector": [1.0, 2.0]}],  # wrong key
        })

        result = embedder.get_embedding("hello")
        assert result == []

    def test_data_items_out_of_order(self):
        """Items arrive as index 2, 0, 1 -- should be sorted."""
        embedder = _make_embedder()
        embedder.client = _mock_client({
            "data": [
                {"index": 2, "embedding": [0.7, 0.8, 0.9]},
                {"index": 0, "embedding": [0.1, 0.2, 0.3]},
                {"index": 1, "embedding": [0.4, 0.5, 0.6]},
            ],
        })

        result = embedder.get_embedding("hello")
        # get_embedding returns the first after sorting -> index 0
        assert result == [0.1, 0.2, 0.3]

    def test_response_is_none(self):
        """_response returns None instead of a dict -- should not crash."""
        embedder = _make_embedder()
        embedder.client = _mock_client(None)

        # None.get("data") will raise AttributeError, caught by try/except
        result = embedder.get_embedding("hello")
        assert result == []

    def test_response_is_a_string(self):
        """API returns a raw string instead of dict."""
        embedder = _make_embedder()
        embedder.client = _mock_client("unexpected string response")

        result = embedder.get_embedding("hello")
        assert result == []

    def test_embedding_value_is_not_a_list(self):
        """Embedding value is a scalar or dict instead of list."""
        embedder = _make_embedder()
        embedder.client = _mock_client({
            "data": [{"index": 0, "embedding": 42}],
        })

        result = embedder.get_embedding("hello")
        assert result == []

    def test_embedding_value_is_none(self):
        embedder = _make_embedder()
        embedder.client = _mock_client({
            "data": [{"index": 0, "embedding": None}],
        })

        result = embedder.get_embedding("hello")
        assert result == []

    def test_data_is_none(self):
        """'data' key exists but is None."""
        embedder = _make_embedder()
        embedder.client = _mock_client({"data": None})

        result = embedder.get_embedding("hello")
        assert result == []

    def test_data_contains_non_dict_items(self):
        """data list contains mixed types -- non-dicts should be skipped."""
        embedder = _make_embedder()
        embedder.client = _mock_client({
            "data": [
                "garbage",
                42,
                {"index": 0, "embedding": [1.0, 2.0]},
                None,
            ],
        })

        result = embedder.get_embedding("hello")
        assert result == [1.0, 2.0]

    def test_missing_index_defaults_to_zero(self):
        """Items without 'index' key should default to 0 in sorting."""
        embedder = _make_embedder()
        embedder.client = _mock_client({
            "data": [
                {"embedding": [0.1, 0.2]},  # no index -> defaults to 0
                {"index": 1, "embedding": [0.3, 0.4]},
            ],
        })

        result = embedder.get_embedding("hello")
        assert result == [0.1, 0.2]

    def test_usage_is_not_a_dict(self):
        """Usage field is a string instead of dict."""
        embedder = _make_embedder()
        embedder.client = _mock_client({
            "data": [{"index": 0, "embedding": [1.0]}],
            "usage": "not-a-dict",
        })

        _, usage = embedder.get_embedding_and_usage("hello")
        assert usage is None

    def test_usage_missing_entirely(self):
        embedder = _make_embedder()
        embedder.client = _mock_client({
            "data": [{"index": 0, "embedding": [1.0]}],
        })

        _, usage = embedder.get_embedding_and_usage("hello")
        assert usage is None


# ===================================================================
# 2. Batch processing edge cases
# ===================================================================

class TestBatchProcessing:

    def test_empty_texts_list(self):
        embedder = _make_embedder(batch_size=5)
        embedder.client = _mock_client()

        embeddings, usages = embedder.get_embeddings_batch_and_usage([])

        assert embeddings == []
        assert usages == []
        embedder.client.request_json.assert_not_called()

    def test_single_text(self):
        embedder = _make_embedder(batch_size=5)
        embedder.client = _mock_client({
            "data": [{"index": 0, "embedding": [0.1, 0.2]}],
            "usage": {"prompt_tokens": 1},
        })

        embeddings, usages = embedder.get_embeddings_batch_and_usage(["hello"])

        assert embeddings == [[0.1, 0.2]]
        assert len(usages) == 1

    def test_batch_size_larger_than_texts(self):
        """batch_size=100, texts has 2 items -- should still work in one call."""
        embedder = _make_embedder(batch_size=100)
        embedder.client = _mock_client({
            "data": [
                {"index": 0, "embedding": [0.1]},
                {"index": 1, "embedding": [0.2]},
            ],
            "usage": {"prompt_tokens": 2},
        })

        embeddings, usages = embedder.get_embeddings_batch_and_usage(["a", "b"])

        assert len(embeddings) == 2
        assert embedder.client.request_json.call_count == 1

    def test_all_items_fail_in_batch_and_fallback(self):
        """Batch fails, then every individual call also fails."""
        embedder = _make_embedder(batch_size=10)
        embedder.client = _mock_client(side_effect=RuntimeError("always fails"))

        embeddings, usages = embedder.get_embeddings_batch_and_usage(["a", "b"])

        # Individual fallback also fails -> each returns ([], None)
        assert embeddings == [[], []]
        assert usages == [None, None]

    def test_batch_fails_some_individual_succeed(self):
        """Batch call fails, fallback: first text succeeds, second fails."""
        embedder = _make_embedder(batch_size=10)
        embedder.client = _mock_client(side_effect=[
            RuntimeError("batch fails"),
            {"data": [{"index": 0, "embedding": [1.0, 2.0]}], "usage": {"t": 1}},
            RuntimeError("second individual fails"),
        ])

        embeddings, usages = embedder.get_embeddings_batch_and_usage(["a", "b"])

        assert embeddings[0] == [1.0, 2.0]
        assert embeddings[1] == []
        assert usages[0] == {"t": 1}
        assert usages[1] is None

    def test_multiple_batches(self):
        """5 texts with batch_size=2 -> 3 batch calls."""
        embedder = _make_embedder(batch_size=2)
        embedder.client = _mock_client(side_effect=[
            {"data": [{"index": 0, "embedding": [1.0]}, {"index": 1, "embedding": [2.0]}], "usage": {"t": 2}},
            {"data": [{"index": 0, "embedding": [3.0]}, {"index": 1, "embedding": [4.0]}], "usage": {"t": 2}},
            {"data": [{"index": 0, "embedding": [5.0]}], "usage": {"t": 1}},
        ])

        embeddings, usages = embedder.get_embeddings_batch_and_usage(
            ["a", "b", "c", "d", "e"]
        )

        assert len(embeddings) == 5
        assert embeddings == [[1.0], [2.0], [3.0], [4.0], [5.0]]
        assert embedder.client.request_json.call_count == 3

    def test_batch_usage_replication(self):
        """Usage is replicated per embedding, not per text."""
        embedder = _make_embedder(batch_size=10)
        # Response has 3 embeddings but data could be filtered
        embedder.client = _mock_client({
            "data": [
                {"index": 0, "embedding": [1.0]},
                {"index": 1, "embedding": [2.0]},
                # Item 2 has no embedding key -> filtered out
                {"index": 2, "vector": [3.0]},
            ],
            "usage": {"prompt_tokens": 3},
        })

        embeddings, usages = embedder.get_embeddings_batch_and_usage(["a", "b", "c"])

        # Only 2 valid embeddings extracted, so usage is replicated 2 times
        assert len(embeddings) == 2
        assert len(usages) == 2
        # This means texts[2] ("c") has NO corresponding embedding!
        # This is a potential bug: len(embeddings) != len(texts)


# ===================================================================
# 3. Dimension auto-learning
# ===================================================================

class TestDimensionAutoLearning:

    def test_dimension_learned_from_first_call(self):
        embedder = _make_embedder(dimensions=None)
        embedder.client = _mock_client({
            "data": [{"index": 0, "embedding": [0.1] * 768}],
        })

        embedder.get_embedding("hello")
        assert embedder.dimensions == 768

    def test_dimension_not_updated_once_set(self):
        """Once dimensions is set (even via auto-learn), it should not change
        because _update_dimensions_from_embeddings only updates when None."""
        embedder = _make_embedder(dimensions=None)

        # First call: 768-dim
        embedder.client = _mock_client({
            "data": [{"index": 0, "embedding": [0.1] * 768}],
        })
        embedder.get_embedding("first")
        assert embedder.dimensions == 768

        # Second call: 1024-dim -- dimensions should stay 768
        embedder.client = _mock_client({
            "data": [{"index": 0, "embedding": [0.2] * 1024}],
        })
        embedder.get_embedding("second")
        assert embedder.dimensions == 768

    def test_dimension_stays_none_on_failure(self):
        embedder = _make_embedder(dimensions=None)
        embedder.client = _mock_client(side_effect=RuntimeError("fail"))

        embedder.get_embedding("hello")
        assert embedder.dimensions is None

    def test_dimension_stays_none_on_empty_response(self):
        embedder = _make_embedder(dimensions=None)
        embedder.client = _mock_client({"data": []})

        embedder.get_embedding("hello")
        assert embedder.dimensions is None

    def test_explicit_dimensions_sent_in_request(self):
        embedder = _make_embedder(dimensions=512)
        embedder.client = _mock_client({
            "data": [{"index": 0, "embedding": [0.1] * 512}],
        })

        embedder.get_embedding("hello")

        call_args = embedder.client.request_json.call_args
        assert call_args[1]["json"]["dimensions"] == 512


# ===================================================================
# 4. Client reuse
# ===================================================================

class TestClientReuse:

    def test_get_client_returns_same_instance(self):
        embedder = _make_embedder()
        c1 = embedder.get_client()
        c2 = embedder.get_client()
        assert c1 is c2

    def test_get_async_client_returns_same_instance(self):
        embedder = _make_embedder()
        c1 = embedder.get_async_client()
        c2 = embedder.get_async_client()
        assert c1 is c2

    def test_injected_client_is_preserved(self):
        """If client is injected, get_client() should return it."""
        mock = Mock()
        embedder = _make_embedder()
        embedder.client = mock
        assert embedder.get_client() is mock

    def test_injected_async_client_is_preserved(self):
        mock = Mock()
        embedder = _make_embedder()
        embedder.async_client = mock
        assert embedder.get_async_client() is mock


# ===================================================================
# 5. Async paths
# ===================================================================

class TestAsyncPaths:

    @pytest.mark.asyncio
    async def test_async_get_embedding_failure(self):
        embedder = _make_embedder()
        embedder.async_client = _mock_async_client(side_effect=RuntimeError("boom"))

        result = await embedder.async_get_embedding("hello")
        assert result == []

    @pytest.mark.asyncio
    async def test_async_get_embedding_and_usage_failure(self):
        embedder = _make_embedder()
        embedder.async_client = _mock_async_client(side_effect=RuntimeError("boom"))

        embedding, usage = await embedder.async_get_embedding_and_usage("hello")
        assert embedding == []
        assert usage is None

    @pytest.mark.asyncio
    async def test_async_get_embedding_with_malformed_response(self):
        embedder = _make_embedder()
        embedder.async_client = _mock_async_client(return_value={"data": None})

        result = await embedder.async_get_embedding("hello")
        assert result == []

    @pytest.mark.asyncio
    async def test_async_batch_fallback(self):
        """Async batch fails, falls back to individual async calls."""
        embedder = _make_embedder(batch_size=10)
        embedder.async_client = _mock_async_client(side_effect=[
            RuntimeError("batch fails"),
            {"data": [{"index": 0, "embedding": [1.0]}], "usage": {"t": 1}},
            {"data": [{"index": 0, "embedding": [2.0]}], "usage": {"t": 1}},
        ])

        embeddings, usages = await embedder.async_get_embeddings_batch_and_usage(
            ["a", "b"]
        )

        assert embeddings == [[1.0], [2.0]]
        assert len(usages) == 2

    @pytest.mark.asyncio
    async def test_async_batch_all_fail(self):
        embedder = _make_embedder(batch_size=10)
        embedder.async_client = _mock_async_client(
            side_effect=RuntimeError("always fails")
        )

        embeddings, usages = await embedder.async_get_embeddings_batch_and_usage(
            ["a", "b"]
        )

        assert embeddings == [[], []]
        assert usages == [None, None]

    @pytest.mark.asyncio
    async def test_async_batch_empty_texts(self):
        embedder = _make_embedder(batch_size=5)
        embedder.async_client = _mock_async_client()

        embeddings, usages = await embedder.async_get_embeddings_batch_and_usage([])

        assert embeddings == []
        assert usages == []

    @pytest.mark.asyncio
    async def test_async_dimension_auto_learn(self):
        embedder = _make_embedder(dimensions=None)
        embedder.async_client = _mock_async_client(return_value={
            "data": [{"index": 0, "embedding": [0.1] * 256}],
        })

        await embedder.async_get_embedding("hello")
        assert embedder.dimensions == 256


# ===================================================================
# 6. Settings / auth edge cases
# ===================================================================

class TestSettingsAuth:

    def test_no_host_no_token_no_env(self, monkeypatch):
        """With no host/token and env vars cleared, client still constructs
        (settings will have None values)."""
        monkeypatch.delenv("DATABRICKS_HOST", raising=False)
        monkeypatch.delenv("DATABRICKS_TOKEN", raising=False)
        monkeypatch.delenv("DATABRICKS_PAT", raising=False)
        monkeypatch.delenv("DATABRICKS_WORKSPACE_URL", raising=False)

        embedder = DatabricksEmbedder(endpoint="my-ep")
        client = embedder.get_client()

        assert client.settings.host is None
        assert client.settings.token is None

    def test_custom_endpoint_name(self):
        embedder = DatabricksEmbedder(endpoint="my-custom-endpoint")
        params = embedder._build_request_params("hello")
        assert params["model"] == "my-custom-endpoint"

    def test_endpoint_defaults_to_id(self):
        embedder = DatabricksEmbedder(id="some-model-id")
        assert embedder.endpoint == "some-model-id"
        params = embedder._build_request_params("hello")
        assert params["model"] == "some-model-id"

    def test_request_params_override(self):
        embedder = _make_embedder(request_params={"extra_key": "extra_val"})
        params = embedder._build_request_params("hello")
        assert params["extra_key"] == "extra_val"

    def test_request_params_override_can_clobber_model(self):
        """request_params can override the 'model' field -- potentially a bug."""
        embedder = _make_embedder(
            endpoint="original-ep",
            request_params={"model": "clobbered-model"},
        )
        params = embedder._build_request_params("hello")
        assert params["model"] == "clobbered-model"

    def test_request_params_override_in_batch(self):
        embedder = _make_embedder(request_params={"instruction": "search"})
        params = embedder._build_batch_request_params(["a", "b"])
        assert params["instruction"] == "search"
        assert params["input"] == ["a", "b"]

    def test_workspace_url_separate_from_host(self):
        """workspace_url can differ from host."""
        embedder = DatabricksEmbedder(
            endpoint="ep",
            host="https://host.databricks.com",
            workspace_url="https://workspace.databricks.com",
        )
        settings = embedder._get_settings()
        # workspace_url explicit should win over host-derived
        assert settings.workspace_url == "https://workspace.databricks.com"

    def test_dimensions_override_in_base_class(self):
        """Base Embedder sets dimensions=1536, DatabricksEmbedder overrides to None."""
        embedder = DatabricksEmbedder(endpoint="ep")
        assert embedder.dimensions is None

    def test_batch_size_from_base_class(self):
        """batch_size defaults to 100 from Embedder base."""
        embedder = DatabricksEmbedder(endpoint="ep")
        assert embedder.batch_size == 100

    def test_max_retries_propagated(self):
        embedder = DatabricksEmbedder(
            endpoint="ep",
            host="https://test.databricks.com",
            max_retries=7,
        )
        client = embedder.get_client()
        assert client.settings.max_retries == 7

    def test_timeout_propagated(self):
        embedder = DatabricksEmbedder(
            endpoint="ep",
            host="https://test.databricks.com",
            timeout=120.0,
        )
        client = embedder.get_client()
        assert client.settings.timeout == 120.0
