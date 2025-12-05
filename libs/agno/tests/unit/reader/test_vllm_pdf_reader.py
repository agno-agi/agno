import asyncio
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from agno.knowledge.document.base import Document
from agno.knowledge.reader.vllm_pdf_reader import VllmPDFReader


@pytest.fixture(scope="session")
def sample_pdf_path(tmp_path_factory) -> Path:
    """Downloads ThaiRecipes.pdf once."""
    tmp_dir = tmp_path_factory.mktemp("vllm_pdf_tests")
    pdf_path = tmp_dir / "ThaiRecipes.pdf"

    if not pdf_path.exists():
        url = "https://agno-public.s3.amazonaws.com/recipes/ThaiRecipes.pdf"
        response = httpx.get(url)
        response.raise_for_status()
        pdf_path.write_bytes(response.content)

    return pdf_path


@pytest.fixture
def dummy_vllm():
    """Fake synchronous-only VLLM."""

    class DummyVllm:
        def __init__(self, caption="This is a test caption."):
            self.caption = caption
            self.calls = []

        def invoke(self, *args, **kwargs):
            self.calls.append((args, kwargs))
            return SimpleNamespace(content=self.caption)

    return DummyVllm()


def test_vllm_pdf_reader_read(sample_pdf_path, dummy_vllm):
    reader = VllmPDFReader(vllm=dummy_vllm)
    documents = reader.read(str(sample_pdf_path))

    assert len(documents) > 0
    assert all(isinstance(doc, Document) for doc in documents)
    assert all("ThaiRecipes" in doc.name for doc in documents)


def test_vllm_pdf_reader_image_captions(sample_pdf_path):
    class FakeVLLM:
        def __init__(self):
            self.calls = []

        def invoke(self, *args, **kwargs):
            self.calls.append((args, kwargs))
            return SimpleNamespace(content="FAKE CAPTION")

    reader = VllmPDFReader(vllm=FakeVLLM())
    documents = reader.read(str(sample_pdf_path))

    images = [d for d in documents if d.meta_data.get("type") == "image"]

    if images:
        assert all(d.content.startswith("[IMAGE CAPTION]") for d in images)


def test_vllm_pdf_reader_invalid_file(dummy_vllm):
    reader = VllmPDFReader(vllm=dummy_vllm)
    assert reader.read("does_not_exist.pdf") == []


@pytest.mark.asyncio
async def test_vllm_pdf_reader_async_read(sample_pdf_path, dummy_vllm):
    reader = VllmPDFReader(vllm=dummy_vllm)
    docs = await reader.async_read(str(sample_pdf_path))

    assert len(docs) > 0
    assert any(d.meta_data.get("type") == "text" for d in docs)
    assert any(d.meta_data.get("type") == "image" for d in docs)


@pytest.mark.asyncio
async def test_vllm_pdf_reader_async_caption_failure(sample_pdf_path):
    """If invoke() fails inside to_thread, caption should fallback."""

    class FailingVLLM:
        def invoke(self, *args, **kwargs):
            raise RuntimeError("Boom")

    reader = VllmPDFReader(vllm=FailingVLLM())
    docs = await reader.async_read(str(sample_pdf_path))

    images = [d for d in docs if d.meta_data.get("type") == "image"]
    if images:
        assert all("(caption unavailable)" in d.content for d in images)


@pytest.mark.asyncio
async def test_async_parallel_processing(sample_pdf_path, dummy_vllm):
    reader = VllmPDFReader(vllm=dummy_vllm)

    tasks = [reader.async_read(str(sample_pdf_path)) for _ in range(3)]
    results = await asyncio.gather(*tasks)

    assert len(results) == 3
    assert all(len(r) > 0 for r in results)


@pytest.mark.asyncio
async def test_vllm_pdf_reader_async_call_count(sample_pdf_path):
    """Ensure each image triggers one .invoke() inside to_thread."""

    class CountingVLLM:
        def __init__(self):
            self.calls = []

        def invoke(self, *args, **kwargs):
            self.calls.append((args, kwargs))
            return SimpleNamespace(content="OK")

    vllm = CountingVLLM()
    reader = VllmPDFReader(vllm=vllm)

    docs = await reader.async_read(str(sample_pdf_path))

    images = [d for d in docs if d.meta_data.get("type") == "image"]

    if images:
        assert len(vllm.calls) >= len(images)
