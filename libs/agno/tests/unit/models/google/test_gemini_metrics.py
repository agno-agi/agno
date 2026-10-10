from google.genai.types import GenerateContentResponseUsageMetadata

from agno.models.google import Gemini


def test_get_metrics_counts_thoughts_as_output_tokens():
    usage = GenerateContentResponseUsageMetadata(
        prompt_token_count=1000,
        candidates_token_count=50,
        thoughts_token_count=800,
        total_token_count=1850,
    )

    metrics = Gemini(id="gemini-2.5-flash", api_key="test")._get_metrics(usage)

    assert metrics.input_tokens == 1000
    assert metrics.output_tokens == 850
    assert metrics.reasoning_tokens == 800
    assert metrics.total_tokens == usage.total_token_count


def test_get_metrics_without_thoughts_keeps_candidate_tokens():
    usage = GenerateContentResponseUsageMetadata(
        prompt_token_count=1000,
        candidates_token_count=50,
        total_token_count=1050,
    )

    metrics = Gemini(id="gemini-2.5-flash", api_key="test")._get_metrics(usage)

    assert metrics.output_tokens == 50
    assert metrics.reasoning_tokens == 0
    assert metrics.total_tokens == usage.total_token_count
