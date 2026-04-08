"""Tests for send_dimensions auto-detection and override logic across all embedder subclasses."""

from unittest.mock import MagicMock

import pytest


# OpenAIEmbedder auto-detection 

def test_openai_embedder_text_embedding_3_small_sends_dimensions():
    """text-embedding-3-small (default) should auto-detect send_dimensions=True."""
    from agno.knowledge.embedder.openai import OpenAIEmbedder

    embedder = OpenAIEmbedder()
    assert embedder.send_dimensions is True


def test_openai_embedder_text_embedding_3_large_sends_dimensions():
    """text-embedding-3-large should auto-detect send_dimensions=True."""
    from agno.knowledge.embedder.openai import OpenAIEmbedder

    embedder = OpenAIEmbedder(id="text-embedding-3-large")
    assert embedder.send_dimensions is True
    assert embedder.dimensions == 3072


def test_openai_embedder_with_base_url_sends_dimensions():
    """Custom base_url should auto-detect send_dimensions=True (backward compat)."""
    from agno.knowledge.embedder.openai import OpenAIEmbedder

    embedder = OpenAIEmbedder(
        id="some-custom-model",
        base_url="http://localhost:8000/v1",
        dimensions=768,
    )
    assert embedder.send_dimensions is True


def test_openai_embedder_no_base_url_non_embedding3_does_not_send():
    """Non text-embedding-3 model without base_url should not send dimensions."""
    from agno.knowledge.embedder.openai import OpenAIEmbedder

    embedder = OpenAIEmbedder(id="text-embedding-ada-002")
    assert embedder.send_dimensions is False


# Explicit override


def test_openai_embedder_explicit_true_overrides_auto_detection():
    """Explicit send_dimensions=True should override auto-detection."""
    from agno.knowledge.embedder.openai import OpenAIEmbedder

    embedder = OpenAIEmbedder(
        id="text-embedding-ada-002",
        send_dimensions=True,
    )
    assert embedder.send_dimensions is True


def test_openai_embedder_explicit_false_overrides_auto_detection():
    """Explicit send_dimensions=False should override auto-detection even for text-embedding-3."""
    from agno.knowledge.embedder.openai import OpenAIEmbedder

    embedder = OpenAIEmbedder(
        id="text-embedding-3-small",
        send_dimensions=False,
    )
    assert embedder.send_dimensions is False


# TogetherEmbedder (the bug fix)


def test_together_embedder_does_not_send_dimensions():
    """TogetherEmbedder must NOT send dimensions — Together AI rejects it (HTTP 400)."""
    from agno.knowledge.embedder.together import TogetherEmbedder

    embedder = TogetherEmbedder()
    # send_dimensions should be False despite base_url being set
    assert embedder.send_dimensions is False
    assert embedder.base_url == "https://api.together.xyz/v1"
    # dimensions should still be set (PgVector needs it for column size)
    assert embedder.dimensions == 768


def test_together_embedder_dimensions_not_in_request():
    """Verify that dimensions is NOT included in the actual API request params."""
    from agno.knowledge.embedder.together import TogetherEmbedder

    mock_response = MagicMock()
    mock_response.data = [MagicMock(embedding=[0.1, 0.2, 0.3])]
    mock_response.usage = None

    mock_client = MagicMock()
    mock_client.embeddings.create.return_value = mock_response

    embedder = TogetherEmbedder(openai_client=mock_client)
    embedder.get_embedding("test text")

    call_kwargs = mock_client.embeddings.create.call_args[1]
    assert "dimensions" not in call_kwargs


# OpenAILikeEmbedder


def test_openai_like_embedder_does_not_send_dimensions():
    """OpenAILikeEmbedder should default send_dimensions=False."""
    from agno.knowledge.embedder.openai_like import OpenAILikeEmbedder

    embedder = OpenAILikeEmbedder()
    assert embedder.send_dimensions is False


def test_openai_like_embedder_with_base_url_still_does_not_send():
    """Even with base_url set, OpenAILikeEmbedder should not send dimensions."""
    from agno.knowledge.embedder.openai_like import OpenAILikeEmbedder

    embedder = OpenAILikeEmbedder(
        id="my-model",
        base_url="http://localhost:11434/v1",
        dimensions=768,
    )
    assert embedder.send_dimensions is False


