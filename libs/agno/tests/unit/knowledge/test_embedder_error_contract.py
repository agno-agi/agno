"""Every embedder must raise on failure rather than return an empty vector.

An empty vector is indistinguishable from a successful embedding downstream, so a
provider error that is swallowed here lets ingestion report success for content the
agent can never retrieve. Each embedder is driven with a client that fails, and with
one that returns a well-formed but empty response.
"""

import asyncio
import importlib
import inspect
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

            # Every public entry point must honour the contract, not just get_embedding.
            # ``Document.embed`` calls get_embedding_and_usage, and enable_batch defaults
            # to False, so that pair is the default ingestion path.
            for method_name in (
                "get_embedding",
                "get_embedding_and_usage",
                "async_get_embedding",
                "async_get_embedding_and_usage",
            ):
                method = getattr(embedder, method_name, None)
                if method is None:
                    continue
                try:
                    result = method("hello world")
                    if inspect.isawaitable(result):
                        result = asyncio.get_event_loop_policy().new_event_loop().run_until_complete(result)
                except EmbeddingError:
                    continue  # the contract
                except NotImplementedError:
                    continue
                except Exception as e:
                    if "not installed" in str(e):
                        continue  # optional async dependency absent in this environment
                    pytest.fail(f"{class_name}.{method_name} raised {type(e).__name__} instead of EmbeddingError: {e}")

                pytest.fail(
                    f"{class_name}.{method_name} returned a value instead of raising. "
                    "An empty or stale vector is reported as a successful embedding downstream."
                )
        finally:
            for owner, attr, original in patched_types:
                if original is _MISSING:
                    delattr(owner, attr)
                else:
                    setattr(owner, attr, original)


class TestEmptyResponseIsNotAnError:
    """A 200 carrying no embedding is a valid provider response, not a failure.

    Ingestion counts unembedded chunks and reports the shortfall, so raising here would
    fail callers that legitimately tolerate an empty result.
    """

    @pytest.mark.parametrize(
        "module_path,class_name",
        [
            ("agno.knowledge.embedder.google", "GeminiEmbedder"),
            ("agno.knowledge.embedder.mistral", "MistralEmbedder"),
            ("agno.knowledge.embedder.cohere", "CohereEmbedder"),
            ("agno.knowledge.embedder.openai", "OpenAIEmbedder"),
            ("agno.knowledge.embedder.azure_openai", "AzureOpenAIEmbedder"),
            ("agno.knowledge.embedder.voyageai", "VoyageAIEmbedder"),
        ],
    )
    def test_empty_response_returns_empty_without_raising(self, module_path, class_name):
        embedder = load(module_path, class_name, {"api_key": "test"})

        empty = MagicMock()
        empty.embeddings = []
        empty.data = []
        empty.usage = None
        empty.meta = None
        for attr in ("response", "_response"):
            if hasattr(embedder, attr):
                setattr(embedder, attr, MagicMock(return_value=empty))

        assert embedder.get_embedding("hello world") == []
        embedder.get_embedding_and_usage("hello world")  # must not raise either


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


class TestEveryBatchingEmbedderKeepsGoodChunks:
    """Every embedder with a batch path must preserve chunks that did embed.

    Guards against a fallback loop being added or reverted in one embedder only.
    """

    BATCHING = [
        "agno.knowledge.embedder.openai",
        "agno.knowledge.embedder.azure_openai",
        "agno.knowledge.embedder.google",
        "agno.knowledge.embedder.cohere",
        "agno.knowledge.embedder.mistral",
        "agno.knowledge.embedder.jina",
        "agno.knowledge.embedder.voyageai",
        "agno.knowledge.embedder.vllm",
    ]

    @pytest.mark.parametrize("module_path", BATCHING, ids=[m.rsplit(".", 1)[-1] for m in BATCHING])
    def test_batch_fallback_uses_the_shared_helper(self, module_path):
        """The per-text fallback must collect failures rather than abort on the first."""
        try:
            module = importlib.import_module(module_path)
        except ImportError as e:
            pytest.skip(f"{module_path} unavailable: {e}")

        source = inspect.getsource(module)
        if "batch_and_usage" not in source:
            pytest.skip(f"{module_path} has no batch path")

        assert "aembed_texts_individually" in source, (
            f"{module_path} falls back per text without the shared helper, so the first "
            "failing chunk would discard every chunk that embedded successfully"
        )


class TestShortBatchKeepsPositions:
    """A batch returning fewer embeddings than texts must not shift later texts.

    Callers pair embeddings with documents by position, so an unpadded short response
    would silently give a document the wrong vector.
    """

    @pytest.mark.parametrize(
        "module_path",
        [
            "agno.knowledge.embedder.openai",
            "agno.knowledge.embedder.azure_openai",
            "agno.knowledge.embedder.google",
            "agno.knowledge.embedder.cohere",
            "agno.knowledge.embedder.mistral",
            "agno.knowledge.embedder.jina",
            "agno.knowledge.embedder.voyageai",
            "agno.knowledge.embedder.vllm",
        ],
        ids=lambda m: m.rsplit(".", 1)[-1],
    )
    def test_batch_extraction_is_padded(self, module_path):
        try:
            module = importlib.import_module(module_path)
        except ImportError as e:
            pytest.skip(f"{module_path} unavailable: {e}")

        source = inspect.getsource(module)
        if "batch_and_usage" not in source:
            pytest.skip(f"{module_path} has no batch path")

        assert "pad_batch_embeddings" in source, (
            f"{module_path} builds batch embeddings without padding, so a short response "
            "would shift every later text onto the wrong vector"
        )

    def test_padding_helper_fills_missing_slots(self):
        from agno.knowledge.embedder.base import pad_batch_embeddings

        padded = pad_batch_embeddings([[0.1], [0.2]], ["a", "b", "c"], "Test")

        assert padded == [[0.1], [0.2], []]

    def test_padding_helper_leaves_complete_batches_alone(self):
        from agno.knowledge.embedder.base import pad_batch_embeddings

        full = [[0.1], [0.2]]

        assert pad_batch_embeddings(full, ["a", "b"], "Test") == full


class TestBedrockEmptyResponse:
    """Bedrock must treat a 200 carrying no embedding the same way Google does."""

    def _embedder(self):
        module = pytest.importorskip("agno.knowledge.embedder.aws_bedrock")
        embedder = module.AwsBedrockEmbedder.__new__(module.AwsBedrockEmbedder)
        embedder.id = "amazon.titan-embed-text-v2:0"
        return embedder

    @pytest.mark.parametrize(
        "body", [{}, {"embeddings": []}, {"embeddings": {}}], ids=["no key", "empty list", "empty dict"]
    )
    def test_empty_response_returns_empty_without_raising(self, body):
        """Raising here would invent an HTTP 502 and a message AWS never sent."""
        assert self._embedder()._extract_embeddings(body) == []

    def test_a_genuine_parse_failure_still_raises(self):
        with pytest.raises(EmbeddingError):
            self._embedder()._extract_embeddings({"embeddings": {"float": None}})

    def test_happy_path_is_unchanged(self):
        assert self._embedder()._extract_embeddings({"embeddings": [[0.1, 0.2]]}) == [0.1, 0.2]
