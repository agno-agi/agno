"""Unit tests for the A2A interface wire-format utilities (a2a-sdk >= 1.0)."""

import json

import pytest
from fastapi import HTTPException

from agno.os.interfaces.a2a.utils import (
    map_a2a_request_to_run_input,
    map_run_output_to_a2a_task,
    session_id_or_new,
    stream_a2a_response,
    stream_a2a_response_with_error_handling,
)
from agno.run.agent import RunCompletedEvent, RunContentEvent, RunOutput, RunStartedEvent
from agno.run.base import RunStatus


def _jsonrpc_request(parts):
    return {
        "jsonrpc": "2.0",
        "id": "req-1",
        "method": "message/send",
        "params": {
            "message": {
                "messageId": "msg-1",
                "role": "ROLE_USER",
                "contextId": "ctx-1",
                "parts": parts,
            }
        },
    }


async def _collect_sse_payloads(stream):
    """Parse SSE chunks into the JSON-RPC `result` payloads, in order."""
    payloads = []
    async for chunk in stream:
        for line in chunk.splitlines():
            if line.startswith("data: "):
                payloads.append(json.loads(line[len("data: ") :])["result"])
    return payloads


async def _event_stream(events):
    for event in events:
        yield event


# --- map_a2a_request_to_run_input ------------------------------------------------


@pytest.mark.asyncio
async def test_legacy_kind_file_part_is_rejected():
    # Pre-1.0 file parts ({"kind": "file", "file": {...}}) cannot be represented in
    # the v1 Part oneof; they must be rejected, not silently dropped.
    body = _jsonrpc_request(
        [
            {"text": "look at this"},
            {"kind": "file", "file": {"uri": "https://example.com/report.pdf"}},
        ]
    )
    with pytest.raises(HTTPException) as exc_info:
        await map_a2a_request_to_run_input(body)
    assert exc_info.value.status_code == 400
    assert "Unsupported content" in exc_info.value.detail


@pytest.mark.asyncio
async def test_url_part_without_media_type_is_kept_as_file():
    body = _jsonrpc_request([{"url": "https://example.com/blob"}])
    run_input = await map_a2a_request_to_run_input(body)
    assert run_input.files is not None
    assert run_input.files[0].url == "https://example.com/blob"


@pytest.mark.asyncio
async def test_raw_part_without_media_type_is_kept_as_file():
    body = _jsonrpc_request([{"raw": "aGVsbG8="}])
    run_input = await map_a2a_request_to_run_input(body)
    assert run_input.files is not None
    assert run_input.files[0].content == b"hello"


@pytest.mark.asyncio
async def test_raw_image_part_maps_to_image_input():
    body = _jsonrpc_request([{"raw": "aGVsbG8=", "mediaType": "image/png"}])
    run_input = await map_a2a_request_to_run_input(body)
    assert run_input.images is not None
    assert run_input.images[0].content == b"hello"


@pytest.mark.asyncio
async def test_unsupported_mime_type_returns_400():
    body = _jsonrpc_request([{"raw": "aGVsbG8=", "mediaType": "application/zip"}])
    with pytest.raises(HTTPException) as exc_info:
        await map_a2a_request_to_run_input(body)
    assert exc_info.value.status_code == 400
    assert "Unsupported media type" in exc_info.value.detail


# --- map_run_output_to_a2a_task ---------------------------------------------------


def test_paused_run_maps_to_input_required():
    output = RunOutput(run_id="r1", session_id="s1", content="need more info", status=RunStatus.paused)
    task = map_run_output_to_a2a_task(output)
    assert task.status.state.__str__() != ""
    from a2a.types import TaskState

    assert task.status.state == TaskState.TASK_STATE_INPUT_REQUIRED


# --- stream_a2a_response ----------------------------------------------------------


