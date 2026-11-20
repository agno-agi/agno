"""Native global-client shutdown overlap with a caller replacing the default."""

import os
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.mark.parametrize("overlap", ["replacement", "shutdown"])
def test_async_shutdown_does_not_block_overlapping_callers(tmp_path: Path, overlap: str) -> None:
    script = tmp_path / "shutdown.py"
    script.write_text(
        """
import asyncio
import sys

import httpx

from agno.utils.http import aclose_default_clients, get_default_async_client, set_default_async_client


async def main():
    closing = asyncio.Event()

    class ObservedClient(httpx.AsyncClient):
        async def aclose(self):
            closing.set()
            # Schedule the replacement during the asynchronous close boundary.
            # The client and its loopback transport remain the real httpx SDK.
            await asyncio.sleep(0)
            await super().aclose()

    async def serve(reader, writer):
        try:
            await reader.readuntil(b"\\r\\n\\r\\n")
            writer.write(b"HTTP/1.1 200 OK\\r\\nContent-Length: 2\\r\\n\\r\\nok")
            await writer.drain()
            await reader.read()
        finally:
            writer.close()
            await writer.wait_closed()

    server = await asyncio.start_server(serve, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    client = ObservedClient()
    replacement = httpx.AsyncClient()
    try:
        assert (await client.get(f"http://127.0.0.1:{port}/")).text == "ok"
        set_default_async_client(client)

        async def replace():
            await closing.wait()
            if sys.argv[1] == "replacement":
                set_default_async_client(replacement)
            else:
                await aclose_default_clients()

        task = asyncio.create_task(replace())
        await aclose_default_clients()
        await task
        assert client.is_closed
        if sys.argv[1] == "replacement":
            assert get_default_async_client() is replacement
            assert not replacement.is_closed
        print("native shutdown and replacement completed")
    finally:
        await aclose_default_clients()
        await client.aclose()
        await replacement.aclose()
        server.close()
        await server.wait_closed()


asyncio.run(main())
""",
        encoding="utf-8",
    )
    source = Path(__file__).resolve().parents[3]
    result = subprocess.run(
        [sys.executable, str(script), overlap],
        capture_output=True,
        text=True,
        timeout=5,
        env={
            **os.environ,
            "PYTHONPATH": os.pathsep.join([str(source), os.environ.get("PYTHONPATH", "")]),
            "AGNO_TELEMETRY": "false",
        },
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "native shutdown and replacement completed"
