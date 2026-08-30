"""Verify that exception handlers chain the original cause via ``from``.

Every ``except ... as e: raise X(...)`` site in the tools, models, and
vectordb packages must use ``from e`` so that ``__cause__`` is preserved
(PEP 3134).  Without it the original traceback is lost and debugging
provider failures, connection errors, and cache-validation issues becomes
unnecessarily hard.

Fixes https://github.com/agno-agi/agno/issues/9857
"""

from __future__ import annotations

from typing import Any, Iterator, Optional
from unittest.mock import MagicMock, Mock, patch

import pytest

from agno.exceptions import ModelProviderError, RetryableModelProviderError
from agno.models.base import Model, ModelResponse


# ---------------------------------------------------------------------------
# Concrete Model stub (Model is abstract)
# ---------------------------------------------------------------------------

class _StubModel(Model):
    def invoke(self, *args, **kwargs) -> ModelResponse:
        raise NotImplementedError

    def invoke_stream(self, *args, **kwargs) -> Iterator[ModelResponse]:
        raise NotImplementedError

    async def ainvoke(self, *args, **kwargs) -> ModelResponse:
        raise NotImplementedError

    async def ainvoke_stream(self, *args, **kwargs):
        raise NotImplementedError

    def _parse_provider_response(self, response: Any) -> ModelResponse:
        raise NotImplementedError

    def _parse_provider_response_delta(self, response: Any) -> ModelResponse:
        raise NotImplementedError


# ---------------------------------------------------------------------------
# tools/zendesk.py — ConnectionError from requests.RequestException
# ---------------------------------------------------------------------------

class TestZendeskExceptionChaining:
    def test_search_zendesk_chains_request_exception(self):
        import requests

        from agno.tools.zendesk import ZendeskTools

        tools = ZendeskTools(username="u", password="p", company_name="c")
        original = requests.ConnectionError("connection refused")
        with patch("agno.tools.zendesk.requests.get", side_effect=original):
            with pytest.raises(ConnectionError) as exc_info:
                tools.search_zendesk("query")
            assert exc_info.value.__cause__ is original


# ---------------------------------------------------------------------------
# tools/gitlab.py — ValueError from gitlab init failure
# ---------------------------------------------------------------------------

class TestGitlabExceptionChaining:
    def test_create_client_chains_cause(self):
        pytest.importorskip("gitlab")
        from agno.tools.gitlab import GitlabTools

        original = RuntimeError("auth failed")
        with patch("agno.tools.gitlab.gitlab.Gitlab") as mock_gl:
            mock_gl.return_value = MagicMock()
            tools = GitlabTools(access_token="tok")
        with patch("agno.tools.gitlab.gitlab.Gitlab", side_effect=original):
            with pytest.raises(ValueError) as exc_info:
                tools._create_client()
            assert exc_info.value.__cause__ is original


# ---------------------------------------------------------------------------
# tools/brightdata.py — Exception from requests failure
# ---------------------------------------------------------------------------

class TestBrightdataExceptionChaining:
    def test_make_request_chains_request_exception(self):
        import requests

        from agno.tools.brightdata import BrightDataTools

        tools = BrightDataTools(api_key="key")
        original = requests.ConnectionError("timeout")
        with patch("agno.tools.brightdata.requests.post", side_effect=original):
            with pytest.raises(Exception) as exc_info:
                tools._make_request({"url": "http://example.com", "zone": "z"})
            assert exc_info.value.__cause__ is original


# ---------------------------------------------------------------------------
# tools/models/gemini.py — ValueError from Client init failure
# ---------------------------------------------------------------------------

class TestGeminiToolExceptionChaining:
    def test_init_failure_chains_cause(self):
        original = RuntimeError("invalid API key")
        with patch("agno.tools.models.gemini.Client", side_effect=original):
            with pytest.raises(ValueError) as exc_info:
                from agno.tools.models.gemini import GeminiTools

                GeminiTools(api_key="bad-key")
            assert exc_info.value.__cause__ is original


# ---------------------------------------------------------------------------
# tools/aws_ses.py — Exception from SES send failure
# ---------------------------------------------------------------------------

class TestAwsSesExceptionChaining:
    def test_send_email_chains_cause(self):
        from agno.tools.aws_ses import AWSSESTool

        original = RuntimeError("SES quota exceeded")
        mock_client = MagicMock()
        mock_client.send_email.side_effect = original

        with patch("agno.tools.aws_ses.boto3") as mock_boto:
            mock_boto.client.return_value = mock_client
            tools = AWSSESTool(
                sender_email="a@b.com",
                sender_name="Test",
                region_name="us-east-1",
            )

        with pytest.raises(Exception) as exc_info:
            tools.send_email("subj", "body", "c@d.com")
        assert exc_info.value.__cause__ is original


# ---------------------------------------------------------------------------
# tools/function.py — _StaleCacheEntry from validation failures
# ---------------------------------------------------------------------------

