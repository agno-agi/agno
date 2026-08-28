"""Every embedder must raise on failure rather than return an empty vector.

An empty vector is indistinguishable from a successful embedding downstream, so a
provider error that is swallowed here lets ingestion report success for content the
agent can never retrieve. Each embedder is driven with a client that fails, and with
one that returns a well-formed but empty response.
"""

import importlib
from unittest.mock import MagicMock

import pytest

from agno.exceptions import EmbeddingError

_MISSING = object()

# (import path, class name, kwargs needed to construct without touching the network)
EMBEDDERS = [
    ("agno.knowledge.embedder.openai", "OpenAIEmbedder", {"api_key": "test"}),
    ("agno.knowledge.embedder.azure_openai", "AzureOpenAIEmbedder", {"api_key": "test"}),
    ("agno.knowledge.embedder.cohere", "CohereEmbedder", {"api_key": "test"}),
    ("agno.knowledge.embedder.mistral", "MistralEmbedder", {"api_key": "test"}),
    ("agno.knowledge.embedder.jina", "JinaEmbedder", {"api_key": "test"}),
    ("agno.knowledge.embedder.voyageai", "VoyageAIEmbedder", {"api_key": "test"}),
    ("agno.knowledge.embedder.google", "GeminiEmbedder", {"api_key": "test"}),
    ("agno.knowledge.embedder.ollama", "OllamaEmbedder", {}),
    ("agno.knowledge.embedder.vllm", "VLLMEmbedder", {"api_key": "test"}),
    ("agno.knowledge.embedder.huggingface", "HuggingfaceCustomEmbedder", {"api_key": "test"}),
    ("agno.knowledge.embedder.aws_bedrock", "AwsBedrockEmbedder", {}),
    ("agno.knowledge.embedder.fastembed", "FastEmbedEmbedder", {}),
    ("agno.knowledge.embedder.sentence_transformer", "SentenceTransformerEmbedder", {}),
]


def load(module_path: str, class_name: str, kwargs: dict):
    """Build the embedder, skipping when its optional dependency is absent."""
    try:
        module = importlib.import_module(module_path)
    except ImportError as e:
        pytest.skip(f"{module_path} unavailable: {e}")

    cls = getattr(module, class_name, None)
    if cls is None:
        pytest.skip(f"{class_name} not exported by {module_path}")
    try:
        return cls(**kwargs)
    except Exception as e:  # missing optional dependency or required credential
        pytest.skip(f"cannot construct {class_name}: {e}")


@pytest.mark.parametrize("module_path,class_name,kwargs", EMBEDDERS, ids=[e[1] for e in EMBEDDERS])
class TestEmbedderRaisesOnFailure:
    def test_provider_error_raises_embedding_error(self, module_path, class_name, kwargs):
        """A provider exception must surface as EmbeddingError, not an empty vector."""
        embedder = load(module_path, class_name, kwargs)
        boom = RuntimeError("provider is down")

        def failing_client():
            client = MagicMock()
            for method in ("embed", "encode", "feature_extraction", "invoke_model"):
                setattr(client, method, MagicMock(side_effect=boom))
            client.embeddings.create = MagicMock(side_effect=boom)
            return client

        # Fail at the boundary each embedder uses to reach its model or API. Class-level
        # patches are undone in the finally block so no state leaks into other tests.
        patched_types: list[tuple[type, str, object]] = []
        patched = False
        for attr in ("response", "_response", "_create_embedding_local"):
            if hasattr(embedder, attr):
                setattr(embedder, attr, MagicMock(side_effect=boom))
                patched = True
        for attr in ("client", "aclient", "sentence_transformer_client"):
            if not (hasattr(type(embedder), attr) or hasattr(embedder, attr)):
                continue
            try:
                setattr(embedder, attr, failing_client())
                patched = True
            except AttributeError:
                # A read-only property: shadow it on the type, then restore it
                original = type(embedder).__dict__.get(attr, _MISSING)
                patched_types.append((type(embedder), attr, original))
                setattr(type(embedder), attr, property(lambda self, _c=failing_client(): _c))
                patched = True

        try:
            if not patched:
                pytest.skip(f"no known provider boundary to fail on {class_name}")

            try:
                result = embedder.get_embedding("hello world")
            except EmbeddingError:
                return  # the contract
            except NotImplementedError:
                pytest.skip(f"{class_name} does not implement get_embedding")
            except Exception as e:
                pytest.fail(f"{class_name} raised {type(e).__name__} instead of EmbeddingError: {e}")

            pytest.fail(
                f"{class_name}.get_embedding returned a value instead of raising "
                f"(len={len(result) if hasattr(result, '__len__') else 'n/a'}). "
                "An empty or stale vector is reported as a successful embedding downstream."
            )
        finally:
            for owner, attr, original in patched_types:
                if original is _MISSING:
                    delattr(owner, attr)
                else:
                    setattr(owner, attr, original)


