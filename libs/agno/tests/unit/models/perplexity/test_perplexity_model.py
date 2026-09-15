import pytest

from agno.models.perplexity import Perplexity

DEFAULT_MODEL_ID = "not-provided"
EXPLICIT_MODEL_ID = "sonar-pro"


@pytest.mark.parametrize("model_id", [None, EXPLICIT_MODEL_ID])
def test_perplexity_warns_about_deprecation_without_changing_model_selection(model_id):
    model_kwargs = {"api_key": "test-key"}
    if model_id is not None:
        model_kwargs["id"] = model_id

    with pytest.warns(
        DeprecationWarning,
        match="Sonar Chat Completions.*OpenAIResponses.*Agent API",
    ) as warning_records:
        model = Perplexity(**model_kwargs)

    assert model.id == (model_id or DEFAULT_MODEL_ID)
    assert len(warning_records) == 1
    assert warning_records[0].filename == __file__
