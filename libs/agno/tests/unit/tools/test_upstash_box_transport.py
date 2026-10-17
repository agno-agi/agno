"""UpstashBoxTools over a real HTTP transport.

Runs the real `upstash-box` SDK against a minimal local stand-in for the Box API,
because event-loop ownership of async connections only shows up with a real
`httpx.AsyncClient`, never with mocks. Skipped when `upstash-box` is not installed.
"""

import asyncio
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, Iterator

import pytest

pytest.importorskip("upstash_box")

from agno.run import RunContext  # noqa: E402
from agno.tools.upstash_box import SESSION_STATE_BOX_ID, UpstashBoxTools  # noqa: E402


class _FakeBoxAPI(BaseHTTPRequestHandler):
    """Just enough of the Box API: create, get, status, and exec."""

    protocol_version = "HTTP/1.1"
    created: Dict[str, Any] = {}

    def _send(self, code: int, body: Dict[str, Any]) -> None:
        data = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _read_body(self) -> None:
        length = int(self.headers.get("content-length", 0))
        if length:
            self.rfile.read(length)

    def do_POST(self) -> None:  # noqa: N802
        self._read_body()
        if self.path == "/v2/box":
            box_id = f"box-{len(self.created) + 1}"
            self.created[box_id] = True
            return self._send(200, {"id": box_id, "status": "idle", "created_at": 0, "updated_at": 0})
        if self.path.endswith("/exec"):
            return self._send(200, {"exit_code": 0, "output": "ok\n"})
        self._send(404, {"error": "not found"})

    def do_GET(self) -> None:  # noqa: N802
        box_id = self.path.split("/")[3]
        if self.path.endswith("/status"):
            return self._send(200, {"status": "idle"})
        self._send(200, {"id": box_id, "status": "idle", "created_at": 0, "updated_at": 0})

    def log_message(self, *args: Any) -> None:
        pass


@pytest.fixture
def box_api() -> Iterator[str]:
    _FakeBoxAPI.created = {}
    server = ThreadingHTTPServer(("127.0.0.1", 0), _FakeBoxAPI)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()
    server.server_close()


def test_async_tools_work_across_event_loops(box_api):
    # Each asyncio.run() is a new event loop; the second must not reuse the first
    # loop's connections ("Event loop is closed"), but reconnect to the same box.
    tools = UpstashBoxTools(api_key="box_test", base_url=box_api)
    run_context = RunContext(run_id="r", session_id="s", session_state={})

    first = asyncio.run(tools.arun_command(run_context, "echo first"))
    second = asyncio.run(tools.arun_command(run_context, "echo second"))

    assert first == "STDOUT:\nok\n\nExit code: 0"
    assert second == "STDOUT:\nok\n\nExit code: 0"
    assert list(_FakeBoxAPI.created) == ["box-1"]
    assert run_context.session_state[SESSION_STATE_BOX_ID] == "box-1"


def test_sync_and_async_tools_share_a_box_over_http(box_api):
    tools = UpstashBoxTools(api_key="box_test", base_url=box_api, persistent=False)
    run_context = RunContext(run_id="r", session_id="s", session_state={})

    tools.run_command(run_context, "echo sync")
    asyncio.run(tools.arun_command(run_context, "echo async"))

    assert list(_FakeBoxAPI.created) == ["box-1"]