def test_openai_like_embedder_explicit_true_override():
    """User can override send_dimensions=True if their provider supports it."""
    from agno.knowledge.embedder.openai_like import OpenAILikeEmbedder

    embedder = OpenAILikeEmbedder(
        id="my-model",
        base_url="http://localhost:8000/v1",
        dimensions=768,
        send_dimensions=True,
    )
    assert embedder.send_dimensions is True


def test_openai_like_embedder_dimensions_not_in_request():
    """Verify that dimensions is NOT included in the actual API request params."""
    from agno.knowledge.embedder.openai_like import OpenAILikeEmbedder

    mock_response = MagicMock()
    mock_response.data = [MagicMock(embedding=[0.1, 0.2, 0.3])]
    mock_response.usage = None

    mock_client = MagicMock()
    mock_client.embeddings.create.return_value = mock_response

    embedder = OpenAILikeEmbedder(
        id="my-model",
        api_key="test-key",
        base_url="http://localhost:8000/v1",
        dimensions=3,
        openai_client=mock_client,
    )
    embedder.get_embedding("test text")

    call_kwargs = mock_client.embeddings.create.call_args[1]
    assert "dimensions" not in call_kwargs


# FireworksEmbedder / NebiusEmbedder (backward compat)


def test_fireworks_embedder_sends_dimensions():
    """FireworksEmbedder has base_url set — should auto-detect send_dimensions=True."""
    from agno.knowledge.embedder.fireworks import FireworksEmbedder

    embedder = FireworksEmbedder()
    assert embedder.send_dimensions is True
    assert embedder.base_url is not None


def test_nebius_embedder_sends_dimensions():
    """NebiusEmbedder has base_url set — should auto-detect send_dimensions=True."""
    from agno.knowledge.embedder.nebius import NebiusEmbedder

    embedder = NebiusEmbedder()
    assert embedder.send_dimensions is True
    assert embedder.base_url is not None


# LangDBEmbedder (super().__post_init__() fix)


def test_langdb_embedder_sends_dimensions():
    """LangDBEmbedder should send dimensions — it calls super().__post_init__() for auto-detection."""
    import os
    from unittest.mock import patch

    with patch.dict(os.environ, {"LANGDB_PROJECT_ID": "test-project-id"}):
        from agno.knowledge.embedder.langdb import LangDBEmbedder

        embedder = LangDBEmbedder()
        assert embedder.send_dimensions is True
        assert "test-project-id" in embedder.base_url


# Request params integration


def test_openai_embedder_dimensions_included_in_request_when_true():
    """When send_dimensions=True, dimensions MUST appear in the API request."""
    from agno.knowledge.embedder.openai import OpenAIEmbedder

    mock_response = MagicMock()
    mock_response.data = [MagicMock(embedding=[0.1, 0.2, 0.3])]
    mock_response.usage = None

    mock_client = MagicMock()
    mock_client.embeddings.create.return_value = mock_response

    embedder = OpenAIEmbedder(
        id="text-embedding-3-small",
        dimensions=1536,
        openai_client=mock_client,
    )
    embedder.get_embedding("test text")

    call_kwargs = mock_client.embeddings.create.call_args[1]
    assert call_kwargs["dimensions"] == 1536


def test_openai_embedder_dimensions_excluded_from_request_when_false():
    """When send_dimensions=False, dimensions must NOT appear in the API request."""
    from agno.knowledge.embedder.openai import OpenAIEmbedder

    mock_response = MagicMock()
    mock_response.data = [MagicMock(embedding=[0.1, 0.2, 0.3])]
    mock_response.usage = None

    mock_client = MagicMock()
    mock_client.embeddings.create.return_value = mock_response

    embedder = OpenAIEmbedder(
        id="text-embedding-3-small",
        dimensions=1536,
        send_dimensions=False,
        openai_client=mock_client,
    )
    embedder.get_embedding("test text")

    call_kwargs = mock_client.embeddings.create.call_args[1]
    assert "dimensions" not in call_kwargs
