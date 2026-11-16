"""Untrusted website Sources cannot reach private networks or exhaust a worker."""

import asyncio
import socket
from unittest.mock import AsyncMock

import httpx
import pytest

from agno.db.schemas.sources import validate_source_fields
from agno.knowledge.reader.utils.public_fetch import afetch_public_page


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1",
        "http://[::1]",
        "http://169.254.169.254",
        "http://10.0.0.1",
        "http://metadata.google.internal",
    ],
)
def test_source_rejects_private_literal_and_reserved_hosts(url):
    with pytest.raises(ValueError, match="private"):
        validate_source_fields({"type": "website", "reference": url})


class Stream(httpx.AsyncByteStream):
    def __init__(self, chunks, delay=0):
        self.chunks = chunks
        self.delay = delay
        self.closed = False

    async def __aiter__(self):
        for chunk in self.chunks:
            await asyncio.sleep(self.delay)
            yield chunk

    async def aclose(self):
        self.closed = True


def transport(monkeypatch, handler, address="93.184.216.34"):
    dns = AsyncMock(return_value=[(socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, 443))])
    monkeypatch.setattr("agno.knowledge.reader.utils.public_fetch._resolve", dns)
    factory = httpx.AsyncClient
    monkeypatch.setattr(
        httpx, "AsyncClient", lambda **kwargs: factory(transport=httpx.MockTransport(handler), **kwargs)
    )
    return dns


@pytest.mark.asyncio
async def test_dns_rebinding_cannot_change_connection(monkeypatch):
    seen = []

    def serve(request):
        seen.append(request)
        return httpx.Response(200, stream=Stream([b"page"]))

    dns = transport(monkeypatch, serve)
    assert (await afetch_public_page("https://docs.example/page"))[1] == b"page"
    assert len(seen) == dns.await_count == 1
    assert seen[0].url.host == "93.184.216.34"
    assert seen[0].headers["host"] == "docs.example"
    assert seen[0].extensions["sni_hostname"] == "docs.example"


@pytest.mark.asyncio
async def test_private_dns_and_cross_origin_redirect_never_reach_target(monkeypatch):
    requests = []

    def serve(request):
        requests.append(request)
        return httpx.Response(302, headers={"location": "http://127.0.0.1/secret"})

    dns = transport(monkeypatch, serve, "10.0.0.1")
    with pytest.raises(ValueError, match="private"):
        await afetch_public_page("https://docs.example/page")
    assert not requests
    dns.return_value = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))]
    with pytest.raises(ValueError, match="private"):
        await afetch_public_page("https://docs.example/page")
    assert len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["declared", "streamed", "compressed", "trickle"])
async def test_download_limits_close_the_stream(monkeypatch, kind):
    stream = Stream([b"x" * 8] * 20, delay=0.01 if kind == "trickle" else 0)
    headers = (
        {"content-length": "999"}
        if kind == "declared"
        else {"content-encoding": "gzip"}
        if kind == "compressed"
        else {}
    )
    transport(monkeypatch, lambda request: httpx.Response(200, headers=headers, stream=stream))
    with pytest.raises((ValueError, asyncio.TimeoutError)):
        await afetch_public_page("https://docs.example/page", max_bytes=32, deadline=0.025 if kind == "trickle" else 1)
    assert stream.closed
