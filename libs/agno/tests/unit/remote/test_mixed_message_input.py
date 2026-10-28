"""Remote clients preserve mixed Message and dictionary conversation entries."""

import asyncio
import json
from urllib.parse import parse_qs

import httpx
import pytest

from agno.agent.remote import RemoteAgent
from agno.models.message import Message
from agno.team.remote import RemoteTeam
from agno.utils import http
from agno.utils.remote import serialize_input
from agno.workflow.remote import RemoteWorkflow


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["agent", "team", "workflow"])
async def test_remote_run_sends_mixed_conversation_to_loopback(monkeypatch, kind):
    requests = []
    handlers = set()

    async def serve(reader, writer):
        task = asyncio.current_task()
        handlers.add(task)
        try:
            headers = await reader.readuntil(b"\r\n\r\n")
            length = next(
                int(line.split(b":", 1)[1])
                for line in headers.split(b"\r\n")
                if line.lower().startswith(b"content-length:")
            )
            body = await reader.readexactly(length)
            requests.append((headers.split(b"\r\n", 1)[0], parse_qs(body.decode("utf-8"))))
            payload = json.dumps({"run_id": "native-run", "content": "ok"}).encode()
            writer.write(
                b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nConnection: close\r\nContent-Length: "
                + str(len(payload)).encode()
                + b"\r\n\r\n"
                + payload
            )
            await writer.drain()
        finally:
            writer.close()
            await writer.wait_closed()
            handlers.discard(task)

    server = await asyncio.start_server(serve, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    async with httpx.AsyncClient(trust_env=False) as client:
        monkeypatch.setattr(http, "_global_async_client", client)
        try:
            constructors = {
                "agent": lambda: RemoteAgent(base_url=f"http://127.0.0.1:{port}", agent_id="native"),
                "team": lambda: RemoteTeam(base_url=f"http://127.0.0.1:{port}", team_id="native"),
                "workflow": lambda: RemoteWorkflow(base_url=f"http://127.0.0.1:{port}", workflow_id="native"),
            }
            remote = constructors[kind]()
            messages = [Message(role="system", content="instructions"), {"role": "user", "content": "hello"}]
            response = await asyncio.wait_for(remote.arun(messages), timeout=5)
            assert response.content == "ok"
            assert len(requests) == 1
            request_line, form = requests[0]
            assert request_line == f"POST /{kind}s/native/runs HTTP/1.1".encode()
            assert json.loads(form["message"][0]) == [messages[0].to_dict(), messages[1]]
            assert form["stream"] == ["false"]
        finally:
            server.close()
            await server.wait_closed()
            if handlers:
                await asyncio.wait_for(asyncio.gather(*handlers), timeout=5)


@pytest.mark.parametrize(
    "messages",
    [
        [],
        [{"role": "user", "content": "hello"}],
        [Message(role="user", content="hello")],
        [{"role": "system", "content": "instructions"}, Message(role="user", content="hello")],
    ],
)
def test_serialization_preserves_each_entry(messages):
    assert json.loads(serialize_input(messages)) == [
        message.to_dict() if isinstance(message, Message) else message for message in messages
    ]
