import json

import pytest

from agno.media import Audio, File, Image, Video
from agno.media.reference import MediaReference
from agno.models.openai.chat import OpenAIChat
from agno.models.response import ModelResponse

INLINE_MEDIA_CASES = [
    pytest.param("images", Image, "image/png", {"detail": "high", "alt_text": "A chart"}, id="image"),
    pytest.param("audio", Audio, "audio/wav", {"transcript": "Hello", "sample_rate": 16000}, id="response-audio"),
    pytest.param("audios", Audio, "audio/wav", {"duration": 1.5, "channels": 2}, id="audio-list"),
    pytest.param("videos", Video, "video/mp4", {"width": 320, "height": 240, "fps": 24}, id="video"),
]
MEDIA_CASES = [
    *INLINE_MEDIA_CASES,
    pytest.param("files", File, "application/pdf", {"filename": "report.pdf", "size": 9, "name": "Report"}, id="file"),
]
BINARY_CONTENT = b"\x00\xff\x89\x80media"


def response_with_media(field, media):
    return ModelResponse(**{field: media if field == "audio" else [media]})


def response_media(response, field):
    media = getattr(response, field)
    return media if field == "audio" else media[0]


@pytest.mark.parametrize("field,media_type,mime_type,extra", INLINE_MEDIA_CASES)
@pytest.mark.parametrize("media_id", ["media-1", ""])
def test_binary_media_survives_model_response_json_roundtrip(field, media_type, mime_type, extra, media_id):
    original = media_type(
        content=BINARY_CONTENT, id=media_id, mime_type=mime_type, metadata={"source": {"tool": "generate"}}, **extra
    )
    payload = json.loads(json.dumps(response_with_media(field, original).to_dict()))

    restored = response_media(ModelResponse.from_dict(payload), field)

    assert isinstance(restored, media_type)
    assert restored.get_content_bytes() == BINARY_CONTENT
    assert restored.to_dict() == original.to_dict()


@pytest.mark.parametrize("field,media_type,mime_type,extra", INLINE_MEDIA_CASES)
@pytest.mark.parametrize("content", ["not base64", "caf\u00e9"])
def test_model_response_keeps_non_base64_media_strings(field, media_type, mime_type, extra, content):
    media = {"id": "media-1", "content": content, "mime_type": mime_type, **extra}
    payload = {field: media if field == "audio" else [media]}

    restored = response_media(ModelResponse.from_dict(payload), field)

    assert isinstance(restored, media_type)
    assert restored.content == content.encode("utf-8")


@pytest.mark.parametrize("field,media_type,mime_type,extra", MEDIA_CASES)
@pytest.mark.parametrize("source", ["url", "filepath", "media_reference"])
def test_model_response_media_preserves_non_inline_sources(field, media_type, mime_type, extra, source):
    sources = {
        "url": "https://example.com/media",
        "filepath": "cached-media.bin",
        "media_reference": MediaReference(
            media_id="media-1", storage_key="media/key", storage_backend="local", metadata={"owner": "session-1"}
        ),
    }
    original = media_type(
        **{source: sources[source]}, id="media-1", mime_type=mime_type, metadata={"origin": "test"}, **extra
    )
    payload = json.loads(json.dumps(response_with_media(field, original).to_dict()))

    restored = response_media(ModelResponse.from_dict(payload), field)

    assert restored.content is None
    assert restored.to_dict() == original.to_dict()


@pytest.mark.parametrize(
    "mime_type,text",
    [
        ("text/plain", "TestData"),
        ("text/plain", "caf\u00e9\n"),
        ("application/json", '"test"'),
        ("application/json", "1234"),
        ("text/plain", ""),
    ],
)
def test_model_response_keeps_file_string_content(mime_type, text):
    original = File(id="file-1", content=text, mime_type=mime_type, metadata={"language": "en"})
    payload = json.loads(json.dumps(ModelResponse(files=[original]).to_dict()))

    restored = ModelResponse.from_dict(payload).files[0]

    assert restored.content == text
    assert restored.to_dict() == original.to_dict()


@pytest.mark.parametrize("streaming", [False, True])
def test_model_cache_restores_media_bytes_and_metadata(tmp_path, streaming):
    model = OpenAIChat(cache_response=True, cache_dir=str(tmp_path))
    response = ModelResponse(
        content="Generated media",
        images=[Image(content=BINARY_CONTENT, metadata={"kind": "image"})],
        audio=Audio(content=BINARY_CONTENT, transcript="Hello"),
        audios=[Audio(content=BINARY_CONTENT, sample_rate=16000)],
        videos=[Video(content=BINARY_CONTENT, width=320)],
        files=[File(content='"test"', mime_type="application/json", filename="report.json")],
    )
    if streaming:
        model._save_streaming_responses_to_cache("media", [response])
    else:
        model._save_model_response_to_cache("media", response)

    cached = model._get_cached_model_response("media")
    assert cached is not None
    if streaming:
        restored = list(model._streaming_responses_from_cache(cached["streaming_responses"]))[0]
    else:
        restored = model._model_response_from_cache(cached)

    for field in ("images", "audio", "audios", "videos"):
        assert response_media(restored, field).get_content_bytes() == BINARY_CONTENT
    assert restored.to_dict() == response.to_dict()