@pytest.mark.asyncio
async def test_stream_opens_with_task_and_closes_artifact():
    events = [
        RunStartedEvent(run_id="run-1", session_id="sess-1"),
        RunContentEvent(content="Hello", run_id="run-1", session_id="sess-1"),
        RunContentEvent(content=" world", run_id="run-1", session_id="sess-1"),
        RunCompletedEvent(content="Hello world", run_id="run-1", session_id="sess-1"),
    ]
    payloads = await _collect_sse_payloads(stream_a2a_response(_event_stream(events), "req-1"))

    # 1. The stream must open with the initial Task (SUBMITTED), before any update.
    assert "task" in payloads[0]
    assert payloads[0]["task"]["id"] == "run-1"
    assert payloads[0]["task"]["status"]["state"] == "TASK_STATE_SUBMITTED"

    # 2. WORKING status update follows.
    assert payloads[1]["statusUpdate"]["status"]["state"] == "TASK_STATE_WORKING"

    artifact_updates = [p["artifactUpdate"] for p in payloads if "artifactUpdate" in p]
    assert len(artifact_updates) == 3  # two content chunks + closing marker

    # 3. First chunk creates the artifact: append must be False/absent (proto3 JSON
    #    omits false). a2a-sdk >= 1.1 rejects append=True for an unknown artifact_id.
    assert not artifact_updates[0].get("append", False)
    assert artifact_updates[1]["append"] is True

    # 4. The artifact is closed with last_chunk=True before the terminal status.
    assert artifact_updates[-1]["lastChunk"] is True

    # 5. Terminal status update, then the final Task snapshot last.
    assert payloads[-2]["statusUpdate"]["status"]["state"] == "TASK_STATE_COMPLETED"
    assert payloads[-1]["task"]["status"]["state"] == "TASK_STATE_COMPLETED"

    # All chunks share one artifact id.
    assert len({a["artifact"]["artifactId"] for a in artifact_updates}) == 1


@pytest.mark.asyncio
async def test_stream_without_start_event_still_opens_with_task():
    events = [RunContentEvent(content="Hi", run_id="run-2", session_id="sess-2")]
    payloads = await _collect_sse_payloads(stream_a2a_response(_event_stream(events), "req-1"))
    assert "task" in payloads[0]
    assert payloads[0]["task"]["status"]["state"] == "TASK_STATE_SUBMITTED"


@pytest.mark.asyncio
async def test_empty_stream_emits_initial_task_and_completion():
    payloads = await _collect_sse_payloads(stream_a2a_response(_event_stream([]), "req-1"))
    assert "task" in payloads[0]
    assert payloads[0]["task"]["status"]["state"] == "TASK_STATE_SUBMITTED"
    assert payloads[-2]["statusUpdate"]["status"]["state"] == "TASK_STATE_COMPLETED"
    assert payloads[-1]["task"]["status"]["state"] == "TASK_STATE_COMPLETED"


@pytest.mark.asyncio
async def test_stream_error_does_not_leak_exception_text():
    async def exploding_stream():
        yield RunStartedEvent(run_id="run-3", session_id="sess-3")
        raise RuntimeError("postgres://user:secret@10.0.0.5/prod connection refused")

    payloads = await _collect_sse_payloads(stream_a2a_response_with_error_handling(exploding_stream(), "req-1"))

    failed_task = payloads[-1]["task"]
    assert failed_task["status"]["state"] == "TASK_STATE_FAILED"
    wire_text = json.dumps(payloads)
    assert "secret" not in wire_text
    assert "10.0.0.5" not in wire_text
    assert "internal server error" in wire_text


# --- session_id_or_new (contextId is optional on first contact) ------------------


def test_explicit_context_id_is_honoured():
    assert session_id_or_new("ctx-123") == "ctx-123"


def test_none_context_mints_a_fresh_session():
    minted = session_id_or_new(None)
    assert isinstance(minted, str) and len(minted) > 0


def test_empty_context_mints_a_fresh_session():
    minted = session_id_or_new("")
    assert isinstance(minted, str) and len(minted) > 0


def test_sessionless_calls_get_distinct_sessions():
    assert session_id_or_new(None) != session_id_or_new(None)
