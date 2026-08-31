import pytest

from agno.models.perplexity import Perplexity


def test_perplexity_does_not_select_a_model_and_warns_about_chat_completions_deprecation():
    with pytest.warns(DeprecationWarning) as warning_records:
        model = Perplexity(api_key="test-key")

    assert model.id == "not-provided"
    assert len(warning_records) == 1
    assert warning_records[0].filename == __file__
