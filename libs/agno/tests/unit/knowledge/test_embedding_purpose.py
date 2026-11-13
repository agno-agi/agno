import asyncio
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from cohere.types.embed_response import EmbeddingsFloatsEmbedResponse

from agno.knowledge.document import Document
from agno.knowledge.embedder.base import Embedder
from agno.knowledge.embedder.cohere import CohereEmbedder
from agno.knowledge.embedder.google import GeminiEmbedder
from agno.vectordb.base import aembed_before_replace
from agno.vectordb.qdrant import Qdrant


@pytest.fixture(params=["cohere", "gemini"])
def provider(request):
    calls = []
    fail_batch = [False]

    def respond(**kwargs):
        calls.append(deepcopy(kwargs))
        texts = kwargs.get("texts", kwargs.get("contents"))
        texts = texts if isinstance(texts, list) else [texts]
        if fail_batch[0] and len(texts) > 1:
            raise RuntimeError("retry individually")
        vectors = [[1.0, 0.0, 0.0, 0.5] for _ in texts]
        if request.param == "cohere":
            return EmbeddingsFloatsEmbedResponse.model_construct(embeddings=vectors, meta=None)
        return SimpleNamespace(embeddings=[SimpleNamespace(values=value) for value in vectors], metadata=None)

    async def arespond(**kwargs):
        await asyncio.sleep(0)
        return respond(**kwargs)

    if request.param == "cohere":
        embedder = CohereEmbedder(
            dimensions=4,
            cohere_client=SimpleNamespace(embed=respond),
            async_client=SimpleNamespace(embed=arespond),
        )
        document_type, query_type, field = "search_document", "search_query", "input_type"

        def task_type(call):
            return call["input_type"]
    else:
        embedder = GeminiEmbedder(
            dimensions=4,
            gemini_client=SimpleNamespace(
                models=SimpleNamespace(embed_content=respond),
                aio=SimpleNamespace(models=SimpleNamespace(embed_content=arespond)),
            ),
        )
        document_type, query_type, field = "RETRIEVAL_DOCUMENT", "RETRIEVAL_QUERY", "task_type"

        def task_type(call):
            return call["config"]["task_type"]

    return SimpleNamespace(
        embedder=embedder,
        calls=calls,
        fail_batch=fail_batch,
        task_type=task_type,
        document_type=document_type,
        query_type=query_type,
        field=field,
    )


@pytest.mark.parametrize("async_mode,batch", [(False, False), (True, False), (True, True)])
async def test_ingestion_and_search_send_different_purposes(provider, async_mode, batch):
    provider.embedder.enable_batch = batch
    db = Qdrant(collection="documents", location=":memory:", embedder=provider.embedder)
    documents = [Document(content="document one"), Document(content="document two")]
    try:
        if async_mode:
            await db.async_create()
            await db.async_insert(documents=documents, content_hash="content")
            results = await db.async_search("query")
        else:
            db.create()
            db.insert(documents=documents, content_hash="content")
            results = db.search("query")
        assert len(results) == 2
        purposes = [provider.task_type(call) for call in provider.calls]
        assert purposes[-1] == provider.query_type
        assert all(value == provider.document_type for value in purposes[:-1])
        assert getattr(provider.embedder, provider.field) == provider.query_type
    finally:
        if db._client is not None:
            db._client.close()
        if db._async_client is not None:
            await db._async_client.close()


@pytest.mark.parametrize(
    "method",
    [
        "get_embedding",
        "get_embedding_and_usage",
        "async_get_embedding",
        "async_get_embedding_and_usage",
        "async_get_embeddings_batch_and_usage",
    ],
)
async def test_explicit_purpose_for_each_embedding_api(provider, method):
    call = getattr(provider.embedder, method)
    text = ["one", "two"] if "batch" in method else "one"
    for purpose, expected in [("document", provider.document_type), ("query", provider.query_type)]:
        result = call(text, purpose=purpose)
        if method.startswith("async_"):
            await result
        assert provider.task_type(provider.calls[-1]) == expected


async def test_batch_fallback_keeps_document_purpose(provider):
    provider.fail_batch[0] = True
    provider.embedder.enable_batch = True
    documents = [Document(content="one"), Document(content="two")]
    await aembed_before_replace(documents, provider.embedder)
    assert all(document.embedding for document in documents)
    assert len(provider.calls) == 3
    assert all(provider.task_type(call) == provider.document_type for call in provider.calls)


