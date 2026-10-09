"""Opt-in real harness examples and loopback HTTP tests; no mocked model calls."""

import asyncio
import hashlib
import json
import os
import runpy
import socket
import subprocess
import sys
import time
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[5]
COOKBOOK = ROOT / "cookbook/harnesses"
GATES = {"claude": "AGNO_TEST_CLAUDE_SDK", "codex": "AGNO_TEST_CODEX_SDK"}
PROMPT = (
    "Read shipping.py and orders.json with your file or shell tools. "
    "Explain the shipping fee for each order and the boundary condition. "
    "Do not modify files or use the network."
)


def _require_live(provider):
    if os.getenv(GATES[provider]) != "1":
        pytest.skip(f"Set {GATES[provider]}=1 with working SDK authentication")


def _fixture_digest():
    return {
        str(path.relative_to(COOKBOOK)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in (COOKBOOK / "sample_project").rglob("*")
        if path.is_file()
    }


@pytest.mark.parametrize("provider", GATES)
@pytest.mark.parametrize("example", ["native_sdk.py", "basic.py", "tools.py"])
def test_live_harness_script(provider, example, tmp_path):
    _require_live(provider)
    before = _fixture_digest()
    result = subprocess.run(
        [sys.executable, "-u", str(COOKBOOK / provider / example)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=180,
    )
    (tmp_path / "output.log").write_text(result.stdout + result.stderr)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Status:" in result.stdout
    if example == "tools.py":
        assert "ToolCallStarted:" in result.stdout
        assert "ToolCallCompleted:" in result.stdout
        # The returned tool data must contain fixture content, not just a claimed read.
        assert "subtotal" in result.stdout and "boundary" in result.stdout
    assert _fixture_digest() == before, "The read-only exercise modified its fixture"


@contextmanager
def _server(provider, tmp_path):
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    env = dict(os.environ, PORT=str(port), HARNESS_STATE_DIR=str(tmp_path / "state"))
    log_path = tmp_path / "server.log"
    with log_path.open("w") as log:
        process = subprocess.Popen(
            [sys.executable, "-u", str(COOKBOOK / provider / "agent_os.py")],
            cwd=ROOT,
            env=env,
            stdout=log,
            stderr=subprocess.STDOUT,
        )
        try:
            with httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=120, trust_env=False) as client:
                deadline = time.monotonic() + 30
                while time.monotonic() < deadline:
                    assert process.poll() is None, log_path.read_text()
                    try:
                        if client.get("/health", timeout=1).is_success:
                            break
                    except httpx.HTTPError:
                        pass
                    time.sleep(0.1)
                else:
                    pytest.fail("AgentOS did not become healthy: " + log_path.read_text())
                yield client
        finally:
            process.terminate()
            try:
                process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)


def _assert_stored_run(client, provider, session_id, run_id):
    response = client.get(f"/agents/{provider}-reviewer/runs/{run_id}", params={"session_id": session_id})
    response.raise_for_status()
    run = response.json()
    assert run["status"] == "COMPLETED", run
    assert run["content"], run
    assert run["tools"], run
    results = [str(tool.get("result", "")) for tool in run["tools"] if not tool.get("tool_call_error")]
    assert any("subtotal" in result for result in results), results
    return run


@pytest.mark.parametrize("provider", GATES)
def test_live_harness_agentos_http(provider, tmp_path):
    _require_live(provider)
    before = _fixture_digest()
    with _server(provider, tmp_path) as client:
        agents = client.get("/agents")
        agents.raise_for_status()
        assert any(agent["id"] == f"{provider}-reviewer" for agent in agents.json())

        session_id = str(uuid4())
        response = client.post(
            f"/agents/{provider}-reviewer/runs",
            data={"message": PROMPT, "session_id": session_id, "stream": "false"},
        )
        response.raise_for_status()
        result = response.json()
        assert result["status"] == "COMPLETED", result
        stored = _assert_stored_run(client, provider, session_id, result["run_id"])
        (tmp_path / "nonstream.json").write_text(json.dumps(stored, indent=2))

        # A fresh session makes both requests exercise tool execution independently.
        session_id = str(uuid4())
        events = []
        with client.stream(
            "POST",
            f"/agents/{provider}-reviewer/runs",
            data={"message": PROMPT, "session_id": session_id, "stream": "true"},
        ) as response:
            response.raise_for_status()
            assert "text/event-stream" in response.headers["content-type"]
            for line in response.iter_lines():
                if line.startswith("data: "):
                    events.append(json.loads(line[6:]))
        (tmp_path / "events.json").write_text(json.dumps(events, indent=2))
        names = [event.get("event") for event in events]
        assert "RunError" not in names and "RunCancelled" not in names, events
        assert names[0] == "RunStarted", events
        for name in ("RunContent", "ToolCallStarted", "ToolCallCompleted", "RunCompleted"):
            assert name in names, events
        run_id = events[0]["run_id"]
        assert all(event.get("run_id") == run_id for event in events), events
        stored = _assert_stored_run(client, provider, session_id, run_id)
        (tmp_path / "stream.json").write_text(json.dumps(stored, indent=2))
    assert _fixture_digest() == before, "The read-only API exercise modified its fixture"


@pytest.mark.asyncio
async def test_live_claude_native_options():
    """The native comparison's options can be reused directly by the Agno adapter."""
    _require_live("claude")
    from agno.agents.claude import ClaudeAgent
    from agno.run.base import RunStatus

    example = runpy.run_path(str(COOKBOOK / "claude/native_sdk.py"))
    options = example["options"]
    original = (options.resume, options.include_partial_messages, list(options.tools))
    agent = ClaudeAgent(id="claude-native-options", options=options)
    result = await asyncio.wait_for(agent.arun(example["prompt"]), timeout=120)
    assert result.status == RunStatus.completed, result.content
    assert result.content
    assert (options.resume, options.include_partial_messages, options.tools) == original