class TestFunctionCacheExceptionChaining:
    def test_stale_cache_entry_chains_validation_error(self):
        from agno.tools.function import Function, _StaleCacheEntry

        fn = Function.model_construct(entrypoint=None)

        original = TypeError("unexpected type")
        with patch("agno.tools.function.ToolResult.model_validate", side_effect=original):
            with pytest.raises(_StaleCacheEntry) as exc_info:
                fn._cached_value({"a": 1}, "ToolResult")
            assert exc_info.value.__cause__ is original


# ---------------------------------------------------------------------------
# vectordb/mongodb — ConnectionError from pymongo failure
# ---------------------------------------------------------------------------

class TestMongodbExceptionChaining:
    def test_cosmos_connection_failure_chains_cause(self):
        pymongo = pytest.importorskip("pymongo")
        try:
            from pymongo import AsyncMongoClient  # noqa: F401
        except ImportError:
            pytest.skip("pymongo version too old (needs AsyncMongoClient)")

        from agno.vectordb.mongodb.mongodb import MongoDBVector

        original = pymongo.errors.ConnectionFailure("DNS resolution failed")
        with patch("agno.vectordb.mongodb.mongodb.MongoClient", side_effect=original):
            vec = MongoDBVector.__new__(MongoDBVector)
            vec._client = None
            vec.cosmos_compatibility = True
            vec.connection_string = "mongodb+srv://cosmos.azure.com"
            vec.database = "test"
            vec.kwargs = {}
            with pytest.raises(ConnectionError) as exc_info:
                vec._get_client()
            assert exc_info.value.__cause__ is original

    def test_mongodb_connection_failure_chains_cause(self):
        pymongo = pytest.importorskip("pymongo")
        try:
            from pymongo import AsyncMongoClient  # noqa: F401
        except ImportError:
            pytest.skip("pymongo version too old (needs AsyncMongoClient)")

        from agno.vectordb.mongodb.mongodb import MongoDBVector

        original = pymongo.errors.ConnectionFailure("connection refused")
        with patch("agno.vectordb.mongodb.mongodb.MongoClient", side_effect=original):
            vec = MongoDBVector.__new__(MongoDBVector)
            vec._client = None
            vec.cosmos_compatibility = False
            vec.connection_string = "mongodb://localhost"
            vec.database = "test"
            vec.kwargs = {}
            with pytest.raises(ConnectionError) as exc_info:
                vec._get_client()
            assert exc_info.value.__cause__ is original


# ---------------------------------------------------------------------------
# vectordb/couchbase — ConnectionError from Couchbase failure
# ---------------------------------------------------------------------------

class TestCouchbaseExceptionChaining:
    def test_cluster_connect_failure_chains_cause(self):
        pytest.importorskip("couchbase")
        from agno.vectordb.couchbase.couchbase import CouchbaseSearch

        vec = CouchbaseSearch.__new__(CouchbaseSearch)
        vec._cluster = None
        vec.connection_string = "couchbase://localhost"
        vec.username = "user"
        vec.password = "pass"
        vec.bucket_name = "b"
        vec.scope_name = "s"
        vec.collection_name = "c"

        original = Exception("auth failed")
        with patch("agno.vectordb.couchbase.couchbase.Cluster", side_effect=original):
            with pytest.raises(ConnectionError) as exc_info:
                _ = vec.cluster
            assert exc_info.value.__cause__ is original


# ---------------------------------------------------------------------------
# models/base.py — ModelProviderError from RetryableModelProviderError
# ---------------------------------------------------------------------------

class TestModelBaseExceptionChaining:
    def _make_model(self, **overrides):
        model = _StubModel.__new__(_StubModel)
        model.name = overrides.get("name", "test-model")
        model.id = overrides.get("id", "test-id")
        model.retries = overrides.get("retries", 0)
        model.retry_with_guidance_limit = overrides.get("retry_with_guidance_limit", 0)
        return model

    def test_retry_exhaustion_chains_retryable_error(self):
        model = self._make_model(retry_with_guidance_limit=0)

        original = RetryableModelProviderError(
            original_error="rate limit",
            retry_guidance_message="slow down",
        )
        model.invoke = Mock(side_effect=original)

        with pytest.raises(ModelProviderError) as exc_info:
            model._invoke_with_retry(messages=[])
        assert exc_info.value.__cause__ is original

    def test_non_retryable_error_chains_cause(self):
        model = self._make_model(retries=1)

        original = ModelProviderError(
            message="invalid model",
            model_name="test-model",
            model_id="test-id",
        )
        model.invoke = Mock(side_effect=original)
        model.classify_error = Mock(return_value=original)
        model._is_retryable_error = Mock(return_value=False)

        with pytest.raises(ModelProviderError) as exc_info:
            model._invoke_with_retry(messages=[])
        assert exc_info.value.__cause__ is original
