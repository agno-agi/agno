"""Bound native page fetching at the public concurrency boundary."""

import asyncio

import pytest

pytest.importorskip("bs4")
from agno.knowledge.reader.page_fetcher import HttpxPageFetcher, ParallelPageFetcher


@pytest.mark.parametrize("fetcher_type", [HttpxPageFetcher, ParallelPageFetcher])
async def test_zero_concurrency_is_rejected_before_a_hanging_fetch(fetcher_type):
    try:
        kwargs = {"concurrency": 0}
        if fetcher_type is ParallelPageFetcher:
            kwargs.update(api_key="", fallback=HttpxPageFetcher(concurrency=1))
        fetcher = fetcher_type(**kwargs)
    except ValueError as exc:
        assert "concurrency" in str(exc)
        return
    # Even an off-host-filter-free local request never reaches HTTP with zero permits.
    # A bounded deadline turns the native semaphore hang into a test failure.
    await asyncio.wait_for(fetcher.afetch_many(["http://127.0.0.1:1/page"]), timeout=0.2)
    pytest.fail("Zero concurrency was accepted")


@pytest.mark.parametrize("fetcher_type", [HttpxPageFetcher, ParallelPageFetcher])
def test_negative_concurrency_is_rejected_at_construction(fetcher_type):
    with pytest.raises(ValueError, match="concurrency"):
        fetcher_type(concurrency=-1)


async def test_positive_concurrency_fetches_real_loopback_pages(monkeypatch):
    # Environment proxy settings must not redirect the owned loopback fixture.
    monkeypatch.setenv("NO_PROXY", "127.0.0.1")
    handlers = set()
    paths = []

    async def respond(reader, writer):
        task = asyncio.current_task()
        handlers.add(task)
        try:
            request = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), timeout=5)
            paths.append(request.split(b" ")[1].decode())
            writer.write(
                b"HTTP/1.1 200 OK\r\nContent-Type: text/plain\r\nContent-Length: 12\r\nConnection: close\r\n\r\nNative page!"
            )
            await writer.drain()
        finally:
            writer.close()
            await writer.wait_closed()
            handlers.discard(task)

    server = await asyncio.start_server(respond, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    urls = [f"http://127.0.0.1:{port}/{index}" for index in range(3)]
    try:
        pages = await asyncio.wait_for(HttpxPageFetcher(concurrency=1).afetch_many(urls), timeout=5)
        assert [page.url for page in pages] == urls
        assert all(page.ok and page.content == "Native page!" for page in pages)
        assert paths == ["/0", "/1", "/2"]
    finally:
        server.close()
        await server.wait_closed()
        if handlers:
            await asyncio.wait_for(asyncio.gather(*handlers), timeout=5)
