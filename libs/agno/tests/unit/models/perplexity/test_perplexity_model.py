import pytest

from agno.models.perplexity import Perplexity

DEFAULT_MODEL_ID = "not-provided"
EXPLICIT_MODEL_ID = "sonar-pro"
MIGRATION_GUIDE_URL = "https://docs.perplexity.ai/docs/getting-started/integrations/agno"


def test_perplexity_does_not_select_a_default_model():
    with pytest.warns(DeprecationWarning):
        model = Perplexity(api_key="test-key")

    assert model.id == DEFAULT_MODEL_ID


def test_perplexity_warns_about_chat_completions_deprecation_with_explicit_model():
    with pytest.warns(DeprecationWarning) as warning_records:
        model = Perplexity(id=EXPLICIT_MODEL_ID, api_key="test-key")

    assert model.id == EXPLICIT_MODEL_ID
    assert len(warning_records) == 1
    warning_message = str(warning_records[0].message)
    assert "Sonar Chat Completions" in warning_message
    assert "September 27, 2026" in warning_message
    assert "OpenAIResponses" in warning_message
    assert MIGRATION_GUIDE_URL in warning_message
    assert warning_records[0].filename == __file__
