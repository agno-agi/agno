"""Async-twin tests for the polling / wait tools — one test per affected tool.

Each test covers the toolkit's ``async_tools`` registration plus the behavior of
its new async twin(s): ``asyncio.to_thread``-backed (lumalab, scrapegraph, e2b),
``httpx.AsyncClient``-backed (brightdata, models_labs), or ``asyncio.sleep``
(sleep). The Gemini test also exercises the deadline guard added to the (sync)
``generate_video`` loop. Toolkits with optional deps use ``pytest.importorskip``.
"""

import json
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest


def _patch_async_client(*, post=None, get=None):
    """Stand-in for ``httpx.AsyncClient(...)`` used as ``async with ... as client``."""
    client = MagicMock()
    client.post = AsyncMock(side_effect=post) if post is not None else AsyncMock()
    client.get = AsyncMock(side_effect=get) if get is not None else AsyncMock()
    factory = MagicMock()
    factory.return_value.__aenter__.return_value = client
    factory.return_value.__aexit__.return_value = False
    return factory


async def test_lumalab():
    pytest.importorskip("lumaai")
    from agno.tools.lumalab import LumaLabTools

    with patch("agno.tools.lumalab.LumaAI"), patch("agno.tools.lumalab.AsyncLumaAI"):
        assert set(LumaLabTools(api_key="k", all=True).async_functions) == {"generate_video", "image_to_video"}

    running = Mock(id="g1", state="dreaming", assets=None)
    done = Mock(id="g1", state="completed")
    done.assets = Mock(video="https://cdn/x.mp4")
    async_client = MagicMock()
    async_client.generations.create = AsyncMock(return_value=running)
    async_client.generations.get = AsyncMock(side_effect=[running, done])
    with patch("agno.tools.lumalab.LumaAI"), patch("agno.tools.lumalab.AsyncLumaAI"):
        tools = LumaLabTools(api_key="k", poll_interval=2, all=True)
    tools.async_client = async_client
    with patch("agno.tools.lumalab.asyncio.sleep", new_callable=AsyncMock) as slept:
        result = await tools.agenerate_video(agent=Mock(), prompt="a cat")
    assert async_client.generations.get.await_count == 2
    slept.assert_awaited_with(2)
    assert result.videos is not None and result.videos[0].url == "https://cdn/x.mp4"

    stuck = MagicMock()
    stuck.generations.create = AsyncMock(return_value=running)
    stuck.generations.get = AsyncMock(return_value=running)
    with patch("agno.tools.lumalab.LumaAI"), patch("agno.tools.lumalab.AsyncLumaAI"):
        tools = LumaLabTools(api_key="k", poll_interval=10, max_wait_time=20, all=True)
    tools.async_client = stuck
    with patch("agno.tools.lumalab.asyncio.sleep", new_callable=AsyncMock):
        result = await tools.agenerate_video(agent=Mock(), prompt="a cat")
    assert "timed out" in result.content.lower()


async def test_scrapegraph():
    pytest.importorskip("scrapegraph_py")
    from agno.tools.scrapegraph import ScrapeGraphTools

    with (
        patch("agno.tools.scrapegraph.ScrapeGraphAI"),
        patch("agno.tools.scrapegraph.AsyncScrapeGraphAI"),
        patch.dict("os.environ", {"SGAI_API_KEY": "k"}),
    ):
        tools = ScrapeGraphTools(all=True)
    assert "crawl" in tools.async_functions

    finished = Mock(id="c1", status="completed")
    finished.model_dump_json.return_value = '{"pages": []}'
    async_client = MagicMock()
    async_client.crawl.start = AsyncMock(return_value=Mock(status="success", data=finished))
    async_client.crawl.get = AsyncMock()
    tools.async_client = async_client
    with patch("agno.tools.scrapegraph.asyncio.sleep", new_callable=AsyncMock) as slept:
        result = await tools.acrawl("https://x.com", prompt="p", schema={"type": "object"})
    assert not async_client.crawl.get.called
    slept.assert_not_awaited()
    assert result == '{"pages": []}'


