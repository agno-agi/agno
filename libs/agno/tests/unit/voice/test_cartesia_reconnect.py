"""CartesiaTTS reopens a WebSocket that died between replies; no network."""

import asyncio
import base64
import json

import pytest
from websockets.protocol import State

from agno.voice.tts.cartesia import CartesiaTTS, _CartesiaSession


class CartesiaSocket:
    """Answers each Cartesia request with one audio chunk and a done event."""

    def __init__(self, state=State.OPEN):
        self.state = state
        self.sent = []
        self.events = asyncio.Queue()
        self.closed = False

    async def send(self, message):
        request = json.loads(message)
        self.sent.append(request)
        if request.get("cancel"):
            return
        context_id = request["context_id"]
        if request["transcript"]:
            chunk = base64.b64encode(bytes(480)).decode()
            await self.events.put(json.dumps({"type": "chunk", "context_id": context_id, "data": chunk}))
        if not request["continue"]:
            await self.events.put(json.dumps({"type": "done", "context_id": context_id}))

    async def recv(self):
        return await self.events.get()

    async def close(self):
        self.closed = True
        self.state = State.CLOSED


async def words(*parts):
    for part in parts:
        yield part


@pytest.mark.asyncio
async def test_cartesia_reopens_a_socket_that_died_between_replies():
    # For example, the keepalive ping timed out during a long tool run.
    dead, fresh = CartesiaSocket(state=State.CLOSED), CartesiaSocket()
    opened = []

    async def open_socket():
        opened.append(fresh)
        return fresh

    session = _CartesiaSession(dead, CartesiaTTS(api_key="key"), open_socket)
    chunks = [chunk async for chunk in session._synthesize(words("Still here."))]
    assert opened == [fresh] and dead.closed
    assert session._connection is fresh
    assert b"".join(chunk.audio for chunk in chunks) == bytes(480)
    assert dead.sent == [] and fresh.sent


@pytest.mark.asyncio
async def test_cartesia_keeps_an_open_socket_between_replies():
    socket = CartesiaSocket()

    async def open_socket():
        raise AssertionError("An open socket must be reused.")

    session = _CartesiaSession(socket, CartesiaTTS(api_key="key"), open_socket)
    for text in ("First.", "Second."):
        chunks = [chunk async for chunk in session._synthesize(words(text))]
        assert b"".join(chunk.audio for chunk in chunks) == bytes(480)
    assert session._connection is socket