class TestBatchFallbackKeepsGoodChunks:
    """One bad text must not discard the chunks that embedded successfully."""

    def _embedder(self, bad_marker="OVERSIZED"):
        from agno.knowledge.embedder.openai import OpenAIEmbedder

        embedder = OpenAIEmbedder(id="text-embedding-3-small", api_key="test", enable_batch=True, batch_size=10)

        async def one_at_a_time(text):
            if bad_marker in text:
                raise EmbeddingError("maximum context length is 8191 tokens", 400, provider="OpenAI")
            return [0.1, 0.2], {"total_tokens": 1}

        embedder.async_get_embedding_and_usage = one_at_a_time

        class FailingClient:
            class embeddings:
                @staticmethod
                async def create(**kwargs):
                    raise RuntimeError("maximum context length is 8191 tokens")

        embedder.async_client = FailingClient()
        return embedder

    @pytest.mark.asyncio
    async def test_one_oversized_chunk_does_not_discard_the_batch(self):
        embedder = self._embedder()
        texts = ["fine one", "fine two", "OVERSIZED", "fine three"]

        embeddings, _ = await embedder.async_get_embeddings_batch_and_usage(texts)

        assert len(embeddings) == len(texts), "every text keeps its position"
        assert sum(1 for e in embeddings if e) == 3
        assert embeddings[2] == [], "the failed chunk is the empty one"

    @pytest.mark.asyncio
    async def test_every_chunk_failing_still_raises(self):
        """With nothing to preserve there is no partial result worth returning."""
        embedder = self._embedder(bad_marker="")  # matches every text

        with pytest.raises(EmbeddingError) as excinfo:
            await embedder.async_get_embeddings_batch_and_usage(["a", "b"])

        assert "All 2 chunks failed" in str(excinfo.value)


class TestEmptyResponseIsReported:
    """A well-formed response carrying no embedding must still raise.

    This pins the outcome, not the control flow: ``raise_embedding_error`` re-raises an
    ``EmbeddingError`` unchanged, so the message survives even when the check sits inside
    the provider-error handler. Keeping the check outside that handler is a structural
    choice this test cannot observe.
    """

    @pytest.mark.parametrize(
        "module_path,class_name",
        [
            ("agno.knowledge.embedder.google", "GeminiEmbedder"),
            ("agno.knowledge.embedder.mistral", "MistralEmbedder"),
            ("agno.knowledge.embedder.cohere", "CohereEmbedder"),
        ],
    )
    def test_empty_response_reports_the_shape_problem(self, module_path, class_name):
        embedder = load(module_path, class_name, {"api_key": "test"})

        empty = MagicMock()
        empty.embeddings = []
        empty.data = []
        for attr in ("response", "_response"):
            if hasattr(embedder, attr):
                setattr(embedder, attr, MagicMock(return_value=empty))

        with pytest.raises(EmbeddingError) as excinfo:
            embedder.get_embedding("hello world")

        assert "No embeddings found in response" in str(excinfo.value)
