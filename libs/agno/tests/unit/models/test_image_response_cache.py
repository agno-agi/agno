"""Input images must distinguish cached responses without relying on tracking IDs."""

import base64
import json
from pathlib import Path

import httpx
import pytest
from openai import AsyncOpenAI, OpenAI

from agno.media import Image
from agno.media.reference import MediaReference
from agno.models.message import Message
from agno.models.openai.responses import OpenAIResponses


def image_messages(source: str, name: str, tmp_path: Path) -> list[Message]:
    if source == "url":
        image = Image(url=f"https://example.invalid/{name}.png")
    elif source == "content":
        image = Image(content=name.encode(), mime_type="image/png")
    else:
        # Replace the same file between requests, including when restoring A.
        path = tmp_path / "input.png"
        path.write_bytes(name.encode())
        image = Image(filepath=path)
    return [Message(role="user", content="Describe this image.", images=[image])]


def image_transport(calls: list[str]) -> httpx.MockTransport:
    def handle(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        image_url = next(
            part["image_url"]
            for message in payload["input"]
            for part in message.get("content", [])
            if isinstance(part, dict) and part.get("type") == "input_image"
        )
        if image_url.startswith("data:"):
            name = base64.b64decode(image_url.split(",", 1)[1]).decode()
        else:
            name = Path(image_url).stem
        assert name in ("A", "B")
        calls.append(name)
        answer = f"Image {name}"
        response = {
            "id": f"resp_{len(calls)}",
            "object": "response",
            "created_at": 0,
            "status": "completed",
            "error": None,
            "incomplete_details": None,
            "model": "gpt-5.6-luna",
            "output": [
                {
                    "id": "msg_1",
                    "type": "message",
                    "role": "assistant",
                    "status": "completed",
                    "content": [{"type": "output_text", "text": answer, "annotations": []}],
                }
            ],
            "usage": {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
        }
        if not payload.get("stream"):
            return httpx.Response(200, json=response)
        events = [
            {"type": "response.created", "sequence_number": 0, "response": response},
            {
                "type": "response.output_text.delta",
                "sequence_number": 1,
                "item_id": "msg_1",
                "output_index": 0,
                "content_index": 0,
                "delta": answer,
                "logprobs": [],
            },
            {"type": "response.completed", "sequence_number": 2, "response": response},
        ]
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            content="".join(f"data: {json.dumps(event)}\n\n" for event in events),
        )

    return httpx.MockTransport(handle)


@pytest.mark.parametrize("source", ["url", "content", "filepath"])
@pytest.mark.parametrize("stream", [False, True])
def test_image_response_cache(tmp_path, source, stream):
    calls = []
    with httpx.Client(transport=image_transport(calls)) as http:
        model = OpenAIResponses(
            id="gpt-5.6-luna",
            client=OpenAI(api_key="offline", http_client=http),
            cache_response=True,
            cache_dir=str(tmp_path / "cache"),
        )
        answers = []
        for name in ("A", "B", "A"):
            messages = image_messages(source, name, tmp_path)
            if stream:
                answers.append("".join(part.content or "" for part in model.response_stream(messages)))
            else:
                answers.append(model.response(messages).content)

    assert answers == ["Image A", "Image B", "Image A"]
    assert calls == ["A", "B"]
    assert len(list((tmp_path / "cache").glob("*.json"))) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("source", ["url", "content", "filepath"])
@pytest.mark.parametrize("stream", [False, True])
async def test_async_image_response_cache(tmp_path, source, stream):
    calls = []
    async with httpx.AsyncClient(transport=image_transport(calls)) as http:
        model = OpenAIResponses(
            id="gpt-5.6-luna",
            async_client=AsyncOpenAI(api_key="offline", http_client=http),
            cache_response=True,
            cache_dir=str(tmp_path / "cache"),
        )
        answers = []
        for name in ("A", "B", "A"):
            messages = image_messages(source, name, tmp_path)
            if stream:
                answers.append("".join([part.content or "" async for part in model.aresponse_stream(messages)]))
            else:
                answers.append((await model.aresponse(messages)).content)

    assert answers == ["Image A", "Image B", "Image A"]
    assert calls == ["A", "B"]
    assert len(list((tmp_path / "cache").glob("*.json"))) == 2


def image_key(images):
    return OpenAIResponses(id="gpt-5.6-luna")._get_model_cache_key(
        [Message(role="user", content="Describe this image.", images=images)], stream=False
    )


def test_image_cache_key_ignores_tracking_and_output_metadata():
    original = Image(content=b"image", mime_type="image/png")
    annotated = Image(
        content=b"image",
        mime_type="image/png",
        original_prompt="Generate an image",
        revised_prompt="Updated prompt",
        alt_text="A caption",
        metadata={"request_id": "another-run"},
    )
    assert original.id != annotated.id
    assert image_key([original]) == image_key([annotated])


@pytest.mark.parametrize(
    "field,values",
    [("detail", ("low", "high")), ("format", ("png", "jpeg")), ("mime_type", ("image/png", "image/jpeg"))],
)
def test_image_cache_key_includes_input_options(field, values):
    first = Image(content=b"image", **{field: values[0]})
    second = Image(content=b"image", **{field: values[1]})
    assert image_key([first]) != image_key([second])


def test_image_cache_key_preserves_order_and_count():
    first = Image(url="https://example.invalid/A.png")
    second = Image(url="https://example.invalid/B.png")
    keys = [image_key(images) for images in (None, [first], [first, first], [first, second], [second, first])]
    assert len(set(keys)) == len(keys)


def test_image_cache_key_tracks_file_contents_and_accepts_string_paths(tmp_path):
    path = tmp_path / "input.png"
    image = Image(filepath=path)
    missing_key = image_key([image])
    path.write_bytes(b"image")
    assert image_key([image]) != missing_key
    assert image_key([image]) == image_key([Image(filepath=str(path))])


def test_image_cache_key_includes_storage_identity():
    reference = MediaReference(media_id="first-run", storage_key="A.png", storage_backend="s3", bucket="images")
    first = Image(media_reference=reference)
    same = Image(media_reference=reference.model_copy(update={"media_id": "second-run", "session_id": "new-session"}))
    other = Image(media_reference=reference.model_copy(update={"storage_key": "B.png"}))
    assert image_key([first]) == image_key([same])
    assert image_key([first]) != image_key([other])


def test_no_image_cache_key_unchanged():
    # Existing text-only cache files must remain readable after adding image identity.
    assert image_key(None) == image_key([]) == "37e29bffd00b1222fcd91185d727c11c"
