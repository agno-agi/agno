from unittest.mock import patch

from agno.models.ollama import OllamaResponses


def test_ollama_responses_default_config():
    """Test OllamaResponses default configuration."""
    model = OllamaResponses()

    assert model.id == "gpt-oss:20b"
    assert model.name == "OllamaResponses"
    assert model.provider == "Ollama"
    assert model.store is False  # Stateless by default


def test_ollama_responses_local_base_url():
    """Test OllamaResponses uses local base URL by default."""
    model = OllamaResponses(id="llama3.1")

    with patch("agno.models.openai.responses.OpenAI") as mock_client:
        model.get_client()

        _, kwargs = mock_client.call_args
        assert kwargs["base_url"] == "http://localhost:11434/v1"
        assert kwargs["api_key"] == "ollama"  # Dummy key for local


def test_ollama_responses_custom_host():
    """Test OllamaResponses with custom host."""
    model = OllamaResponses(id="llama3.1", host="http://192.168.1.100:11434")

    with patch("agno.models.openai.responses.OpenAI") as mock_client:
        model.get_client()

        _, kwargs = mock_client.call_args
        assert kwargs["base_url"] == "http://192.168.1.100:11434/v1"


def test_ollama_responses_custom_host_with_v1():
    """Test OllamaResponses with custom host that already has /v1."""
    model = OllamaResponses(id="llama3.1", host="http://192.168.1.100:11434/v1")

    with patch("agno.models.openai.responses.OpenAI") as mock_client:
        model.get_client()

        _, kwargs = mock_client.call_args
        assert kwargs["base_url"] == "http://192.168.1.100:11434/v1"


def test_ollama_responses_cloud():
    """Test OllamaResponses with Ollama Cloud API key."""
    model = OllamaResponses(id="llama3.1", api_key="test-api-key")

    with patch("agno.models.openai.responses.OpenAI") as mock_client:
        model.get_client()

        _, kwargs = mock_client.call_args
        assert kwargs["base_url"] == "https://ollama.com/v1"
        assert kwargs["api_key"] == "test-api-key"


def test_ollama_responses_not_reasoning_model():
    """Test that OllamaResponses never reports as reasoning model."""
    model = OllamaResponses(id="llama3.1")
    assert model._using_reasoning_model() is False

    # Even with DeepSeek-R1 which has reasoning capabilities
    model = OllamaResponses(id="deepseek-r1")
    assert model._using_reasoning_model() is False
