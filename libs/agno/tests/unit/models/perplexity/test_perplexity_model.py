import pytest

from agno.models.perplexity.perplexity import Perplexity


def test_perplexity_requires_explicit_model_and_warns_about_chat_completions_deprecation():
    with pytest.warns(DeprecationWarning) as warning_records:
        model = Perplexity(api_key="test-key")

    assert model.id == "not-provided"
    assert len(warning_records) == 1

    warning_message = str(warning_records[0].message)
    assert "September 27, 2026" in warning_message
    assert "OpenAIResponses" in warning_message
    assert "https://docs.perplexity.ai/docs/agent-api/migrate-from-sonar" in warning_message
    assert warning_records[0].filename == __file__
