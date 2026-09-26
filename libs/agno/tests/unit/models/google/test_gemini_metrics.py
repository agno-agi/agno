import pytest

pytest.importorskip("google.genai")

from google.genai.types import Candidate, GenerateContentResponse, GenerateContentResponseUsageMetadata

from agno.models.google.gemini import Gemini


@pytest.mark.parametrize("streaming", [False, True])
def test_multimodal_usage_preserves_totals_and_additive_details(streaming):
    usage = GenerateContentResponseUsageMetadata(
        prompt_token_count=100,
        candidates_token_count=20,
        thoughts_token_count=7,
        tool_use_prompt_token_count=3,
        total_token_count=130,
        cached_content_token_count=10,
        traffic_type="ON_DEMAND",
        prompt_tokens_details=[
            {"modality": "TEXT", "token_count": 10},
            {"modality": "IMAGE", "token_count": 20},
            {"modality": "AUDIO", "token_count": 30},
            {"modality": "VIDEO", "token_count": 40},
        ],
        candidates_tokens_details=[
            {"modality": "TEXT", "token_count": 5},
            {"modality": "IMAGE", "token_count": 5},
            {"modality": "AUDIO", "token_count": 10},
        ],
        cache_tokens_details=[{"modality": "AUDIO", "token_count": 10}],
        tool_use_prompt_tokens_details=[{"modality": "TEXT", "token_count": 3}],
    )
    model = Gemini()
    response = GenerateContentResponse(candidates=[Candidate(finish_reason="STOP")], usage_metadata=usage)
    parse = model._parse_provider_response_delta if streaming else model._parse_provider_response
    metrics = parse(response).response_usage

    assert metrics is not None
    assert (metrics.input_tokens, metrics.output_tokens, metrics.total_tokens) == (100, 20, 130)
    assert (metrics.reasoning_tokens, metrics.cache_read_tokens) == (7, 10)
    assert (metrics.audio_input_tokens, metrics.audio_output_tokens, metrics.audio_total_tokens) == (30, 10, 40)
    assert metrics.provider_metrics == {
        "traffic_type": "ON_DEMAND",
        "tool_use_prompt_tokens": 3,
        "prompt_text_tokens": 10,
        "prompt_image_tokens": 20,
        "prompt_audio_tokens": 30,
        "prompt_video_tokens": 40,
        "candidates_text_tokens": 5,
        "candidates_image_tokens": 5,
        "candidates_audio_tokens": 10,
        "cache_audio_tokens": 10,
        "tool_use_prompt_text_tokens": 3,
    }
    combined = metrics + metrics
    assert combined.total_tokens == 260
    assert combined.audio_total_tokens == 80
    assert combined.provider_metrics is not None
    for key, value in metrics.provider_metrics.items():
        assert combined.provider_metrics[key] == (value * 2 if isinstance(value, int) else value)


@pytest.mark.parametrize("total", [None, 0])
def test_usage_without_modality_details(total):
    metrics = Gemini()._get_metrics(
        GenerateContentResponseUsageMetadata(prompt_token_count=10, candidates_token_count=2, total_token_count=total)
    )
    assert metrics.total_tokens == (12 if total is None else total)
    assert metrics.audio_total_tokens == 0
    assert metrics.provider_metrics is None


def test_partial_and_unknown_modality_details():
    with pytest.warns(UserWarning, match="FUTURE"):
        usage = GenerateContentResponseUsageMetadata(
            prompt_tokens_details=[
                {"modality": "FUTURE", "token_count": 4},
                {"modality": "AUDIO", "token_count": 2},
                {"modality": "AUDIO", "token_count": 3},
                {"modality": "TEXT", "token_count": 0},
                {"modality": "IMAGE"},
                {"token_count": 5},
            ]
        )
    metrics = Gemini()._get_metrics(usage)
    assert metrics.provider_metrics == {"prompt_future_tokens": 4, "prompt_audio_tokens": 5, "prompt_text_tokens": 0}
    assert metrics.audio_input_tokens == 5
    assert metrics.total_tokens == 0
