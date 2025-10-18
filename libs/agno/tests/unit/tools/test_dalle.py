from types import SimpleNamespace
from pathlib import Path

import pytest

from agno.media import Image
from agno.tools.dalle import DalleTools


class _FakeImages:
    def __init__(self, mode: str = "url"):
        self.mode = mode

    def generate(self, **kwargs):
        if self.mode == "url":
            return SimpleNamespace(data=[SimpleNamespace(url="http://example.com/img.png", revised_prompt=None)])
        else:
            return SimpleNamespace(data=[SimpleNamespace(b64_json="ZmFrZV9pbWFnZV9ieXRlcw==", revised_prompt=None)])

    def edits(self, **kwargs):
        # Accept arbitrary kwargs including file handles for image/mask
        return SimpleNamespace(data=[SimpleNamespace(url="http://example.com/edited.png", revised_prompt=None)])


def _mock_openai(monkeypatch, mode: str = "url"):
    import agno.tools.dalle as dalle_mod

    class _FakeOpenAI:
        def __init__(self, api_key: str | None = None):
            self.images = _FakeImages(mode=mode)

    monkeypatch.setattr(dalle_mod, "OpenAI", _FakeOpenAI)


def test_create_image_url(monkeypatch):
    _mock_openai(monkeypatch, mode="url")
    tools = DalleTools(api_key="test-key", n=1)
    result = tools.create_image(agent=None, prompt="a red apple")
    assert result is not None
    assert result.images is not None and len(result.images) == 1
    assert result.images[0].url == "http://example.com/img.png"


def test_create_image_b64(monkeypatch):
    _mock_openai(monkeypatch, mode="b64")
    tools = DalleTools(api_key="test-key", n=1)
    result = tools.create_image(agent=None, prompt="a blue circle", response_format="b64_json")
    assert result is not None
    assert result.images is not None and len(result.images) == 1
    # base64 path yields content bytes
    assert result.images[0].content is not None


def test_save_image(tmp_path: Path):
    # Provide an Image with raw bytes content
    image = Image(content=b"fake-bytes", mime_type="image/png", format="png")
    tools = DalleTools(api_key="test-key", n=1, enable_create_image=False, **{"enable_save_image": True})
    out_file = tmp_path / "saved.png"
    result = tools.save_image(agent=None, image=image, filepath=str(out_file))
    assert result is not None
    assert out_file.exists()


def test_edit_image_gated_for_dalle3():
    tools = DalleTools(api_key="test-key", model="dall-e-3")
    image = Image(content=b"fake-bytes", mime_type="image/png", format="png")
    result = tools.edit_image(agent=None, image=image, prompt="add a shadow")
    assert "not currently supported" in (result.content or "")


def test_edit_image_dalle2(monkeypatch, tmp_path: Path):
    _mock_openai(monkeypatch, mode="url")
    tools = DalleTools(api_key="test-key", model="dall-e-2", **{"enable_edit_image": True})
    image = Image(content=b"fake-bytes", mime_type="image/png", format="png")
    result = tools.edit_image(agent=None, image=image, prompt="add a shadow")
    assert result is not None
    assert result.images is not None and len(result.images) == 1
    assert result.images[0].url == "http://example.com/edited.png"


