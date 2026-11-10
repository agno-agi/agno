"""Attachments reach the installed Claude and Codex SDK request types, with no network and no model call.

The runtime hands decoded ``images``/``files`` to the real adapter. These tests run the adapter's own
staging and request construction and stop at the SDK transport, which is replaced by a recorder.
"""

import re
from pathlib import Path
from typing import Any, List

import pytest

from agno.exceptions import UnsupportedMediaError
from agno.media import Audio, File, Image
from agno.sandbox.media import decode_media, encode_media

PNG = b"\x89PNG\r\n\x1a\nfixture"


def _decoded() -> dict:
    return decode_media(
        encode_media(
            images=[Image(content=PNG, format="png")],
            files=[File(content=b"a,b\n1,2\n", filename="data.csv", mime_type="text/csv")],
        )
    )


def _named_paths(text: str) -> List[Path]:
    return [Path(match) for match in re.findall(r"^- (/\S+) \(", text, flags=re.MULTILINE)]


@pytest.mark.asyncio
async def test_claude_prompt_names_staged_files_that_exist_with_the_attached_bytes(tmp_path):
    claude_agent_sdk = pytest.importorskip("claude_agent_sdk")
    from agno.agents.claude import ClaudeAgent

    queried: List[Any] = []
    existed: List[bool] = []
    inline: List[str] = []

    class Recorder:
        def __init__(self, options=None):
            self.options = options

        async def connect(self):
            pass

        async def query(self, prompt):
            if not isinstance(prompt, str):
                [message] = [m async for m in prompt]
                text, *blocks = message["message"]["content"]
                prompt = text["text"]
                inline.extend(block["type"] for block in blocks)
            queried.append(prompt)
            existed.extend(path.is_file() for path in _named_paths(prompt))

        async def receive_response(self):
            if False:
                yield None

        async def disconnect(self):
            pass

    agent = ClaudeAgent(cwd=str(tmp_path), keep_uploads=True)
    original = claude_agent_sdk.ClaudeSDKClient
    claude_agent_sdk.ClaudeSDKClient = Recorder
    try:
        await agent.arun("read them", run_id="run-1", session_id="s", **_decoded())
    finally:
        claude_agent_sdk.ClaudeSDKClient = original
    prompt = queried[0]
    assert prompt.startswith("read them") and "Attached files" in prompt
    paths = _named_paths(prompt)
    assert sorted(path.name for path in paths) == ["data.csv", "image-1.png"] and all(existed)
    assert inline == ["image"], "the image is a content block; the csv stays a file for the Read tool"
    assert all(path.is_relative_to(tmp_path / ".agno/uploads/run-1") for path in paths)
    assert {path.name: path.read_bytes() for path in paths} == {"data.csv": b"a,b\n1,2\n", "image-1.png": PNG}
    assert "text/csv" in prompt and "image/png" in prompt


@pytest.mark.asyncio
async def test_codex_turn_input_uses_native_image_items_and_names_files(tmp_path):
    openai_codex = pytest.importorskip("openai_codex")
    from agno.agents._media import stage_media
    from agno.agents.codex import CodexAgent

    agent = CodexAgent(cwd=str(tmp_path), keep_uploads=True)
    staged = stage_media(str(tmp_path), "run-1", agent._media_kwargs(**_decoded())["media"])
    items = agent._turn_input(openai_codex, "read them", staged)
    assert isinstance(items[0], openai_codex.TextInput) and "data.csv" in items[0].text
    assert "image-1.png" not in items[0].text
    images = [item for item in items if isinstance(item, openai_codex.LocalImageInput)]
    assert len(images) == 1 and Path(images[0].path).read_bytes() == PNG
    (csv,) = _named_paths(items[0].text)
    assert csv.read_bytes() == b"a,b\n1,2\n"


@pytest.mark.asyncio
async def test_codex_run_stages_before_the_turn_and_hands_the_staged_media_to_the_sdk_step(tmp_path):
    pytest.importorskip("openai_codex")
    from agno.agents.codex import CodexAgent

    seen = {}

    class Agent(CodexAgent):
        async def _arun_adapter_stream_sdk(self, input, *, history=None, **kwargs):
            seen["staged"] = [(item.kind, item.name, Path(item.path).read_bytes()) for item in kwargs["staged_media"]]
            seen["media_kwarg"] = "media" in kwargs
            return
            yield

    agent = Agent(cwd=str(tmp_path), keep_uploads=True)
    async for _ in agent._arun_adapter_stream(
        "read them", run_id="run-1", media=agent._media_kwargs(**_decoded())["media"]
    ):
        pass
    assert sorted(seen["staged"]) == [("file", "data.csv", b"a,b\n1,2\n"), ("image", "image-1.png", PNG)]
    assert seen["media_kwarg"] is False


@pytest.mark.parametrize("name", ["claude", "codex"])
def test_unsupported_media_is_refused_by_the_installed_adapter_before_any_work(name):
    pytest.importorskip("claude_agent_sdk" if name == "claude" else "openai_codex")
    from agno.agents.claude import ClaudeAgent
    from agno.agents.codex import CodexAgent

    agent = (ClaudeAgent if name == "claude" else CodexAgent)()
    with pytest.raises(UnsupportedMediaError):
        agent._media_kwargs(audio=[Audio(content=b"audio")])
    with pytest.raises(UnsupportedMediaError):
        agent._media_kwargs(videos=[object()])