async def test_brightdata():
    pytest.importorskip("requests")
    from agno.tools.brightdata import BrightDataTools

    tools = BrightDataTools(api_key="k")
    assert "web_data_feed" in tools.async_functions

    trigger = Mock()
    trigger.json.return_value = {"snapshot_id": "s1"}
    snapshot = Mock()
    snapshot.json.return_value = {"status": "ready", "data": [{"x": 1}]}
    with patch("agno.tools.brightdata.httpx.AsyncClient", _patch_async_client(post=[trigger], get=[snapshot])):
        result = await tools.aweb_data_feed("amazon_product", "https://x.com")
    assert json.loads(result) == {"status": "ready", "data": [{"x": 1}]}


async def test_models_labs():
    pytest.importorskip("requests")
    from agno.models.response import FileType
    from agno.tools.models_labs import ModelsLabTools

    tools = ModelsLabTools(api_key="k", file_type=FileType.PNG)
    assert "generate_media" in tools.async_functions

    response = Mock()
    response.json.return_value = {"status": "success", "eta": None, "output": ["https://cdn/img.png"]}
    with patch("agno.tools.models_labs.httpx.AsyncClient", _patch_async_client(post=[response])):
        result = await tools.agenerate_media("a sunset")
    assert result.images is not None and result.images[0].url == "https://cdn/img.png"


def test_gemini():
    pytest.importorskip("google.genai")
    from agno.tools.models.gemini import GeminiTools

    with patch("agno.tools.models.gemini.Client"):
        tools = GeminiTools(api_key="k", enable_generate_video=True)
    assert "generate_video" in tools.async_functions
    assert (tools.poll_interval, tools.max_wait_time) == (5, 600)

    op = Mock(done=False)
    client = Mock()
    client.models.generate_videos.return_value = op
    client.operations.get.return_value = op
    with patch("agno.tools.models.gemini.Client", return_value=client):
        tools = GeminiTools(vertexai=True, poll_interval=5, max_wait_time=10, enable_generate_video=True)
    with patch("agno.tools.models.gemini.time.sleep") as slept:
        result = tools.generate_video(agent=Mock(), prompt="a dog")
    assert "timed out" in result.content.lower()
    assert slept.call_count == 2


async def test_gemini_async():
    pytest.importorskip("google.genai")
    from agno.tools.models.gemini import GeminiTools

    op_running = Mock(done=False, result=None)
    op_done = Mock(done=True)
    op_done.result = Mock(generated_videos=[])
    client = MagicMock()
    client.aio.models.generate_videos = AsyncMock(return_value=op_running)
    client.aio.operations.get = AsyncMock(side_effect=[op_running, op_done])
    with patch("agno.tools.models.gemini.Client", return_value=client):
        tools = GeminiTools(vertexai=True, poll_interval=1, max_wait_time=10, enable_generate_video=True)

    with patch("agno.tools.models.gemini.asyncio.sleep", new_callable=AsyncMock) as slept:
        result = await tools.agenerate_video(agent=Mock(), prompt="a dog")

    client.aio.models.generate_videos.assert_awaited_once()
    assert client.aio.operations.get.await_count == 2
    slept.assert_awaited_with(1)
    assert "No videos were generated" in result.content


async def test_sleep():
    from agno.tools.sleep import SleepTools

    tools = SleepTools()
    assert "sleep" in tools.async_functions

    with patch("agno.tools.sleep.asyncio.sleep", new_callable=AsyncMock) as slept:
        result = await tools.asleep(3)
    slept.assert_awaited_once_with(3)
    assert result == "Slept for 3 seconds"


async def test_e2b():
    pytest.importorskip("e2b_code_interpreter")
    from agno.tools.e2b import E2BTools

    sandbox = Mock()
    sandbox.get_host.return_value = "host123"
    with patch("agno.tools.e2b.Sandbox") as sandbox_cls, patch.dict("os.environ", {"E2B_API_KEY": "k"}):
        sandbox_cls.create.return_value = sandbox
        tools = E2BTools()
    assert "run_server" in tools.async_functions

    with patch("agno.tools.e2b.asyncio.sleep", new_callable=AsyncMock) as slept:
        url = await tools.arun_server("python -m http.server 8000", 8000)
    slept.assert_awaited_once_with(2)
    sandbox.commands.run.assert_called_once_with("python -m http.server 8000", background=True)
    assert url == "http://host123"
