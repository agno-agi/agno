import pytest

pytest.importorskip("google.genai")

from google.genai.types import Blob, Candidate, Content, GenerateContentResponse, Part

from agno.models.base import MessageData
from agno.models.google.gemini import Gemini


@pytest.mark.parametrize("stream", [False, True])
def test_multiple_pcm_parts_are_not_discarded(stream):
    model = Gemini()
    response = GenerateContentResponse(
        candidates=[
            Candidate(
                content=Content(
                    role="model",
                    parts=[
                        Part(inline_data=Blob(data=b"\x00\x01", mime_type="audio/pcm;rate=24000")),
                        Part(text="Transcript"),
                        Part(inline_data=Blob(data=b"\x02\x03", mime_type="audio/pcm;rate=24000")),
                    ],
                )
            )
        ]
    )

    parsed = model._parse_provider_response_delta(response) if stream else model._parse_provider_response(response)

    assert parsed.audio.content == b"\x00\x01\x02\x03"
    assert parsed.audio.mime_type == "audio/pcm;rate=24000"
    assert parsed.content == "Transcript"
    if stream:
        data = MessageData()
        list(model._populate_stream_data(data, parsed))
        assert data.response_audio.content == b"\x00\x01\x02\x03"
