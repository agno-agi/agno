"""Audio, video and file inputs must not reuse another input's cached response."""

import json
from types import SimpleNamespace

import httpx
import pytest
from openai import AsyncOpenAI

from agno.media import Audio, File, Video
from agno.media.reference import MediaReference
from agno.models.message import Message
from agno.models.openai.chat import OpenAIChat

MEDIA = [("audio", Audio), ("videos", Video), ("files", File)]


def cache_key(field, media, stream=False):
    return OpenAIChat(id="test", api_key="test")._get_model_cache_key(
        [Message(role="user", content="Describe this.", **{field: media})], stream=stream
    )


@pytest.mark.parametrize("field,cls", MEDIA)
@pytest.mark.parametrize("source", ["url", "content", "filepath"])
@pytest.mark.parametrize("stream", [False, True])
def test_different_sources_change_key(field, cls, source, stream, tmp_path):
    def media(value):
        if source == "filepath":
            path = tmp_path / "input"
            path.write_bytes(value.encode())
            return cls(filepath=path)
        return cls(**{source: value.encode() if source == "content" else f"https://example.invalid/{value}"})

    first = cache_key(field, [media("A")], stream)
    assert cache_key(field, [media("B")], stream) != first
    assert cache_key(field, [media("A")], stream) == first


@pytest.mark.parametrize("field,cls", MEDIA)
def test_tracking_ids_and_order(field, cls):
    a, b = cls(content=b"A"), cls(content=b"B")
    assert cache_key(field, [a, b]) != cache_key(field, [b, a])
    assert cache_key(field, [a]) == cache_key(field, [cls(content=b"A", id="other", metadata={"run": 2})])
    assert cache_key(field, [a]) != cache_key(field, [a, a])


@pytest.mark.parametrize("field,cls", MEDIA)
def test_storage_references(field, cls):
    def media(key, tracking):
        return cls(media_reference=MediaReference(media_id=tracking, storage_backend="s3", storage_key=key))

    assert cache_key(field, [media("A", "1")]) != cache_key(field, [media("B", "1")])
    assert cache_key(field, [media("A", "1")]) == cache_key(field, [media("A", "2")])


@pytest.mark.parametrize("field,cls", MEDIA)
def test_unreadable_path_can_become_readable(field, cls, tmp_path):
    path = tmp_path / "missing"
    before = cache_key(field, [cls(filepath=path)])
    path.write_bytes(b"now present")
    assert cache_key(field, [cls(filepath=path)]) != before


@pytest.mark.parametrize(
    "field,cls,option,a,b",
    [
        ("audio", Audio, "format", "wav", "mp3"),
        ("videos", Video, "fps", 1, 2),
        ("files", File, "filename", "a.pdf", "b.pdf"),
        ("files", File, "citations", True, False),
    ],
)
def test_provider_options_change_key(field, cls, option, a, b):
    assert cache_key(field, [cls(content=b"A", **{option: a})]) != cache_key(field, [cls(content=b"A", **{option: b})])


def test_provider_file_ids_and_external_objects():
    assert cache_key("files", [File(id="file-A")]) != cache_key("files", [File(id="file-B")])
    assert cache_key("files", [File(external=SimpleNamespace(name="files/A", uri="gs://A"))]) != cache_key(
        "files", [File(external=SimpleNamespace(name="files/B", uri="gs://B"))]
    )


def test_text_file_content_and_text_only_compatibility():
    assert cache_key("files", [File(content="first", mime_type="text/plain")]) != cache_key(
        "files", [File(content="second", mime_type="text/plain")]
    )
    model = OpenAIChat(id="test", api_key="test")
    plain = [Message(role="user", content="Hello")]
    empty = [Message(role="user", content="Hello", audio=[], videos=[], files=[])]
    assert model._get_model_cache_key(plain, False) == model._get_model_cache_key(empty, False)
    from hashlib import md5

    legacy = {
        "model_id": "test",
        "messages": [{"role": "user", "content": "Hello"}],
        "has_tools": False,
        "response_format": None,
        "stream": False,
    }
    assert model._get_model_cache_key(plain, False) == md5(json.dumps(legacy, sort_keys=True).encode()).hexdigest()


def test_audio_response_cache_makes_distinct_requests(tmp_path):
    calls = []

    def handle(request):
        data = json.loads(request.content)["messages"][0]["content"][1]["input_audio"]["data"]
        calls.append(data)
        return httpx.Response(
            200,
            json={
                "id": "x",
                "object": "chat.completion",
                "created": 0,
                "model": "m",
                "choices": [{"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": data}}],
            },
        )

    model = OpenAIChat(
        id="gpt-4o-audio-preview",
        api_key="test",
        cache_response=True,
        cache_dir=str(tmp_path),
        http_client=httpx.Client(transport=httpx.MockTransport(handle)),
    )
    answers = []
    for clip in (b"first", b"second", b"first"):
        answers.append(
            model.response(
                messages=[Message(role="user", content="Transcribe.", audio=[Audio(content=clip, format="wav")])]
            ).content
        )
    assert len(calls) == 2
    assert answers[0] != answers[1]
    assert answers[0] == answers[2]