@pytest.mark.parametrize("request_override", [False, True])
async def test_explicit_non_search_configuration_is_preserved(provider, request_override):
    task = "clustering" if provider.field == "input_type" else "CLUSTERING"
    if request_override:
        provider.embedder.request_params = (
            {"input_type": task} if provider.field == "input_type" else {"config": {"task_type": task}}
        )
    else:
        setattr(provider.embedder, provider.field, task)
    document = Document(content="one")
    document.embed(provider.embedder)
    await document.async_embed(provider.embedder)
    assert all(provider.task_type(call) == task for call in provider.calls)


async def test_concurrent_document_and_query_calls_do_not_mutate_configuration(provider):
    provider.embedder.request_params = (
        {"input_type": provider.query_type}
        if provider.field == "input_type"
        else {"config": {"task_type": provider.query_type, "output_dimensionality": 4}}
    )
    before = deepcopy(provider.embedder.request_params)
    document = Document(content="document")
    await asyncio.gather(
        document.async_embed(provider.embedder),
        provider.embedder.async_get_embedding("query", purpose="query"),
    )
    assert sorted(provider.task_type(call) for call in provider.calls) == sorted(
        [provider.document_type, provider.query_type]
    )
    assert provider.embedder.request_params == before
    assert getattr(provider.embedder, provider.field) == provider.query_type


class LegacyEmbedder(Embedder):
    def get_embedding_and_usage(self, text):
        return [1.0, 0.0], {"tokens": 1}

    async def async_get_embedding_and_usage(self, text):
        return self.get_embedding_and_usage(text)

    async def async_get_embeddings_batch_and_usage(self, texts):
        return [[1.0, 0.0] for _ in texts], [None for _ in texts]


async def test_legacy_embedder_signatures_remain_supported():
    embedder = LegacyEmbedder(enable_batch=True)
    document = Document(content="one")
    document.embed(embedder)
    await document.async_embed(embedder)
    pending = Document(content="two")
    await aembed_before_replace([pending], embedder)
    assert document.embedding == pending.embedding == [1.0, 0.0]


async def test_direct_calls_without_purpose_keep_explicit_configuration(provider):
    setattr(provider.embedder, provider.field, provider.document_type)
    provider.embedder.get_embedding("document")
    await provider.embedder.async_get_embedding("document")
    assert all(provider.task_type(call) == provider.document_type for call in provider.calls)
    provider.embedder.get_embedding("query", purpose="query")
    assert provider.task_type(provider.calls[-1]) == provider.query_type
    assert getattr(provider.embedder, provider.field) == provider.document_type


def test_sdk_config_is_copied_and_query_does_not_carry_document_title():
    from google.genai.types import EmbedContentConfig

    config = EmbedContentConfig(task_type="RETRIEVAL_QUERY", title="Document title", output_dimensionality=4)
    embedder = GeminiEmbedder(request_params={"config": config})
    document = embedder._get_request_params("document", purpose="document")["config"]
    query = embedder._get_request_params("query", purpose="query")["config"]
    assert document.task_type == "RETRIEVAL_DOCUMENT"
    assert document.title == "Document title"
    assert query.task_type == "RETRIEVAL_QUERY"
    assert query.title is None
    assert config.task_type == "RETRIEVAL_QUERY"
    assert config.title == "Document title"


def test_legacy_provider_override_keeps_its_original_signature():
    class CustomEmbedder(CohereEmbedder):
        def get_embedding_and_usage(self, text):
            return [1.0], None

    document = Document(content="one")
    document.embed(CustomEmbedder())
    assert document.embedding == [1.0]


async def test_reduced_batch_retries_keep_document_purpose():
    calls = []

    async def respond(**kwargs):
        calls.append(kwargs)
        if len(kwargs["texts"]) > 1:
            raise RuntimeError("429 rate limit")
        return EmbeddingsFloatsEmbedResponse.model_construct(embeddings=[[1.0]], meta=None)

    embedder = CohereEmbedder(async_client=SimpleNamespace(embed=respond), exponential_backoff=True)
    embedder._async_rate_limit_backoff_sleep = AsyncMock()
    vectors, _ = await embedder.async_get_embeddings_batch_and_usage(["one", "two"], purpose="document")
    assert vectors == [[1.0], [1.0]]
    assert len(calls) == 6
    assert all(call["input_type"] == "search_document" for call in calls)
