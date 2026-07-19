"""
Integration tests for AWS Bedrock Embedder.

These tests require valid AWS credentials with access to Bedrock.
Credentials can be provided via:
- Environment variables (AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY)
- AWS credentials file (~/.aws/credentials)
- AWS SSO session
- IAM role (when running on AWS infrastructure)

To run these tests:
    pytest libs/agno/tests/integration/embedder/test_aws_bedrock_embedder.py -v
"""

import os

import pytest

from agno.knowledge.embedder.aws_bedrock import AwsBedrockEmbedder


def _has_aws_credentials() -> bool:
    """Check if AWS credentials are available via any method."""
    try:
        import boto3

        session = boto3.Session()
        credentials = session.get_credentials()
        return credentials is not None
    except Exception:
        return False


# Skip all tests if AWS credentials are not configured
pytestmark = pytest.mark.skipif(
    not _has_aws_credentials(),
    reason="AWS credentials not configured",
)


class TestAwsBedrockEmbedderV3:
    """Tests for Cohere Embed v3 models on Bedrock."""

    @pytest.fixture
    def embedder(self):
        return AwsBedrockEmbedder(
            id="cohere.embed-multilingual-v3",
            aws_region=os.getenv("AWS_REGION", "us-west-2"),
        )

    def test_embedder_initialization(self, embedder):
        """Test that the embedder initializes correctly."""
        assert embedder is not None
        assert embedder.id == "cohere.embed-multilingual-v3"
        assert embedder.dimensions == 1024
        assert embedder.input_type == "search_query"

    def test_get_embedding(self, embedder):
        """Test that we can get embeddings for a simple text."""
        text = "The quick brown fox jumps over the lazy dog."
        embeddings = embedder.get_embedding(text)

        assert isinstance(embeddings, list)
        assert len(embeddings) > 0
        assert all(isinstance(x, float) for x in embeddings)
        assert len(embeddings) == embedder.dimensions

    def test_get_embedding_and_usage(self, embedder):
        """Test that we can get embeddings with usage information."""
        text = "Test embedding with usage information."
        embedding, usage = embedder.get_embedding_and_usage(text)

        assert isinstance(embedding, list)
        assert len(embedding) > 0
        assert all(isinstance(x, float) for x in embedding)
        assert len(embedding) == embedder.dimensions

    def test_special_characters(self, embedder):
        """Test that special characters are handled correctly."""
        text = "Hello, world! 123 @#$%"
        embeddings = embedder.get_embedding(text)
        assert isinstance(embeddings, list)
        assert len(embeddings) > 0
        assert len(embeddings) == embedder.dimensions

    def test_embedding_consistency(self, embedder):
        """Test that embeddings for the same text are consistent."""
        text = "Consistency test"
        embeddings1 = embedder.get_embedding(text)
        embeddings2 = embedder.get_embedding(text)

        assert len(embeddings1) == len(embeddings2)
        # Allow small floating point differences
        assert all(abs(a - b) < 1e-3 for a, b in zip(embeddings1, embeddings2))

    def test_input_type_search_document(self):
        """Test embedder with search_document input type."""
        embedder = AwsBedrockEmbedder(
            id="cohere.embed-multilingual-v3",
            input_type="search_document",
            aws_region=os.getenv("AWS_REGION", "us-west-2"),
        )

        text = "This is a document to be indexed for search."
        embeddings = embedder.get_embedding(text)

        assert isinstance(embeddings, list)
        assert len(embeddings) == 1024

    def test_truncate_option(self):
        """Test embedder with truncate option."""
        embedder = AwsBedrockEmbedder(
            id="cohere.embed-multilingual-v3",
            truncate="END",
            aws_region=os.getenv("AWS_REGION", "us-west-2"),
        )

        # Create a moderately long text (within API limits but tests truncate param is accepted)
        long_text = " ".join(["word"] * 200)
        embeddings = embedder.get_embedding(long_text)

        assert isinstance(embeddings, list)
        assert len(embeddings) == 1024


