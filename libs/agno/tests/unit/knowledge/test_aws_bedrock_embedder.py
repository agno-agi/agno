"""Unit tests for AwsBedrockEmbedder — Amazon Titan Embed v2 support.

These are pure-logic tests that do NOT require AWS credentials or network
access.  All tested methods operate only on local state (model id, request
body formatting, response parsing).
"""

import json


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------


def _make_titan(model_id: str = "amazon.titan-embed-text-v2:0", **kwargs):
    """Return an AwsBedrockEmbedder configured for a Titan model."""
    from agno.knowledge.embedder.aws_bedrock import AwsBedrockEmbedder

    return AwsBedrockEmbedder(id=model_id, **kwargs)


def _make_cohere(model_id: str = "cohere.embed-english-v3", **kwargs):
    """Return an AwsBedrockEmbedder configured for a Cohere model."""
    from agno.knowledge.embedder.aws_bedrock import AwsBedrockEmbedder

    return AwsBedrockEmbedder(id=model_id, **kwargs)


# ---------------------------------------------------------------------------
# _is_titan_model()
# ---------------------------------------------------------------------------


class TestIsTitanModel:
    def test_titan_embed_text_v2_returns_true(self):
        embedder = _make_titan("amazon.titan-embed-text-v2:0")
        assert embedder._is_titan_model() is True

    def test_cohere_english_returns_false(self):
        embedder = _make_cohere("cohere.embed-english-v3")
        assert embedder._is_titan_model() is False

    def test_cohere_multilingual_returns_false(self):
        embedder = _make_cohere("cohere.embed-multilingual-v3")
        assert embedder._is_titan_model() is False

    def test_cohere_v4_returns_false(self):
        embedder = _make_cohere("cohere.embed-v4:0")
        assert embedder._is_titan_model() is False


# ---------------------------------------------------------------------------
# Default dimensions after __post_init__
# ---------------------------------------------------------------------------


class TestTitanDimensions:
    def test_titan_default_dimensions_are_1024(self):
        embedder = _make_titan()
        assert embedder.dimensions == 1024

    def test_cohere_v3_dimensions_are_1024(self):
        embedder = _make_cohere("cohere.embed-english-v3")
        assert embedder.dimensions == 1024

    def test_cohere_v4_default_dimensions_are_1536(self):
        embedder = _make_cohere("cohere.embed-v4:0")
        assert embedder.dimensions == 1536


# ---------------------------------------------------------------------------
# _format_request_body()  — Titan path
# ---------------------------------------------------------------------------


class TestFormatRequestBodyTitan:
    def test_titan_uses_inputText_key(self):
        embedder = _make_titan()
        body = json.loads(embedder._format_request_body("hello"))
        assert "inputText" in body
        assert body["inputText"] == "hello"

    def test_titan_does_not_include_texts_key(self):
        embedder = _make_titan()
        body = json.loads(embedder._format_request_body("hello"))
        assert "texts" not in body

    def test_titan_does_not_include_input_type_key(self):
        embedder = _make_titan()
        body = json.loads(embedder._format_request_body("hello"))
        assert "input_type" not in body

    def test_titan_request_params_are_merged(self):
        embedder = _make_titan(request_params={"dimensions": 512, "normalize": True})
        body = json.loads(embedder._format_request_body("hello"))
        assert body["inputText"] == "hello"
        assert body["dimensions"] == 512
        assert body["normalize"] is True


# ---------------------------------------------------------------------------
# _format_request_body()  — Cohere path (regression guard)
# ---------------------------------------------------------------------------


class TestFormatRequestBodyCohere:
    def test_cohere_uses_texts_key(self):
        embedder = _make_cohere("cohere.embed-english-v3")
        body = json.loads(embedder._format_request_body("hello"))
        assert "texts" in body
        assert body["texts"] == ["hello"]

    def test_cohere_includes_input_type(self):
        embedder = _make_cohere("cohere.embed-english-v3")
        body = json.loads(embedder._format_request_body("hello"))
        assert "input_type" in body

    def test_cohere_does_not_include_inputText_key(self):
        embedder = _make_cohere("cohere.embed-english-v3")
        body = json.loads(embedder._format_request_body("hello"))
        assert "inputText" not in body


# ---------------------------------------------------------------------------
# _extract_embeddings()  — Titan response format
# ---------------------------------------------------------------------------


class TestExtractEmbeddingsTitan:
    def test_titan_embedding_key_returns_vector(self):
        embedder = _make_titan()
        result = embedder._extract_embeddings({"embedding": [0.1, 0.2], "inputTextTokenCount": 3})
        assert result == [0.1, 0.2]

    def test_titan_single_element_vector(self):
        embedder = _make_titan()
        result = embedder._extract_embeddings({"embedding": [0.5]})
        assert result == [0.5]

    def test_titan_empty_embedding_returns_empty_list(self):
        embedder = _make_titan()
        result = embedder._extract_embeddings({"embedding": []})
        assert result == []


# ---------------------------------------------------------------------------
# _extract_embeddings()  — Cohere response format (regression guard)
# ---------------------------------------------------------------------------


class TestExtractEmbeddingsCohere:
    def test_cohere_list_format(self):
        embedder = _make_cohere("cohere.embed-english-v3")
        result = embedder._extract_embeddings({"embeddings": [[0.1, 0.2]]})
        assert result == [0.1, 0.2]

    def test_cohere_dict_float_format(self):
        embedder = _make_cohere("cohere.embed-english-v3")
        result = embedder._extract_embeddings({"embeddings": {"float": [[0.3, 0.4]]}})
        assert result == [0.3, 0.4]

    def test_cohere_dict_fallback_to_first_type(self):
        embedder = _make_cohere("cohere.embed-english-v3")
        result = embedder._extract_embeddings({"embeddings": {"int8": [[1, 2, 3]]}})
        assert result == [1, 2, 3]

    def test_no_known_key_returns_empty_list(self):
        embedder = _make_cohere("cohere.embed-english-v3")
        result = embedder._extract_embeddings({"unexpected_key": "value"})
        assert result == []