@pytest.mark.asyncio
async def test_async_audio_response_cache_makes_distinct_requests(tmp_path):
    calls = []

    def handle(request):
        data = json.loads(request.content)["messages"][0]["content"][1]["input_audio"]["data"]
        calls.append(data)
        return httpx.Response(
            200,
            json={
                "id": "x",
                "object": "chat.completion",
                "created": 0,
                "model": "m",
                "choices": [{"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": data}}],
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        model = OpenAIChat(
            id="gpt-4o-audio-preview",
            api_key="test",
            cache_response=True,
            cache_dir=str(tmp_path),
            async_client=AsyncOpenAI(api_key="test", http_client=client),
        )
        answers = []
        for clip in (b"first", b"second", b"first"):
            response = await model.aresponse(
                messages=[Message(role="user", content="Transcribe.", audio=[Audio(content=clip, format="wav")])]
            )
            answers.append(response.content)
    assert len(calls) == 2
    assert answers[0] != answers[1]
    assert answers[0] == answers[2]


@pytest.mark.parametrize("field,cls", MEDIA)
def test_cache_key_does_not_fetch_urls(field, cls, monkeypatch):
    def unexpected_fetch(*args, **kwargs):
        pytest.fail("Cache key generation must not fetch remote media")

    monkeypatch.setattr(cls, "get_content_bytes", unexpected_fetch)
    assert cache_key(field, [cls(url="https://example.invalid/input")])


@pytest.mark.parametrize("field,cls", MEDIA)
def test_local_file_hash_uses_bounded_reads(field, cls, tmp_path, monkeypatch):
    from hashlib import sha256
    from pathlib import Path

    content = b"abc" * (1024 * 1024)
    path = tmp_path / "large-media"
    path.write_bytes(content)
    original_open = Path.open
    read_sizes = []

    class BoundedReader:
        def __enter__(self):
            self.file = original_open(path, "rb")
            return self

        def __exit__(self, *args):
            self.file.close()

        def read(self, size=-1):
            assert 0 < size <= 1024 * 1024, "media must not be read into memory in one call"
            read_sizes.append(size)
            return self.file.read(size)

    def open_media(self, *args, **kwargs):
        if self == path:
            return BoundedReader()
        return original_open(self, *args, **kwargs)

    monkeypatch.setattr(Path, "open", open_media)
    result = OpenAIChat(id="test", api_key="test")._get_input_media_cache_data(cls(filepath=path))
    assert result["file_content_hash"] == sha256(content).hexdigest()
    assert len(read_sizes) > 1


@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.asyncio
async def test_async_cache_hit_hashes_off_event_loop(stream, tmp_path, monkeypatch):
    import asyncio
    import threading

    from agno.models.base import Model
    from agno.models.response import ModelResponse

    path = tmp_path / "input"
    path.write_bytes(b"audio")
    messages = [Message(role="user", content="Describe.", audio=[Audio(filepath=path)])]
    model = OpenAIChat(id="test", api_key="test", cache_response=True)
    original_key = Model._get_model_cache_key
    loop_thread = threading.get_ident()
    key_threads = []

    def checked_key(self, *args, **kwargs):
        key_threads.append(threading.get_ident())
        assert threading.get_ident() != loop_thread, "cache key hashing blocks the event loop"
        return original_key(self, *args, **kwargs)

    monkeypatch.setattr(Model, "_get_model_cache_key", checked_key)
    monkeypatch.setattr(Model, "_get_cached_model_response", lambda *args: {"streaming_responses": []})
    monkeypatch.setattr(Model, "_model_response_from_cache", lambda *args: ModelResponse(content="cached"))
    monkeypatch.setattr(Model, "_streaming_responses_from_cache", lambda *args: iter([ModelResponse(content="cached")]))
    for _ in range(2):
        if stream:
            responses = [response async for response in model.aresponse_stream(messages)]
            assert responses[0].content == "cached"
        else:
            assert (await model.aresponse(messages)).content == "cached"
        await asyncio.sleep(0)
    assert len(key_threads) == 2


def test_text_and_bytes_content_share_cache_key():
    assert cache_key("files", [File(content="abc")]) == cache_key("files", [File(content=b"abc")])