class TestAwsBedrockEmbedderV4:
    """Tests for Cohere Embed v4 model on Bedrock."""

    @pytest.fixture
    def embedder(self):
        return AwsBedrockEmbedder(
            id="us.cohere.embed-v4:0",
            aws_region=os.getenv("AWS_REGION", "us-west-2"),
        )

    def test_embedder_initialization(self, embedder):
        """Test that the v4 embedder initializes correctly."""
        assert embedder is not None
        assert embedder.id == "us.cohere.embed-v4:0"
        assert embedder.dimensions == 1536  # v4 default
        assert embedder._is_v4_model()

    def test_get_embedding(self, embedder):
        """Test that we can get embeddings for a simple text."""
        text = "The quick brown fox jumps over the lazy dog."
        embeddings = embedder.get_embedding(text)

        assert isinstance(embeddings, list)
        assert len(embeddings) > 0
        assert all(isinstance(x, float) for x in embeddings)
        assert len(embeddings) == embedder.dimensions

    def test_custom_output_dimension(self):
        """Test v4 embedder with custom output dimension."""
        embedder = AwsBedrockEmbedder(
            id="us.cohere.embed-v4:0",
            output_dimension=1024,
            aws_region=os.getenv("AWS_REGION", "us-west-2"),
        )

        assert embedder.dimensions == 1024

        text = "Test with custom dimension"
        embeddings = embedder.get_embedding(text)

        assert isinstance(embeddings, list)
        assert len(embeddings) == 1024

    def test_all_output_dimensions(self):
        """Test all supported output dimensions for v4."""
        dimensions_to_test = [256, 512, 1024, 1536]
        text = "Test dimensions"

        for dim in dimensions_to_test:
            embedder = AwsBedrockEmbedder(
                id="us.cohere.embed-v4:0",
                output_dimension=dim,
                aws_region=os.getenv("AWS_REGION", "us-west-2"),
            )

            embeddings = embedder.get_embedding(text)
            assert len(embeddings) == dim, f"Expected {dim} dimensions, got {len(embeddings)}"

    def test_v4_truncate_options(self):
        """Test v4 truncate options (LEFT/RIGHT)."""
        embedder = AwsBedrockEmbedder(
            id="us.cohere.embed-v4:0",
            truncate="RIGHT",
            aws_region=os.getenv("AWS_REGION", "us-west-2"),
        )

        long_text = " ".join(["word"] * 1000)
        embeddings = embedder.get_embedding(long_text)

        assert isinstance(embeddings, list)
        assert len(embeddings) == 1536


class TestAwsBedrockEmbedderV4Multimodal:
    """Tests for Cohere Embed v4 multimodal features."""

    @pytest.fixture
    def embedder(self):
        return AwsBedrockEmbedder(
            id="us.cohere.embed-v4:0",
            output_dimension=1024,
            aws_region=os.getenv("AWS_REGION", "us-west-2"),
        )

    def test_image_embedding_requires_v4(self):
        """Test that image embedding raises error for v3 models."""
        v3_embedder = AwsBedrockEmbedder(
            id="cohere.embed-multilingual-v3",
            aws_region=os.getenv("AWS_REGION", "us-west-2"),
        )

        with pytest.raises(Exception) as exc_info:
            v3_embedder.get_image_embedding("data:image/png;base64,...")

        assert "v4" in str(exc_info.value).lower() or "supported" in str(exc_info.value).lower()

    def test_multimodal_embedding_requires_v4(self):
        """Test that multimodal embedding raises error for v3 models."""
        v3_embedder = AwsBedrockEmbedder(
            id="cohere.embed-multilingual-v3",
            aws_region=os.getenv("AWS_REGION", "us-west-2"),
        )

        with pytest.raises(Exception) as exc_info:
            v3_embedder.get_multimodal_embedding([{"type": "text", "text": "test"}])

        assert "v4" in str(exc_info.value).lower() or "supported" in str(exc_info.value).lower()


class TestAwsBedrockEmbedderAsync:
    """Tests for async methods of AWS Bedrock Embedder."""

    @pytest.fixture
    def embedder(self):
        return AwsBedrockEmbedder(
            id="cohere.embed-multilingual-v3",
            aws_region=os.getenv("AWS_REGION", "us-west-2"),
        )

    @pytest.mark.asyncio
    async def test_async_get_embedding(self, embedder):
        """Test async embedding retrieval."""
        text = "Async embedding test"
        embeddings = await embedder.async_get_embedding(text)

        assert isinstance(embeddings, list)
        assert len(embeddings) > 0
        assert len(embeddings) == embedder.dimensions

    @pytest.mark.asyncio
    async def test_async_get_embedding_and_usage(self, embedder):
        """Test async embedding with usage retrieval."""
        text = "Async embedding with usage test"
        embedding, usage = await embedder.async_get_embedding_and_usage(text)

        assert isinstance(embedding, list)
        assert len(embedding) > 0
        assert len(embedding) == embedder.dimensions


class TestAwsBedrockEmbedderConfiguration:
    """Tests for AWS Bedrock Embedder configuration options."""

    def test_english_model(self):
        """Test with English-only model."""
        embedder = AwsBedrockEmbedder(
            id="cohere.embed-english-v3",
            aws_region=os.getenv("AWS_REGION", "us-west-2"),
        )

        text = "English text for embedding"
        embeddings = embedder.get_embedding(text)

        assert isinstance(embeddings, list)
        assert len(embeddings) == 1024

    def test_batch_disabled_warning(self, caplog):
        """Test that batch mode is properly disabled."""
        embedder = AwsBedrockEmbedder(
            id="cohere.embed-multilingual-v3",
            enable_batch=True,
            aws_region=os.getenv("AWS_REGION", "us-west-2"),
        )

        assert embedder.enable_batch is False

    def test_embedding_types_parameter(self):
        """Test with explicit embedding types parameter."""
        embedder = AwsBedrockEmbedder(
            id="cohere.embed-multilingual-v3",
            embedding_types=["float"],
            aws_region=os.getenv("AWS_REGION", "us-west-2"),
        )

        text = "Test with embedding types"
        embeddings = embedder.get_embedding(text)

        assert isinstance(embeddings, list)
        assert len(embeddings) == 1024
